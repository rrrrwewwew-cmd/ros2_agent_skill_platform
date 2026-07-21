"""Validate approved navigation outcomes against the public Schema."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from robot_controlled_navigation_skills.navigation import (
    evaluate_preflight,
    finalize_navigation_result,
    normalize_navigation_request,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_rejected_result_matches_schema():
    """A preflight refusal is still a complete machine-readable result."""
    request = normalize_navigation_request(
        4.5, 0.0, 0.0, 'rbot_water_puddle_v2', 'a' * 64, 'b' * 64,
    )
    health = {
        'state': 'unsafe',
        'safe_to_proceed': False,
        'observation_timestamp_ns': 1,
    }
    preview = {
        'state': 'unavailable',
        'safe_to_execute': False,
        'motion_command_sent': False,
        'request': {
            'goal': request['goal'],
            'keepout_profile': request['keepout_profile'],
        },
        'planner': {'observed_at_ns': 0},
        'route': None,
        'keepout': {},
    }
    preflight = evaluate_preflight(request, health, preview)
    navigation = {
        'action': '/navigate_to_pose',
        'goal_accepted': False,
        'result_status': None,
        'nav2_error_code': None,
        'nav2_error_message': '',
        'started_at_ns': 0,
        'completed_at_ns': 0,
        'cancel_requested': False,
    }
    postcondition = {
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
    result = finalize_navigation_result(
        request, preflight, navigation, postcondition,
    )
    schema = json.loads((
        REPOSITORY_ROOT /
        'skills/navigate_to_approved_pose/schemas/'
        'navigation_result.schema.json'
    ).read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(result)
