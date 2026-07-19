"""Deterministic policy for one human-approved Nav2 pose goal."""

import math
import re


SKILL_NAME = 'navigate_to_approved_pose'
SKILL_VERSION = '0.1.0'
APPROVED_PROFILE = 'rbot_water_puddle_v2'
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
LETHAL_COST = 253
GOAL_POSITION_TOLERANCE_M = 0.25
GOAL_YAW_TOLERANCE_DEG = 15.0


class NavigationInputError(ValueError):
    """Raised when controlled navigation evidence is malformed."""


def _finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NavigationInputError(f'{field} must be numeric')
    value = float(value)
    if not math.isfinite(value):
        raise NavigationInputError(f'{field} must be finite')
    return value


def _sha256(value, field):
    if not isinstance(value, str) or not HASH_PATTERN.fullmatch(value):
        raise NavigationInputError(f'{field} must be lowercase SHA-256')
    return value


def normalize_navigation_request(goal_x, goal_y, goal_yaw_deg,
                                 keepout_profile, approved_path_sha256,
                                 approved_semantic_map_sha256):
    """Return the bounded request whose exact bytes require approval."""
    x = _finite_number(goal_x, 'goal_x')
    y = _finite_number(goal_y, 'goal_y')
    yaw = _finite_number(goal_yaw_deg, 'goal_yaw_deg')
    if not -20.0 <= x <= 20.0 or not -20.0 <= y <= 20.0:
        raise NavigationInputError('goal must remain inside fixed map bounds')
    if not -180.0 <= yaw <= 180.0:
        raise NavigationInputError('goal_yaw_deg must be in [-180, 180]')
    if keepout_profile != APPROVED_PROFILE:
        raise NavigationInputError('keepout profile is not approved')
    return {
        'goal': {
            'frame_id': 'map',
            'x': x,
            'y': y,
            'yaw_deg': yaw,
        },
        'keepout_profile': keepout_profile,
        'approved_preview': {
            'path_sha256': _sha256(
                approved_path_sha256, 'approved_path_sha256',
            ),
            'semantic_map_sha256': _sha256(
                approved_semantic_map_sha256,
                'approved_semantic_map_sha256',
            ),
        },
    }


def evaluate_preflight(request, health_result, preview_result):
    """Require fresh health and an identical fresh safe path preview."""
    if not isinstance(health_result, dict):
        raise NavigationInputError('health result must be an object')
    if not isinstance(preview_result, dict):
        raise NavigationInputError('preview result must be an object')
    reasons = []
    health_state = health_result.get('state', 'unavailable')
    health_observed_at_ns = health_result.get('observation_timestamp_ns', 0)
    if (
        health_state != 'healthy' or
        health_result.get('safe_to_proceed') is not True
    ):
        reasons.append('robot health precondition is not healthy')
    expected_preview_request = {
        'goal': request['goal'],
        'keepout_profile': request['keepout_profile'],
    }
    if preview_result.get('request') != expected_preview_request:
        reasons.append('fresh preview goal identity does not match approval')
    preview_state = preview_result.get('state', 'unavailable')
    if (
        preview_state != 'safe' or
        preview_result.get('safe_to_execute') is not True or
        preview_result.get('motion_command_sent') is not False
    ):
        reasons.append('fresh route preview is not safe')
    route = preview_result.get('route')
    keepout = preview_result.get('keepout')
    route = route if isinstance(route, dict) else {}
    keepout = keepout if isinstance(keepout, dict) else {}
    current_path_hash = route.get('path_sha256')
    current_map_hash = keepout.get('source_content_sha256')
    path_matches = (
        current_path_hash == request['approved_preview']['path_sha256']
    )
    map_matches = (
        current_map_hash ==
        request['approved_preview']['semantic_map_sha256']
    )
    if not path_matches:
        reasons.append('fresh path hash differs from approved preview')
    if not map_matches:
        reasons.append('semantic map changed after route approval')
    if not (
        keepout.get('active_in_global_costmap') is True and
        isinstance(keepout.get('global_center_cost'), int) and
        keepout['global_center_cost'] >= LETHAL_COST
    ):
        reasons.append('semantic keepout is not active in global costmap')
    clearance = keepout.get('minimum_clearance_m')
    if (
        isinstance(clearance, bool) or
        not isinstance(clearance, (int, float)) or
        clearance <= 0.0
    ):
        reasons.append('fresh route has no positive semantic clearance')
    return {
        'allowed': not reasons,
        'health_state': health_state,
        'health_observed_at_ns': int(health_observed_at_ns or 0),
        'preview_state': preview_state,
        'preview_observed_at_ns': int(
            preview_result.get('planner', {}).get('observed_at_ns') or 0
        ),
        'current_path_sha256': current_path_hash,
        'approved_path_sha256': request[
            'approved_preview'
        ]['path_sha256'],
        'path_identity_matches': path_matches,
        'current_semantic_map_sha256': current_map_hash,
        'approved_semantic_map_sha256': request[
            'approved_preview'
        ]['semantic_map_sha256'],
        'semantic_identity_matches': map_matches,
        'keepout_center_m': keepout.get('center_m'),
        'keepout_radius_m': keepout.get('radius_m'),
        'global_center_cost': keepout.get('global_center_cost'),
        'minimum_clearance_m': clearance,
        'reasons': reasons,
    }


