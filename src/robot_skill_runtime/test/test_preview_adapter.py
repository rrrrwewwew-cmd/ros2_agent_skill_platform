"""Tests for the fixed read-only route preview Runtime adapter."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from robot_skill_runtime.adapters import (
    SafeRoutePreviewAdapter,
    SkillAdapterError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class FixedRunner:
    """Return one configured route result and record the process call."""

    def __init__(self, result, returncode=0):
        self.result = result
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=json.dumps(self.result),
            stderr='',
        )


def _safe_result():
    return {
        'schema_version': 1,
        'skill': 'preview_safe_route',
        'skill_version': '0.1.0',
        'state': 'safe',
        'safe_to_execute': True,
        'motion_command_sent': False,
        'request': {
            'goal': {
                'frame_id': 'map',
                'x': 4.5,
                'y': 0.0,
                'yaw_deg': 0.0,
            },
            'keepout_profile': 'rbot_water_puddle_v2',
        },
        'planner': {
            'action': '/compute_path_to_pose',
            'available': True,
            'error_code': 0,
            'error_message': '',
            'planning_time_ms': 12.0,
            'path_frame': 'map',
            'observed_at_ns': 123,
        },
        'route': {
            'pose_count': 3,
            'length_m': 5.0,
            'start_m': {'x': 0.0, 'y': 0.0},
            'end_m': {'x': 4.5, 'y': 0.0},
            'goal_position_error_m': 0.0,
            'path_sha256': 'a' * 64,
        },
        'keepout': {
            'profile': 'rbot_water_puddle_v2',
            'target_id': 'water_puddle',
            'source_content_sha256': 'b' * 64,
            'source_updated_at': 'timestamp',
            'center_m': {'x': 1.67, 'y': 0.0},
            'radius_m': 0.6,
            'global_center_cost': 254,
            'active_in_global_costmap': True,
            'minimum_center_distance_m': 0.9,
            'minimum_clearance_m': 0.3,
            'intersects': False,
        },
        'reasons': [],
    }


def _inputs():
    return {
        'goal_x': 4.5,
        'goal_y': 0.0,
        'goal_yaw_deg': 0.0,
        'keepout_profile': 'rbot_water_puddle_v2',
    }


def test_adapter_uses_fixed_module_and_ros_arguments():
    """Inputs cannot select a process, ROS endpoint, or shell."""
    runner = FixedRunner(_safe_result())
    adapter = SafeRoutePreviewAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )
    result = adapter.invoke(_inputs(), 8.0)
    assert result['state'] == 'safe'
    call = runner.calls[0]
    assert call['command'][1:3] == [
        '-m', 'robot_navigation_skills.preview_ros',
    ]
    assert 'use_sim_time:=true' in call['command']
    assert call['options']['check'] is False
    assert 'shell' not in call['options']


def test_adapter_rejects_identity_mismatch():
    """A schema-shaped response for another goal cannot be accepted."""
    wrong = _safe_result()
    wrong['request']['goal']['x'] = 3.0
    adapter = SafeRoutePreviewAdapter(
        REPOSITORY_ROOT, runner=FixedRunner(wrong),
    )
    with pytest.raises(SkillAdapterError, match='identity mismatch'):
        adapter.invoke(_inputs(), 8.0)


def test_adapter_rejects_forged_safe_postconditions():
    """Safe requires an active filter and positive route clearance."""
    wrong = _safe_result()
    wrong['keepout']['active_in_global_costmap'] = False
    wrong['keepout']['global_center_cost'] = 0
    adapter = SafeRoutePreviewAdapter(
        REPOSITORY_ROOT, runner=FixedRunner(wrong),
    )
    with pytest.raises(SkillAdapterError, match='keepout evidence'):
        adapter.invoke(_inputs(), 8.0)


def test_adapter_timeout_is_bounded():
    """A stuck planner process becomes a bounded Runtime failure."""
    def timeout_runner(command, **options):
        raise subprocess.TimeoutExpired(command, options['timeout'])

    adapter = SafeRoutePreviewAdapter(
        REPOSITORY_ROOT, runner=timeout_runner,
    )
    with pytest.raises(SkillAdapterError, match='timed out'):
        adapter.invoke(_inputs(), 8.0)
