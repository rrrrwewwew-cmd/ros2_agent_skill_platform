"""Emergency fallback that cancels all active Nav2 pose goals."""

import json
import sys

from action_msgs.srv import CancelGoal
import rclpy


def main(argv=None):
    """Request cancellation through the fixed Nav2 action cancel service."""
    rclpy.init(args=argv)
    node = rclpy.create_node('cancel_approved_navigation_fallback')
    result = {'cancel_requested': False, 'return_code': None}
    try:
        client = node.create_client(
            CancelGoal, '/navigate_to_pose/_action/cancel_goal',
        )
        if not client.wait_for_service(timeout_sec=2.0):
            result['error'] = 'Nav2 cancel service is unavailable'
            print(json.dumps(result, sort_keys=True))
            return 3
        request = CancelGoal.Request()
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=2.0)
        if not future.done() or future.result() is None:
            result['error'] = 'Nav2 cancel request timed out'
            print(json.dumps(result, sort_keys=True))
            return 4
        response = future.result()
        result.update({
            'cancel_requested': True,
            'return_code': int(response.return_code),
            'goals_canceling': len(response.goals_canceling),
        })
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