def angle_error_deg(actual, expected):
    """Return the smallest absolute angular difference in degrees."""
    actual = _finite_number(actual, 'actual yaw')
    expected = _finite_number(expected, 'expected yaw')
    return abs((actual - expected + 180.0) % 360.0 - 180.0)


def finalize_navigation_result(request, preflight, navigation, postcondition,
                               forced_state=None, extra_reasons=None):
    """Build a typed result and enforce physical postconditions."""
    reasons = list(preflight.get('reasons', []))
    reasons.extend(str(reason) for reason in (extra_reasons or []))
    if not preflight.get('allowed'):
        state = forced_state or 'rejected'
    else:
        state = forced_state or 'succeeded'
        if navigation.get('goal_accepted') is not True:
            reasons.append('Nav2 did not accept the approved goal')
        if navigation.get('result_status') != 4:
            reasons.append('Nav2 action did not report STATUS_SUCCEEDED')
        if navigation.get('nav2_error_code') != 0:
            reasons.append('Nav2 reported a navigation error')
        position_error = postcondition.get('goal_position_error_m')
        if (
            isinstance(position_error, bool) or
            not isinstance(position_error, (int, float)) or
            position_error > GOAL_POSITION_TOLERANCE_M
        ):
            reasons.append('final position is outside goal tolerance')
        yaw_error = postcondition.get('goal_yaw_error_deg')
        if (
            isinstance(yaw_error, bool) or
            not isinstance(yaw_error, (int, float)) or
            yaw_error > GOAL_YAW_TOLERANCE_DEG
        ):
            reasons.append('final yaw is outside goal tolerance')
        if postcondition.get('entered_keepout') is not False:
            reasons.append('observed trajectory entered semantic keepout')
        if postcondition.get('safety_remained_ok') is not True:
            reasons.append('semantic safety was not continuously OK')
        if postcondition.get('robot_stopped') is not True:
            reasons.append('robot did not reach a verified stopped state')
        if reasons and state == 'succeeded':
            state = 'failed'
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        'schema_version': 1,
        'skill': SKILL_NAME,
        'skill_version': SKILL_VERSION,
        'state': state,
        'goal_reached': state == 'succeeded',
        'motion_command_sent': bool(navigation.get('goal_accepted')),
        'request': request,
        'preflight': preflight,
        'navigation': navigation,
        'postcondition': postcondition,
        'reasons': unique_reasons,
    }


def navigate_to_approved_pose(request, health_result, preview_result,
                              navigation, postcondition,
                              forced_state=None, extra_reasons=None):
    """Apply the pure preflight and postcondition policy to one run."""
    preflight = evaluate_preflight(request, health_result, preview_result)
    return finalize_navigation_result(
        request,
        preflight,
        navigation,
        postcondition,
        forced_state=forced_state,
        extra_reasons=extra_reasons,
    )
