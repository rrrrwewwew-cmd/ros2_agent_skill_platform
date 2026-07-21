"""Read-only ROS 2 evidence adapter for ``check_robot_health``."""

import json
import time

from diagnostic_msgs.msg import DiagnosticArray
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from rosidl_runtime_py.utilities import get_message
from std_msgs.msg import Bool
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from .health import (
    evaluate_health_snapshot,
    HealthEvidenceError,
    validate_required_sensors,
)


def _stamp_ns(message, fallback_ns):
    header = getattr(message, 'header', None)
    stamp = getattr(header, 'stamp', None)
    if stamp is None:
        return fallback_ns
    seconds = int(getattr(stamp, 'sec', 0))
    nanoseconds = int(getattr(stamp, 'nanosec', 0))
    return seconds * 1_000_000_000 + nanoseconds


def _diagnostic_level(value):
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(value, byteorder='little')
    return int(value)


class RosHealthEvidenceNode(Node):
    """Collect bounded evidence without publishing or changing ROS state."""

    def __init__(self, required_sensors=None):
        super().__init__('check_robot_health_skill')
        self.declare_parameter(
            'required_sensors', Parameter.Type.STRING_ARRAY,
        )
        self.declare_parameter('collection_timeout_sec', 5.0)
        self.declare_parameter('max_tf_age_sec', 0.5)
        self.declare_parameter('max_diagnostic_age_sec', 2.0)
        self.declare_parameter('max_sensor_age_sec', 1.0)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('robot_frame', 'base_footprint')
        self.declare_parameter(
            'diagnostic_name_contains', 'keepout_safety_monitor',
        )
        if required_sensors is None:
            try:
                configured_sensors = self.get_parameter(
                    'required_sensors'
                ).get_parameter_value().string_array_value
            except rclpy.exceptions.ParameterUninitializedException:
                configured_sensors = []
        else:
            configured_sensors = []
        self.required_sensors = validate_required_sensors(
            required_sensors if required_sensors is not None
            else configured_sensors
        )
        self.collection_timeout_sec = float(
            self.get_parameter('collection_timeout_sec').value
        )
        self.map_frame = str(self.get_parameter('map_frame').value)
        self.robot_frame = str(self.get_parameter('robot_frame').value)
        self.diagnostic_name_contains = str(
            self.get_parameter('diagnostic_name_contains').value
        ).lower()
        self.configuration = {
            'max_tf_age_sec': float(
                self.get_parameter('max_tf_age_sec').value
            ),
            'max_diagnostic_age_sec': float(
                self.get_parameter('max_diagnostic_age_sec').value
            ),
            'max_sensor_age_sec': float(
                self.get_parameter('max_sensor_age_sec').value
            ),
        }
        if not 0 < self.collection_timeout_sec <= 10.0:
            raise HealthEvidenceError(
                'collection_timeout_sec must be in (0, 10]'
            )

        read_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._sensor_qos = sensor_qos
        self._nav2_client = self.create_client(
            Trigger, '/lifecycle_manager_navigation/is_active',
        )
        self._nav2_future = None
        self._nav2 = {
            'response_received': False,
            'active': False,
            'message': 'service response not received',
        }
        self._semantic_safety = {
            'topic_received': False,
            'topic_ok': False,
            'diagnostic_received': False,
            'diagnostic_level': None,
            'diagnostic_message': 'matching diagnostic not received',
            'diagnostic_stamp_ns': None,
        }
        self._transform = {
            'available': False,
            'target_frame': self.map_frame,
            'source_frame': self.robot_frame,
            'error': 'transform not received',
        }
        self._sensors = {
            topic: {
                'publisher_count': 0,
                'message_received': False,
                'types': [],
            }
            for topic in self.required_sensors
        }
        self._sensor_subscriptions = {}
        self._safety_subscription = self.create_subscription(
            Bool,
            '/semantic_keepout/safety_ok',
            self._on_safety,
            read_qos,
        )
        self._diagnostic_subscription = self.create_subscription(
            DiagnosticArray,
            '/diagnostics',
            self._on_diagnostics,
            read_qos,
        )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(
            self._tf_buffer, self, spin_thread=False,
        )

    def _now_ns(self):
        return self.get_clock().now().nanoseconds

    def _on_safety(self, message):
        self._semantic_safety['topic_received'] = True
        self._semantic_safety['topic_ok'] = bool(message.data)
        self._semantic_safety['topic_received_at_ns'] = self._now_ns()

    def _on_diagnostics(self, message):
        for status in message.status:
            if self.diagnostic_name_contains not in status.name.lower():
                continue
            self._semantic_safety.update({
                'diagnostic_received': True,
                'diagnostic_name': status.name,
                'diagnostic_level': _diagnostic_level(status.level),
                'diagnostic_message': status.message,
                'diagnostic_stamp_ns': _stamp_ns(
                    message, self._now_ns(),
                ),
                'diagnostic_values': {
                    value.key: value.value for value in status.values
                },
            })
            break

    def _start_nav2_request(self):
        if self._nav2_future is not None:
            return
        if self._nav2_client.service_is_ready():
            self._nav2_future = self._nav2_client.call_async(
                Trigger.Request()
            )

    def _update_nav2_result(self):
        if self._nav2_future is None or not self._nav2_future.done():
            return
        if self._nav2['response_received']:
            return
        try:
            response = self._nav2_future.result()
        except Exception as exception:  # rclpy future transports typed errors
            self._nav2['message'] = str(exception)
            return
        self._nav2 = {
            'response_received': True,
            'active': bool(response.success),
            'message': response.message,
            'observed_at_ns': self._now_ns(),
        }

    def _update_transform(self):
        try:
            transform = self._tf_buffer.lookup_transform(
                self.map_frame, self.robot_frame, Time(),
            )
        except TransformException as exception:
            self._transform['error'] = str(exception)
            return
        self._transform = {
            'available': True,
            'stamp_ns': _stamp_ns(transform, self._now_ns()),
            'target_frame': self.map_frame,
            'source_frame': self.robot_frame,
        }

    def _sensor_callback(self, topic):
        def callback(message):
            received_at_ns = self._now_ns()
            self._sensors[topic].update({
                'message_received': True,
                'stamp_ns': _stamp_ns(message, received_at_ns),
                'received_at_ns': received_at_ns,
            })
        return callback

    def _refresh_sensors(self):
        topic_types = dict(self.get_topic_names_and_types())
        for topic in self.required_sensors:
            evidence = self._sensors[topic]
            evidence['publisher_count'] = self.count_publishers(topic)
            evidence['types'] = list(topic_types.get(topic, []))
            if topic in self._sensor_subscriptions:
                continue
            if not evidence['types']:
                continue
            try:
                message_type = get_message(evidence['types'][0])
                subscription = self.create_subscription(
                    message_type,
                    topic,
                    self._sensor_callback(topic),
                    self._sensor_qos,
                )
            except (AttributeError, ImportError, ModuleNotFoundError,
                    RuntimeError, ValueError) as exception:
                evidence['subscription_error'] = str(exception)
                continue
            self._sensor_subscriptions[topic] = subscription

    def _all_evidence_received(self):
        return (
            self._nav2['response_received'] and
            self._transform['available'] and
            self._semantic_safety['topic_received'] and
            self._semantic_safety['diagnostic_received'] and
            all(
                evidence['message_received']
                for evidence in self._sensors.values()
            )
        )

    def collect(self):
        """Collect a bounded snapshot from declared read-only interfaces."""
        deadline = time.monotonic() + self.collection_timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            self._start_nav2_request()
            self._refresh_sensors()
            rclpy.spin_once(self, timeout_sec=0.05)
            self._update_nav2_result()
            self._update_transform()
            if self._all_evidence_received():
                break
        self._refresh_sensors()
        self._update_nav2_result()
        self._update_transform()
        return {
            'observed_at_ns': self._now_ns(),
            'configuration': dict(self.configuration),
            'nav2': dict(self._nav2),
            'transform': dict(self._transform),
            'semantic_safety': dict(self._semantic_safety),
            'sensors': {
                topic: dict(evidence)
                for topic, evidence in self._sensors.items()
            },
        }


