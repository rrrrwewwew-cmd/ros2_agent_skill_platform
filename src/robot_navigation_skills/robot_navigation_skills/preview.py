"""Evaluate one Nav2 path preview against a semantic Keepout zone."""

import hashlib
import json
import math


SKILL_NAME = 'preview_safe_route'
SKILL_VERSION = '0.1.0'
KEEP_OUT_PROFILES = {'rbot_water_puddle_v2'}
GOAL_LIMIT_M = 20.0
GOAL_TOLERANCE_M = 0.25
LETHAL_COST = 253


class RoutePreviewInputError(ValueError):
    """Raised when an input expands the bounded preview contract."""


def _finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoutePreviewInputError(f'{field} must be numeric')
    number = float(value)
    if not math.isfinite(number):
        raise RoutePreviewInputError(f'{field} must be finite')
    return number


def normalize_request(goal_x, goal_y, goal_yaw_deg, keepout_profile):
    """Validate and normalize one bounded map-frame route request."""
    x = _finite_number(goal_x, 'goal_x')
    y = _finite_number(goal_y, 'goal_y')
    yaw = _finite_number(goal_yaw_deg, 'goal_yaw_deg')
    profile = str(keepout_profile).strip()
    if abs(x) > GOAL_LIMIT_M or abs(y) > GOAL_LIMIT_M:
        raise RoutePreviewInputError('goal coordinates exceed map bounds')
    if yaw < -180.0 or yaw > 180.0:
        raise RoutePreviewInputError('goal_yaw_deg must be in [-180, 180]')
    if profile not in KEEP_OUT_PROFILES:
        raise RoutePreviewInputError('keepout_profile is not approved')
    return {
        'goal': {
            'frame_id': 'map',
            'x': x,
            'y': y,
            'yaw_deg': yaw,
        },
        'keepout_profile': profile,
    }


def _normalize_point(point, index):
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise RoutePreviewInputError(f'path point {index} must contain x/y')
    return (
        _finite_number(point[0], f'path[{index}].x'),
        _finite_number(point[1], f'path[{index}].y'),
    )


def _point_to_segment_distance(px, py, start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - start[0], py - start[1])
    ratio = (
        (px - start[0]) * dx + (py - start[1]) * dy
    ) / length_squared
    ratio = min(1.0, max(0.0, ratio))
    return math.hypot(
        px - (start[0] + ratio * dx),
        py - (start[1] + ratio * dy),
    )


