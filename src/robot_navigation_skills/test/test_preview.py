"""Tests for deterministic route preview policy."""

import math

import pytest
from robot_navigation_skills.preview import (
    measure_path,
    normalize_request,
    preview_safe_route,
    RoutePreviewInputError,
)


def _request():
    return normalize_request(4.5, 0.0, 0.0, 'rbot_water_puddle_v2')


def _zone():
    return {
        'target_id': 'water_puddle',
        'center_m': {'x': 1.67, 'y': 0.0},
        'radius_m': 0.6,
        'source_content_sha256': 'a' * 64,
        'source_updated_at': 'timestamp',
    }


def _planner():
    return {
        'error_code': 0,
        'error_message': '',
        'planning_time_ms': 12.5,
        'path_frame': 'map',
        'observed_at_ns': 123,
    }


def test_detour_is_safe_when_keepout_filter_is_active():
    """A map path outside a lethal semantic zone is executable evidence."""
    result = preview_safe_route(
        _request(),
        [(0.0, 0.0), (1.67, 1.0), (4.5, 0.0)],
        _zone(),
        254,
        _planner(),
    )
    assert result['state'] == 'safe'
    assert result['safe_to_execute'] is True
    assert result['motion_command_sent'] is False
    assert result['keepout']['intersects'] is False
    assert result['route']['pose_count'] == 3


def test_direct_path_through_zone_is_unsafe():
    """A planner response cannot override explicit geometry policy."""
    result = preview_safe_route(
        _request(),
        [(0.0, 0.0), (4.5, 0.0)],
        _zone(),
        254,
        _planner(),
    )
    assert result['state'] == 'unsafe'
    assert result['safe_to_execute'] is False
    assert result['keepout']['intersects'] is True
    assert 'intersects' in result['reasons'][0]


def test_nonlethal_costmap_zone_fails_closed():
    """Geometric avoidance alone is insufficient if the filter is absent."""
    result = preview_safe_route(
        _request(),
        [(0.0, 0.0), (1.67, 1.0), (4.5, 0.0)],
        _zone(),
        0,
        _planner(),
    )
    assert result['state'] == 'unsafe'
    assert result['keepout']['active_in_global_costmap'] is False


def test_endpoint_must_match_requested_goal():
    """A valid-looking path for another goal is rejected."""
    result = preview_safe_route(
        _request(),
        [(0.0, 0.0), (1.67, 1.0), (4.0, 0.0)],
        _zone(),
        254,
        _planner(),
    )
    assert result['state'] == 'unsafe'
    assert result['route']['goal_position_error_m'] == pytest.approx(0.5)


def test_segment_clearance_uses_edges_not_only_pose_samples():
    """Sparse path points still detect an intersection between samples."""
    metrics = measure_path([(0.0, 0.0), (2.0, 0.0)], 1.0, 0.1, 0.2)
    assert metrics['intersects'] is True
    assert metrics['minimum_center_distance_m'] == pytest.approx(0.1)


@pytest.mark.parametrize(
    'x,y,yaw,profile',
    [
        (math.inf, 0.0, 0.0, 'rbot_water_puddle_v2'),
        (21.0, 0.0, 0.0, 'rbot_water_puddle_v2'),
        (0.0, 0.0, 181.0, 'rbot_water_puddle_v2'),
        (0.0, 0.0, 0.0, '../../arbitrary'),
    ],
)
def test_request_surface_is_bounded(x, y, yaw, profile):
    """Nonfinite, out-of-map, and unapproved values never reach ROS."""
    with pytest.raises(RoutePreviewInputError):
        normalize_request(x, y, yaw, profile)
