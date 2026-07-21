"""Isolated ROS graph integration test for the health evidence adapter."""

from threading import Thread

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import TransformStamped
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from safe_agent_core.health import evaluate_health_snapshot
from safe_agent_core.health_ros import RosHealthEvidenceNode
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster


class HealthyEvidenceProvider(Node):
    """Publish only the interfaces declared by the reference Skill."""

    def __init__(self):
        super().__init__('healthy_evidence_provider')
        self.safety_publisher = self.create_publisher(
            Bool, '/semantic_keepout/safety_ok', 10,
        )
        self.diagnostic_publisher = self.create_publisher(
            DiagnosticArray, '/diagnostics', 10,
        )
        self.sensor_publisher = self.create_publisher(
            String, '/scan', 10,
        )
        self.nav2_service = self.create_service(
            Trigger,
            '/lifecycle_manager_navigation/is_active',
            self._on_nav2_health,
        )
        self.transform_broadcaster = TransformBroadcaster(self)
        self.timer = self.create_timer(0.05, self._publish_evidence)

    def _on_nav2_health(self, _request, response):
        response.success = True
        response.message = 'Managed nodes are active'
        return response

    def _publish_evidence(self):
        stamp = self.get_clock().now().to_msg()
        self.safety_publisher.publish(Bool(data=True))
        diagnostic = DiagnosticArray()
        diagnostic.header.stamp = stamp
        status = DiagnosticStatus()
        status.level = DiagnosticStatus.OK
        status.name = (
            '/keepout_safety_monitor: semantic keepout safety'
        )
        status.message = 'Robot is outside the semantic keepout zone'
        diagnostic.status = [status]
        self.diagnostic_publisher.publish(diagnostic)
        self.sensor_publisher.publish(String(data='fresh sample'))
        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = 'map'
        transform.child_frame_id = 'base_footprint'
        transform.transform.rotation.w = 1.0
        self.transform_broadcaster.sendTransform(transform)


def test_ros_adapter_collects_declared_read_only_evidence():
    """A healthy isolated ROS graph produces a healthy typed result."""
    rclpy.init(domain_id=229)
    provider = HealthyEvidenceProvider()
    executor = SingleThreadedExecutor()
    executor.add_node(provider)
    thread = Thread(target=executor.spin, daemon=True)
    thread.start()
    adapter = None
    try:
        adapter = RosHealthEvidenceNode(
            required_sensors=['/scan'],
        )
        snapshot = adapter.collect()
        result = evaluate_health_snapshot(
            snapshot,
            required_sensors=['/scan'],
            **adapter.configuration,
        )
        assert result['state'] == 'healthy'
        assert result['safe_to_proceed'] is True
        assert snapshot['nav2']['message'] == 'Managed nodes are active'
    finally:
        if adapter is not None:
            adapter.destroy_node()
        executor.shutdown()
        provider.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        thread.join(timeout=2.0)