def collect_ros_health_snapshot(required_sensors=None):
    """Create a temporary ROS node and return its bounded evidence."""
    owns_context = not rclpy.ok()
    if owns_context:
        rclpy.init()
    node = None
    try:
        node = RosHealthEvidenceNode(required_sensors=required_sensors)
        return node.collect()
    finally:
        if node is not None:
            node.destroy_node()
        if owns_context and rclpy.ok():
            rclpy.shutdown()


def main(args=None):
    """Run the ROS health adapter and print its structured Skill result."""
    rclpy.init(args=args)
    try:
        node = RosHealthEvidenceNode()
        try:
            snapshot = node.collect()
            result = evaluate_health_snapshot(
                snapshot,
                required_sensors=node.required_sensors,
                **node.configuration,
            )
        finally:
            node.destroy_node()
    except (HealthEvidenceError, rclpy.exceptions.ROSInterruptException,
            RuntimeError) as exception:
        print(json.dumps({
            'schema_version': 1,
            'skill': 'check_robot_health',
            'state': 'unsafe',
            'error': str(exception),
        }, ensure_ascii=False, indent=2))
        return 4
    finally:
        if rclpy.ok():
            rclpy.shutdown()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return {'healthy': 0, 'degraded': 3, 'unsafe': 4}[result['state']]


if __name__ == '__main__':
    raise SystemExit(main())
