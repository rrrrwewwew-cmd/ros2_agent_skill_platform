"""Tests for approved navigation deterministic policy."""

from copy import deepcopy

from robot_controlled_navigation_skills.navigation import (
    angle_error_deg,
    evaluate_preflight,
    finalize_navigation_result,
    normalize_navigation_request,
)


def _request():
    return normalize_navigation_request(
        4.5, 0.0, 0.0, 'rbot_water_puddle_v2', 'a' * 64, 'b' * 64,
    )


def _health():
    return {
        'state': 'healthy',
        'safe_to_proceed': True,
        'observation_timestamp_ns': 100,
    }


def _preview():
    return {
        'state': 'safe',
        'safe_to_execute': True,
        'motion_command_sent': False,
        'request': {
            'goal': _request()['goal'],
            'keepout_profile': 'rbot_water_puddle_v2',
        },
        'planner': {'observed_at_ns': 101},
        'route': {'path_sha256': 'a' * 64},
        'keepout': {
            'source_content_sha256': 'b' * 64,
            'center_m': {'x': 1.67, 'y': 0.0},
            'radius_m': 0.6,
            'active_in_global_costmap': True,
            'global_center_cost': 254,
            'minimum_clearance_m': 0.3,
        },
    }


def _navigation():
    return {
        'action': '/navigate_to_pose',
        'goal_accepted': True,
        'result_status': 4,
        'nav2_error_code': 0,
        'nav2_error_message': '',
        'started_at_ns': 110,
        'completed_at_ns': 200,
        'cancel_requested': False,
    }


def _postcondition():
    return {
        'final_pose': {
            'frame_id': 'map',
            'x': 4.5,
            'y': 0.0,
            'yaw_deg': 0.0,
            'observed_at_ns': 201,
        },
        'goal_position_error_m': 0.0,
        'goal_yaw_error_deg': 0.0,
        'minimum_center_distance_m': 0.9,
        'entered_keepout': False,
        'safety_remained_ok': True,
        'robot_stopped': True,
        'final_linear_speed_mps': 0.0,
        'final_angular_speed_rps': 0.0,
    }


def test_identical_fresh_evidence_allows_controlled_navigation():
    """Health, path identity, map identity, and clearance all gate motion."""
    preflight = evaluate_preflight(_request(), _health(), _preview())
    assert preflight['allowed'] is True
    result = finalize_navigation_result(
        _request(), preflight, _navigation(), _postcondition(),
    )
    assert result['state'] == 'succeeded'
    assert result['goal_reached'] is True
    assert result['motion_command_sent'] is True
    assert result['reasons'] == []


def test_changed_preview_hash_rejects_before_motion():
    """An approved target cannot silently switch to a different route."""
    changed = deepcopy(_preview())
    changed['route']['path_sha256'] = 'c' * 64
    preflight = evaluate_preflight(_request(), _health(), changed)
    result = finalize_navigation_result(
        _request(), preflight, {}, _postcondition(),
    )
    assert result['state'] == 'rejected'
    assert result['motion_command_sent'] is False
    assert 'path hash' in ' '.join(result['reasons'])


def test_unsafe_health_or_changed_map_fails_closed():
    """Current safety and semantic-map identity are independent gates."""
    health = deepcopy(_health())
    health.update({'state': 'unsafe', 'safe_to_proceed': False})
    preview = deepcopy(_preview())
    preview['keepout']['source_content_sha256'] = 'd' * 64
    preflight = evaluate_preflight(_request(), health, preview)
    assert preflight['allowed'] is False
    assert len(preflight['reasons']) == 2


def test_bad_physical_postcondition_overrides_nav2_success():
    """Nav2 success alone is insufficient when final motion is unsafe."""
    postcondition = deepcopy(_postcondition())
    postcondition['entered_keepout'] = True
    postcondition['robot_stopped'] = False
    result = finalize_navigation_result(
        _request(),
        evaluate_preflight(_request(), _health(), _preview()),
        _navigation(),
        postcondition,
    )
    assert result['state'] == 'failed'
    assert result['goal_reached'] is False
    assert len(result['reasons']) == 2


def test_angle_error_wraps_at_180_degrees():
    """Equivalent headings around the wrap boundary remain close."""
    assert angle_error_deg(-179.0, 179.0) == 2.0
