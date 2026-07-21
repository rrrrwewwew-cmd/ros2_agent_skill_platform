"""Fixed ROS 2 adapter for one exact human-approved Nav2 goal."""

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sys
import time

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from robot_navigation_skills.preview import measure_path, preview_safe_route
from robot_navigation_skills.preview_ros import (
    _query_global_cost,
    _request_path,
    PROFILE_POLICIES,
)
from robot_semantic_skills.query import query_semantic_target
from safe_agent_core.health import evaluate_health_snapshot
from safe_agent_core.health_ros import RosHealthEvidenceNode
from std_msgs.msg import Bool
from tf2_ros import Buffer, TransformException, TransformListener

from .navigation import (
    angle_error_deg,
    evaluate_preflight,
    finalize_navigation_result,
    NavigationInputError,
    normalize_navigation_request,
)


EXIT_CODES = {
    'succeeded': 0,
    'rejected': 3,
    'failed': 4,
    'canceled': 5,
    'safety_stopped': 6,
    'unavailable': 7,
    'invalid': 8,
}
NAVIGATION_TIMEOUT_SEC = 95.0


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Execute one exact approved Nav2 pose goal.'
    )
    parser.add_argument('--goal-x', type=float, required=True)
    parser.add_argument('--goal-y', type=float, required=True)
    parser.add_argument('--goal-yaw-deg', type=float, required=True)
    parser.add_argument('--keepout-profile', required=True)
    parser.add_argument('--approved-path-sha256', required=True)
    parser.add_argument('--approved-semantic-map-sha256', required=True)
    return parser.parse_known_args(argv)


def _yaw_deg(quaternion):
    yaw = math.atan2(
        2.0 * (
            quaternion.w * quaternion.z
            + quaternion.x * quaternion.y
        ),
        1.0 - 2.0 * (
            quaternion.y * quaternion.y
            + quaternion.z * quaternion.z
        ),
    )
    return math.degrees(yaw)


def _empty_navigation(now_ns=0):
    return {
        'action': '/navigate_to_pose',
        'goal_accepted': False,
        'result_status': None,
        'nav2_error_code': None,
        'nav2_error_message': '',
        'started_at_ns': int(now_ns),
        'completed_at_ns': int(now_ns),
        'cancel_requested': False,
    }


def _empty_postcondition():
    return {
        'final_pose': None,
        'goal_position_error_m': None,
        'goal_yaw_error_deg': None,
        'minimum_center_distance_m': None,
        'entered_keepout': None,
        'safety_remained_ok': False,
        'robot_stopped': False,
        'final_linear_speed_mps': None,
        'final_angular_speed_rps': None,
    }


@contextmanager
def _middleware_logs_to_stderr():
    """Keep native ROS diagnostics outside the one-JSON stdout channel."""
    sys.stdout.flush()
    saved_stdout = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved_stdout, sys.stdout.fileno())
        os.close(saved_stdout)