def measure_path(points, center_x, center_y, radius):
    """Return length and exact segment clearance for a planar path."""
    normalized = [
        _normalize_point(point, index)
        for index, point in enumerate(points)
    ]
    if not normalized:
        raise RoutePreviewInputError('planned path is empty')
    cx = _finite_number(center_x, 'keepout center x')
    cy = _finite_number(center_y, 'keepout center y')
    zone_radius = _finite_number(radius, 'keepout radius')
    if zone_radius <= 0.0:
        raise RoutePreviewInputError('keepout radius must be positive')
    length = sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in zip(normalized, normalized[1:])
    )
    if len(normalized) == 1:
        minimum = math.hypot(
            normalized[0][0] - cx, normalized[0][1] - cy,
        )
    else:
        minimum = min(
            _point_to_segment_distance(cx, cy, start, end)
            for start, end in zip(normalized, normalized[1:])
        )
    canonical = json.dumps(
        [[point[0], point[1]] for point in normalized],
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return {
        'points': normalized,
        'pose_count': len(normalized),
        'length_m': length,
        'minimum_center_distance_m': minimum,
        'minimum_clearance_m': minimum - zone_radius,
        'intersects': minimum <= zone_radius,
        'path_sha256': hashlib.sha256(canonical).hexdigest(),
    }


def _planner_evidence(available, error_code, error_message,
                      planning_time_ms, path_frame, observed_at_ns):
    return {
        'action': '/compute_path_to_pose',
        'available': bool(available),
        'error_code': error_code,
        'error_message': str(error_message or ''),
        'planning_time_ms': planning_time_ms,
        'path_frame': path_frame,
        'observed_at_ns': int(observed_at_ns),
    }


def unavailable_result(request, reason, observed_at_ns=0):
    """Build a fail-closed result when live planning evidence is absent."""
    return {
        'schema_version': 1,
        'skill': SKILL_NAME,
        'skill_version': SKILL_VERSION,
        'state': 'unavailable',
        'safe_to_execute': False,
        'motion_command_sent': False,
        'request': request,
        'planner': _planner_evidence(
            False, None, '', None, None, observed_at_ns,
        ),
        'route': None,
        'keepout': {
            'profile': request['keepout_profile'],
            'target_id': 'water_puddle',
            'source_content_sha256': None,
            'source_updated_at': '',
            'center_m': None,
            'radius_m': None,
            'global_center_cost': None,
            'active_in_global_costmap': None,
            'minimum_center_distance_m': None,
            'minimum_clearance_m': None,
            'intersects': None,
        },
        'reasons': [str(reason)],
    }


def preview_safe_route(request, points, zone, global_center_cost,
                       planner_evidence):
    """Return a typed, fail-closed safety decision for one path preview."""
    normalized_request = normalize_request(
        request['goal']['x'],
        request['goal']['y'],
        request['goal']['yaw_deg'],
        request['keepout_profile'],
    )
    center = zone.get('center_m')
    if not isinstance(center, dict):
        raise RoutePreviewInputError('keepout center is missing')
    metrics = measure_path(
        points, center.get('x'), center.get('y'), zone.get('radius_m'),
    )
    cost = global_center_cost
    if isinstance(cost, bool) or not isinstance(cost, int) or not 0 <= cost <= 255:
        raise RoutePreviewInputError('global center cost must be uint8')
    path_frame = planner_evidence.get('path_frame')
    planner_code = planner_evidence.get('error_code')
    planning_time = planner_evidence.get('planning_time_ms')
    observed_at_ns = planner_evidence.get('observed_at_ns')
    if path_frame != 'map':
        raise RoutePreviewInputError('planned path must use map frame')
    if planner_code != 0:
        raise RoutePreviewInputError('successful path must have error_code 0')
    planning_time = _finite_number(planning_time, 'planning_time_ms')
    if planning_time < 0.0:
        raise RoutePreviewInputError('planning_time_ms must be nonnegative')
    if isinstance(observed_at_ns, bool) or not isinstance(observed_at_ns, int):
        raise RoutePreviewInputError('observed_at_ns must be an integer')
    if observed_at_ns <= 0:
        raise RoutePreviewInputError('observed_at_ns must be positive')
    endpoint = metrics['points'][-1]
    goal = normalized_request['goal']
    endpoint_error = math.hypot(endpoint[0] - goal['x'], endpoint[1] - goal['y'])
    keepout_active = cost >= LETHAL_COST
    reasons = []
    if not keepout_active:
        reasons.append('semantic keepout is not lethal in global costmap')
    if metrics['intersects']:
        reasons.append('planned path intersects semantic keepout zone')
    if endpoint_error > GOAL_TOLERANCE_M:
        reasons.append('planned path endpoint does not match requested goal')
    source_hash = zone.get('source_content_sha256')
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise RoutePreviewInputError('keepout source hash is invalid')
    state = 'safe' if not reasons else 'unsafe'
    return {
        'schema_version': 1,
        'skill': SKILL_NAME,
        'skill_version': SKILL_VERSION,
        'state': state,
        'safe_to_execute': state == 'safe',
        'motion_command_sent': False,
        'request': normalized_request,
        'planner': _planner_evidence(
            True,
            planner_code,
            planner_evidence.get('error_message', ''),
            planning_time,
            path_frame,
            observed_at_ns,
        ),
        'route': {
            'pose_count': metrics['pose_count'],
            'length_m': metrics['length_m'],
            'start_m': {
                'x': metrics['points'][0][0],
                'y': metrics['points'][0][1],
            },
            'end_m': {'x': endpoint[0], 'y': endpoint[1]},
            'goal_position_error_m': endpoint_error,
            'path_sha256': metrics['path_sha256'],
        },
        'keepout': {
            'profile': normalized_request['keepout_profile'],
            'target_id': zone.get('target_id'),
            'source_content_sha256': source_hash,
            'source_updated_at': str(zone.get('source_updated_at', '')),
            'center_m': {
                'x': float(center['x']),
                'y': float(center['y']),
            },
            'radius_m': float(zone['radius_m']),
            'global_center_cost': cost,
            'active_in_global_costmap': keepout_active,
            'minimum_center_distance_m': metrics[
                'minimum_center_distance_m'
            ],
            'minimum_clearance_m': metrics['minimum_clearance_m'],
            'intersects': metrics['intersects'],
        },
        'reasons': reasons,
    }
