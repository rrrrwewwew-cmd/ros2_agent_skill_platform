"""Tests for the fixed controlled navigation Runtime adapter."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from robot_skill_runtime.adapters import (
    ApprovedNavigationAdapter,
    SkillAdapterError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class FixedRunner:
    """Return one configured process result and record all arguments."""

    def __init__(self, result=None, returncode=0):
        self.result = result or {}
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=json.dumps(self.result),
            stderr='',
        )


class SequenceRunner:
    """Return configured process results and retain retry boundaries."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return self.results.pop(0)


def _inputs():
    return {
        'goal_x': 4.5,
        'goal_y': 0.0,
        'goal_yaw_deg': 0.0,
        'keepout_profile': 'rbot_water_puddle_v2',
        'approved_path_sha256': 'a' * 64,
        'approved_semantic_map_sha256': 'b' * 64,
    }


def _success_result():
    return {
        'schema_version': 1,
        'skill': 'navigate_to_approved_pose',
        'skill_version': '0.1.0',
        'state': 'succeeded',
        'goal_reached': True,
        'motion_command_sent': True,
        'request': {
            'goal': {
                'frame_id': 'map',
                'x': 4.5,
                'y': 0.0,
                'yaw_deg': 0.0,
            },
            'keepout_profile': 'rbot_water_puddle_v2',
            'approved_preview': {
                'path_sha256': 'a' * 64,
                'semantic_map_sha256': 'b' * 64,
            },
        },
        'preflight': {
            'allowed': True,
            'health_state': 'healthy',
            'health_observed_at_ns': 100,
            'preview_state': 'safe',
            'preview_observed_at_ns': 101,
            'current_path_sha256': 'a' * 64,
            'approved_path_sha256': 'a' * 64,
            'path_identity_matches': True,
            'current_semantic_map_sha256': 'b' * 64,
            'approved_semantic_map_sha256': 'b' * 64,
            'semantic_identity_matches': True,
            'keepout_center_m': {'x': 1.67, 'y': 0.0},
            'keepout_radius_m': 0.6,
            'global_center_cost': 254,
            'minimum_clearance_m': 0.3,
            'reasons': [],
        },
        'navigation': {
            'action': '/navigate_to_pose',
            'goal_accepted': True,
            'result_status': 4,
            'nav2_error_code': 0,
            'nav2_error_message': '',
            'started_at_ns': 110,
            'completed_at_ns': 200,
            'cancel_requested': False,
        },
        'postcondition': {
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
        },
        'reasons': [],
    }


def test_adapter_uses_only_fixed_module_and_arguments():
    """Agent inputs cannot select a process, endpoint, or shell."""
    runner = FixedRunner(_success_result())
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )
    result = adapter.invoke(_inputs(), 120.0)
    assert result['state'] == 'succeeded'
    call = runner.calls[0]
    assert call['command'][1:3] == [
        '-m', 'robot_controlled_navigation_skills.navigation_ros',
    ]
    assert 'use_sim_time:=true' in call['command']
    assert 'shell' not in call['options']


def test_success_with_forged_postcondition_is_rejected():
    """A Schema-shaped Nav2 result cannot bypass physical verification."""
    forged = _success_result()
    forged['postcondition']['entered_keepout'] = True
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, runner=FixedRunner(forged),
    )
    with pytest.raises(SkillAdapterError, match='postconditions'):
        adapter.invoke(_inputs(), 120.0)


def test_output_identity_must_match_approved_inputs():
    """The subprocess cannot return evidence for a different goal."""
    wrong = _success_result()
    wrong['request']['goal']['x'] = 3.0
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, runner=FixedRunner(wrong),
    )
    with pytest.raises(SkillAdapterError, match='identity mismatch'):
        adapter.invoke(_inputs(), 120.0)


def test_outer_timeout_requests_fixed_emergency_cancellation():
    """A killed adapter process triggers a second fixed Nav2 cancel path."""
    calls = []

    def timeout_runner(command, **options):
        raise subprocess.TimeoutExpired(command, options['timeout'])

    def cancel_runner(command, **options):
        calls.append({'command': command, 'options': options})
        return SimpleNamespace(returncode=0, stdout='{}', stderr='')

    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT,
        runner=timeout_runner,
        cancel_runner=cancel_runner,
    )
    with pytest.raises(SkillAdapterError, match='cancellation requested'):
        adapter.invoke(_inputs(), 120.0)
    assert calls[0]['command'][1:3] == [
        '-m', 'robot_controlled_navigation_skills.cancel_ros',
    ]


def test_transient_sim_clock_startup_retries_before_motion():
    """Retry only the known preflight clock-zero exception."""
    cold = SimpleNamespace(
        returncode=1,
        stdout='',
        stderr=(
            'traceback\nrobot_navigation_skills.preview.'
            'RoutePreviewInputError: observed_at_ns must be positive\n'
        ),
    )
    success = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(_success_result()),
        stderr='',
    )
    runner = SequenceRunner([cold, success])
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )

    result = adapter.invoke(_inputs(), 120.0)

    assert result['state'] == 'succeeded'
    assert len(runner.calls) == 2
    assert runner.calls[1]['options']['timeout'] <= (
        runner.calls[0]['options']['timeout']
    )


def test_unknown_process_failure_is_not_retried_and_surfaces_tail():
    """Unknown exit-one errors remain fail-closed and observable."""
    failed = SimpleNamespace(
        returncode=1,
        stdout='',
        stderr='traceback\nRuntimeError: unexpected failure\n',
    )
    runner = SequenceRunner([failed])
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )

    with pytest.raises(
        SkillAdapterError, match='RuntimeError: unexpected failure',
    ):
        adapter.invoke(_inputs(), 120.0)

    assert len(runner.calls) == 1