class ControlledNavigationNode(Node):
    """Send one Nav2 goal while monitoring only declared safety evidence."""

    def __init__(self):
        super().__init__('navigate_to_approved_pose')
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.safety_received = False
        self.safety_ok = False
        self.safety_remained_ok = True
        self.odom_received = False
        self.odom_received_at_ns = 0
        self.linear_speed_mps = None
        self.angular_speed_rps = None
        self.trajectory = []
        self._safety_subscription = self.create_subscription(
            Bool,
            '/semantic_keepout/safety_ok',
            self._on_safety,
            qos,
        )
        self._odom_subscription = self.create_subscription(
            Odometry,
            '/odom',
            self._on_odom,
            qos,
        )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(
            self._tf_buffer, self, spin_thread=False,
        )
        self._navigation_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose',
        )

    def _on_safety(self, message):
        self.safety_received = True
        self.safety_ok = bool(message.data)
        if not self.safety_ok:
            self.safety_remained_ok = False

    def _on_odom(self, message):
        self.odom_received = True
        self.odom_received_at_ns = self.get_clock().now().nanoseconds
        linear = message.twist.twist.linear
        angular = message.twist.twist.angular
        self.linear_speed_mps = math.sqrt(
            linear.x * linear.x + linear.y * linear.y + linear.z * linear.z
        )
        self.angular_speed_rps = math.sqrt(
            angular.x * angular.x
            + angular.y * angular.y
            + angular.z * angular.z
        )

    def _sample_pose(self):
        try:
            transform = self._tf_buffer.lookup_transform(
                'map', 'base_footprint', Time(),
            )
        except TransformException:
            return None
        pose = {
            'frame_id': 'map',
            'x': float(transform.transform.translation.x),
            'y': float(transform.transform.translation.y),
            'yaw_deg': _yaw_deg(transform.transform.rotation),
            'observed_at_ns': self.get_clock().now().nanoseconds,
        }
        point = (pose['x'], pose['y'])
        if not self.trajectory or point != self.trajectory[-1]:
            self.trajectory.append(point)
        return pose

    def wait_for_monitoring(self, timeout_sec=1.5):
        """Require fresh safety, odometry, and map pose before motion."""
        deadline = time.monotonic() + timeout_sec
        pose = None
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            pose = self._sample_pose() or pose
            if self.safety_received and self.odom_received and pose is not None:
                break
        return self.safety_received and self.odom_received and pose is not None

    def execute_goal(self, request, zone):
        """Execute, cancel on safety/timeout, and collect postconditions."""
        now_ns = self.get_clock().now().nanoseconds
        navigation = _empty_navigation(now_ns)
        if not self._navigation_client.wait_for_server(timeout_sec=3.0):
            return (
                navigation,
                _empty_postcondition(),
                'unavailable',
                ['Nav2 NavigateToPose action is unavailable'],
            )
        goal_message = NavigateToPose.Goal()
        goal_message.pose = PoseStamped()
        goal_message.pose.header.frame_id = 'map'
        goal_message.pose.header.stamp = self.get_clock().now().to_msg()
        goal = request['goal']
        goal_message.pose.pose.position.x = goal['x']
        goal_message.pose.pose.position.y = goal['y']
        yaw = math.radians(goal['yaw_deg'])
        goal_message.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_message.pose.pose.orientation.w = math.cos(yaw / 2.0)
        goal_message.behavior_tree = ''
        navigation['started_at_ns'] = self.get_clock().now().nanoseconds
        send_future = self._navigation_client.send_goal_async(goal_message)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=3.0)
        if not send_future.done() or send_future.result() is None:
            navigation['completed_at_ns'] = self.get_clock().now().nanoseconds
            return (
                navigation,
                _empty_postcondition(),
                'failed',
                ['Nav2 goal request timed out'],
            )
        goal_handle = send_future.result()
        if not goal_handle.accepted:
            navigation['completed_at_ns'] = self.get_clock().now().nanoseconds
            return (
                navigation,
                _empty_postcondition(),
                'failed',
                ['Nav2 rejected the approved goal'],
            )
        navigation['goal_accepted'] = True
        result_future = goal_handle.get_result_async()
        deadline = time.monotonic() + NAVIGATION_TIMEOUT_SEC
        forced_state = None
        reasons = []
        while (
            rclpy.ok() and not result_future.done()
            and time.monotonic() < deadline
        ):
            rclpy.spin_once(self, timeout_sec=0.05)
            self._sample_pose()
            if self.safety_received and not self.safety_ok:
                navigation['cancel_requested'] = True
                goal_handle.cancel_goal_async()
                forced_state = 'safety_stopped'
                reasons.append('semantic safety monitor asserted unsafe')
                break
        if not result_future.done() and forced_state is None:
            navigation['cancel_requested'] = True
            goal_handle.cancel_goal_async()
            forced_state = 'canceled'
            reasons.append('navigation exceeded bounded timeout')
        if navigation['cancel_requested']:
            cancel_deadline = time.monotonic() + 2.0
            while (
                rclpy.ok() and not result_future.done()
                and time.monotonic() < cancel_deadline
            ):
                rclpy.spin_once(self, timeout_sec=0.05)
                self._sample_pose()
        if result_future.done() and result_future.result() is not None:
            wrapped = result_future.result()
            navigation['result_status'] = int(wrapped.status)
            navigation['nav2_error_code'] = int(wrapped.result.error_code)
            navigation['nav2_error_message'] = str(wrapped.result.error_msg)
        navigation['completed_at_ns'] = self.get_clock().now().nanoseconds
        stop_deadline = time.monotonic() + 2.0
        while rclpy.ok() and time.monotonic() < stop_deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            self._sample_pose()
            if (
                self.odom_received
                and self.linear_speed_mps is not None
                and self.angular_speed_rps is not None
                and self.linear_speed_mps <= 0.03
                and self.angular_speed_rps <= 0.05
            ):
                break
        final_pose = self._sample_pose()
        postcondition = _empty_postcondition()
        postcondition['final_pose'] = final_pose
        if final_pose is not None:
            postcondition['goal_position_error_m'] = math.hypot(
                final_pose['x'] - goal['x'], final_pose['y'] - goal['y'],
            )
            postcondition['goal_yaw_error_deg'] = angle_error_deg(
                final_pose['yaw_deg'], goal['yaw_deg'],
            )
        center = zone['center_m']
        if self.trajectory:
            metrics = measure_path(
                self.trajectory, center['x'], center['y'], zone['radius_m'],
            )
            postcondition['minimum_center_distance_m'] = metrics[
                'minimum_center_distance_m'
            ]
            postcondition['entered_keepout'] = metrics['intersects']
        postcondition['safety_remained_ok'] = (
            self.safety_received and self.safety_remained_ok
            and self.safety_ok
        )
        postcondition['final_linear_speed_mps'] = self.linear_speed_mps
        postcondition['final_angular_speed_rps'] = self.angular_speed_rps
        postcondition['robot_stopped'] = (
            self.odom_received
            and self.linear_speed_mps is not None
            and self.angular_speed_rps is not None
            and self.linear_speed_mps <= 0.03
            and self.angular_speed_rps <= 0.05
        )
        if forced_state is None and (
            navigation['result_status'] != GoalStatus.STATUS_SUCCEEDED
            or navigation['nav2_error_code'] != NavigateToPose.Result.NONE
        ):
            forced_state = 'failed'
            reasons.append('Nav2 navigation action failed')
        return navigation, postcondition, forced_state, reasons


