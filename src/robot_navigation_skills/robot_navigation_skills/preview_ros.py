"""ROS 2 adapter process for one read-only Nav2 path preview."""

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sys
import time

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose
from nav2_msgs.srv import GetCostmap
import rclpy
from rclpy.action import ActionClient
from robot_semantic_skills.query import query_semantic_target

from .preview import (
    normalize_request,
    preview_safe_route,
    RoutePreviewInputError,
    unavailable_result,
)


PROFILE_POLICIES = {
    'rbot_water_puddle_v2': {
        'store_file': (
            '~/.ros/semantic_nav_eval/'
            'rbot_water_puddle_landmarks_v2.json'
        ),
        'target_id': 'water_puddle',
        'radius_m': 0.6,
    },
}
EXIT_CODES = {'safe': 0, 'unsafe': 3, 'unavailable': 4, 'invalid': 5}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Preview a Nav2 route without sending a motion goal.'
    )
    parser.add_argument('--goal-x', type=float, required=True)
    parser.add_argument('--goal-y', type=float, required=True)
    parser.add_argument('--goal-yaw-deg', type=float, required=True)
    parser.add_argument('--keepout-profile', required=True)
    return parser.parse_known_args(argv)


def _invalid_result(request, reason):
    result = unavailable_result(request, reason)
    result['state'] = 'invalid'
    return result


def _spin_future(node, future, timeout_sec):
    rclpy.spin_until_future_complete(node, future, timeout_sec=timeout_sec)
    return future.done()


def _cost_at(costmap, world_x, world_y):
    metadata = costmap.metadata
    resolution = float(metadata.resolution)
    if resolution <= 0.0:
        raise RoutePreviewInputError('costmap resolution must be positive')
    origin = metadata.origin
    quaternion = origin.orientation
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
    dx = world_x - origin.position.x
    dy = world_y - origin.position.y
    local_x = math.cos(yaw) * dx + math.sin(yaw) * dy
    local_y = -math.sin(yaw) * dx + math.cos(yaw) * dy
    column = math.floor(local_x / resolution)
    row = math.floor(local_y / resolution)
    if not (
        0 <= column < int(metadata.size_x)
        and 0 <= row < int(metadata.size_y)
    ):
        raise RoutePreviewInputError('keepout center is outside global costmap')
    index = row * int(metadata.size_x) + column
    if index >= len(costmap.data):
        raise RoutePreviewInputError('costmap data length is inconsistent')
    return int(costmap.data[index])


def _query_global_cost(node, center, timeout_sec=2.0):
    client = node.create_client(GetCostmap, '/global_costmap/get_costmap')
    try:
        if not client.wait_for_service(timeout_sec=timeout_sec):
            raise RuntimeError('global costmap service is unavailable')
        future = client.call_async(GetCostmap.Request())
        if not _spin_future(node, future, timeout_sec):
            raise RuntimeError('global costmap request timed out')
        if future.exception() is not None:
            raise RuntimeError(f'global costmap failed: {future.exception()}')
        return _cost_at(future.result().map, center['x'], center['y'])
    finally:
        node.destroy_client(client)


def _request_path(node, request, timeout_sec=3.0):
    client = ActionClient(node, ComputePathToPose, '/compute_path_to_pose')
    try:
        if not client.wait_for_server(timeout_sec=timeout_sec):
            raise RuntimeError('Nav2 planner action is unavailable')
        goal_message = ComputePathToPose.Goal()
        goal_message.goal = PoseStamped()
        goal_message.goal.header.frame_id = 'map'
        goal_message.goal.header.stamp = node.get_clock().now().to_msg()
        goal = request['goal']
        goal_message.goal.pose.position.x = goal['x']
        goal_message.goal.pose.position.y = goal['y']
        yaw = math.radians(goal['yaw_deg'])
        goal_message.goal.pose.orientation.z = math.sin(yaw / 2.0)
        goal_message.goal.pose.orientation.w = math.cos(yaw / 2.0)
        goal_message.start.header.frame_id = 'map'
        goal_message.start.header.stamp = goal_message.goal.header.stamp
        goal_message.planner_id = ''
        goal_message.use_start = False
        send_future = client.send_goal_async(goal_message)
        if not _spin_future(node, send_future, timeout_sec):
            raise RuntimeError('Nav2 planner goal request timed out')
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError('Nav2 planner rejected the preview request')
        result_future = goal_handle.get_result_async()
        if not _spin_future(node, result_future, timeout_sec):
            goal_handle.cancel_goal_async()
            raise RuntimeError('Nav2 path computation timed out')
        wrapped = result_future.result()
        if wrapped is None:
            raise RuntimeError('Nav2 planner returned no action result')
        return wrapped.result
    finally:
        client.destroy()