def _fresh_preview(node, request, semantic):
    policy = PROFILE_POLICIES[request['keepout_profile']]
    position = semantic['landmark']['mean_position_m']
    zone = {
        'target_id': policy['target_id'],
        'center_m': {'x': position['x'], 'y': position['y']},
        'radius_m': policy['radius_m'],
        'source_content_sha256': semantic['source']['content_sha256'],
        'source_updated_at': semantic['source']['updated_at'],
    }
    preview_request = {
        'goal': request['goal'],
        'keepout_profile': request['keepout_profile'],
    }
    center_cost = _query_global_cost(node, zone['center_m'])
    plan = _request_path(node, preview_request)
    if plan.error_code != 0:
        raise RuntimeError(
            f'Nav2 planning failed ({plan.error_code}): {plan.error_msg}'
        )
    points = [
        (pose.pose.position.x, pose.pose.position.y)
        for pose in plan.path.poses
    ]
    planning_time_ms = (
        float(plan.planning_time.sec) * 1000.0
        + float(plan.planning_time.nanosec) / 1_000_000.0
    )
    preview = preview_safe_route(
        preview_request,
        points,
        zone,
        center_cost,
        {
            'error_code': int(plan.error_code),
            'error_message': str(plan.error_msg),
            'planning_time_ms': planning_time_ms,
            'path_frame': plan.path.header.frame_id,
            'observed_at_ns': node.get_clock().now().nanoseconds,
        },
    )
    return preview, zone


def _collect_result(request, ros_args):
    rclpy.init(args=ros_args)
    health_node = None
    navigation_node = None
    try:
        health_node = RosHealthEvidenceNode(required_sensors=['/scan'])
        snapshot = health_node.collect()
        health = evaluate_health_snapshot(
            snapshot,
            required_sensors=health_node.required_sensors,
            **health_node.configuration,
        )
        health_node.destroy_node()
        health_node = None
        policy = PROFILE_POLICIES[request['keepout_profile']]
        semantic = query_semantic_target(
            Path(policy['store_file']).expanduser(),
            request['keepout_profile'],
            policy['target_id'],
        )
        navigation_node = ControlledNavigationNode()
        if semantic['state'] != 'found':
            raise RuntimeError(
                f'semantic keepout evidence is {semantic["state"]}'
            )
        preview, zone = _fresh_preview(navigation_node, request, semantic)
        preflight = evaluate_preflight(request, health, preview)
        monitoring_ready = navigation_node.wait_for_monitoring()
        if not monitoring_ready:
            preflight['allowed'] = False
            preflight['reasons'].append(
                'live safety, odometry, or map pose monitoring is unavailable'
            )
        elif (
            not navigation_node.safety_ok or
            not navigation_node.safety_remained_ok
        ):
            preflight['allowed'] = False
            preflight['reasons'].append(
                'semantic safety monitor is unsafe immediately before motion'
            )
        if not preflight['allowed']:
            return finalize_navigation_result(
                request,
                preflight,
                _empty_navigation(navigation_node.get_clock().now().nanoseconds),
                _empty_postcondition(),
                forced_state='rejected',
            )
        navigation, postcondition, forced_state, reasons = (
            navigation_node.execute_goal(request, zone)
        )
        return finalize_navigation_result(
            request,
            preflight,
            navigation,
            postcondition,
            forced_state=forced_state,
            extra_reasons=reasons,
        )
    except (NavigationInputError, RuntimeError) as exception:
        preflight = {
            'allowed': False,
            'health_state': 'unavailable',
            'health_observed_at_ns': 0,
            'preview_state': 'unavailable',
            'preview_observed_at_ns': 0,
            'current_path_sha256': None,
            'approved_path_sha256': request['approved_preview']['path_sha256'],
            'path_identity_matches': False,
            'current_semantic_map_sha256': None,
            'approved_semantic_map_sha256': request[
                'approved_preview'
            ]['semantic_map_sha256'],
            'semantic_identity_matches': False,
            'keepout_center_m': None,
            'keepout_radius_m': None,
            'global_center_cost': None,
            'minimum_clearance_m': None,
            'reasons': [str(exception)],
        }
        return finalize_navigation_result(
            request,
            preflight,
            _empty_navigation(),
            _empty_postcondition(),
            forced_state='unavailable',
        )
    finally:
        if health_node is not None:
            health_node.destroy_node()
        if navigation_node is not None:
            navigation_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(argv=None):
    """Run the bounded adapter and print exactly one machine JSON result."""
    options, ros_args = _parse_args(argv)
    try:
        request = normalize_navigation_request(
            options.goal_x,
            options.goal_y,
            options.goal_yaw_deg,
            options.keepout_profile,
            options.approved_path_sha256,
            options.approved_semantic_map_sha256,
        )
    except NavigationInputError as exception:
        print(json.dumps({'state': 'invalid', 'error': str(exception)}))
        return EXIT_CODES['invalid']
    with _middleware_logs_to_stderr():
        result = _collect_result(request, ros_args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_CODES[result['state']]


if __name__ == '__main__':
    raise SystemExit(main())