def _print_result(result):
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_CODES[result['state']]


@contextmanager
def _middleware_logs_to_stderr():
    """Keep native DDS diagnostics outside the machine JSON channel."""
    sys.stdout.flush()
    saved_stdout = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved_stdout, sys.stdout.fileno())
        os.close(saved_stdout)


def _collect_live_result(request, semantic, ros_args):
    """Collect ROS evidence without printing to the machine JSON channel."""
    policy = PROFILE_POLICIES[request['keepout_profile']]
    rclpy.init(args=ros_args)
    node = rclpy.create_node('preview_safe_route')
    try:
        deadline = time.monotonic() + 1.5
        while node.get_clock().now().nanoseconds <= 0 and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        observed_at_ns = node.get_clock().now().nanoseconds
        if observed_at_ns <= 0:
            return unavailable_result(
                request, 'ROS clock is unavailable', observed_at_ns,
            )
        landmark = semantic['landmark']
        position = landmark['mean_position_m']
        zone = {
            'target_id': policy['target_id'],
            'center_m': {'x': position['x'], 'y': position['y']},
            'radius_m': policy['radius_m'],
            'source_content_sha256': semantic['source']['content_sha256'],
            'source_updated_at': semantic['source']['updated_at'],
        }
        try:
            center_cost = _query_global_cost(node, zone['center_m'])
            plan = _request_path(node, request)
        except (RuntimeError, RoutePreviewInputError) as exception:
            return unavailable_result(
                request, exception, node.get_clock().now().nanoseconds,
            )
        if plan.error_code != ComputePathToPose.Result.NONE:
            result = unavailable_result(
                request,
                f'Nav2 planning failed ({plan.error_code}): '
                f'{plan.error_msg}',
                node.get_clock().now().nanoseconds,
            )
            result['state'] = 'unsafe'
            result['planner'].update({
                'available': True,
                'error_code': int(plan.error_code),
                'error_message': str(plan.error_msg),
            })
            return result
        points = [
            (pose.pose.position.x, pose.pose.position.y)
            for pose in plan.path.poses
        ]
        planning_time_ms = (
            float(plan.planning_time.sec) * 1000.0
            + float(plan.planning_time.nanosec) / 1_000_000.0
        )
        try:
            result = preview_safe_route(
                request,
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
        except RoutePreviewInputError as exception:
            result = _invalid_result(request, exception)
        return result
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(argv=None):
    """Collect live Nav2 evidence and print exactly one JSON result."""
    options, ros_args = _parse_args(argv)
    try:
        request = normalize_request(
            options.goal_x,
            options.goal_y,
            options.goal_yaw_deg,
            options.keepout_profile,
        )
    except RoutePreviewInputError as exception:
        fallback = {
            'goal': {
                'frame_id': 'map',
                'x': options.goal_x,
                'y': options.goal_y,
                'yaw_deg': options.goal_yaw_deg,
            },
            'keepout_profile': str(options.keepout_profile),
        }
        return _print_result(_invalid_result(fallback, exception))
    policy = PROFILE_POLICIES[request['keepout_profile']]
    semantic = query_semantic_target(
        Path(policy['store_file']).expanduser(),
        request['keepout_profile'],
        policy['target_id'],
    )
    if semantic['state'] != 'found':
        result = unavailable_result(
            request,
            f'semantic keepout evidence is {semantic["state"]}: '
            f'{"; ".join(semantic["reasons"])}',
        )
        if semantic['state'] in {'invalid', 'not_found'}:
            result['state'] = 'invalid'
        return _print_result(result)
    with _middleware_logs_to_stderr():
        result = _collect_live_result(request, semantic, ros_args)
    return _print_result(result)


if __name__ == '__main__':
    sys.exit(main())
