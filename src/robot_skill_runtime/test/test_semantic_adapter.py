"""Tests for the fixed project-one semantic map Runtime adapter."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from robot_skill_runtime.adapters import (
    SemanticTargetQueryAdapter,
    SkillAdapterError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class FixedRunner:
    """Return one configured subprocess result and record the command."""

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


def _result(state='found'):
    found = state == 'found'
    landmark = None
    if found:
        landmark = {
            'target_id': 'green_box',
            'mean_position_m': {'x': 1.0, 'y': 2.0, 'z': 0.5},
            'position_stddev_m': {'x': 0.1, 'y': 0.1, 'z': 0.1},
            'observations': {'total': 2, 'accepted': 2, 'rejected': 0},
            'last_observation_stamp_ns': 123,
            'last_wall_timestamp': 'timestamp',
            'last_evidence': {
                'perception_backend': 'groundingdino_service',
                'model_score': 0.8,
                'verified_score': 0.7,
                'service_request_count': 2,
                'inference_ms': 300.0,
            },
        }
    return {
        'schema_version': 1,
        'skill': 'query_semantic_target',
        'skill_version': '0.1.0',
        'state': state,
        'query': {
            'map_profile': 'semantic_landmarks_v1',
            'target_id': 'green_box',
        },
        'source': {
            'store_profile': 'semantic_landmarks_v1',
            'content_sha256': 'a' * 64,
            'frame_id': 'map',
            'updated_at': 'timestamp',
        },
        'found': found,
        'landmark': landmark,
        'reasons': [] if found else ['target is absent'],
    }


def test_adapter_uses_fixed_profile_path_without_shell(tmp_path):
    """Agent input selects a profile but can never supply a file path."""
    store = tmp_path / 'approved.json'
    runner = FixedRunner(_result())
    adapter = SemanticTargetQueryAdapter(
        REPOSITORY_ROOT,
        profile_paths={'semantic_landmarks_v1': store},
        runner=runner,
    )

    result = adapter.invoke(
        {'map_profile': 'semantic_landmarks_v1', 'target_id': 'green_box'},
        3.0,
    )

    assert result['state'] == 'found'
    call = runner.calls[0]
    assert call['command'][0:3] == [
        call['command'][0], '-m', 'robot_semantic_skills.query_cli',
    ]
    assert str(store.resolve()) in call['command']
    assert call['options']['check'] is False
    assert 'shell' not in call['options']


def test_unapproved_profile_is_rejected_before_process(tmp_path):
    """A profile name cannot become arbitrary filesystem access."""
    runner = FixedRunner(_result())
    adapter = SemanticTargetQueryAdapter(
        REPOSITORY_ROOT,
        profile_paths={'semantic_landmarks_v1': tmp_path / 'approved.json'},
        runner=runner,
    )
    with pytest.raises(SkillAdapterError, match='not approved'):
        adapter.invoke(
            {'map_profile': '../../private', 'target_id': 'green_box'}, 3.0,
        )
    assert runner.calls == []


def test_adapter_rejects_identity_and_postcondition_mismatch(tmp_path):
    """Schema-shaped output cannot answer a different requested target."""
    wrong = _result()
    wrong['query']['target_id'] = 'blue_cylinder'
    wrong['landmark']['target_id'] = 'blue_cylinder'
    runner = FixedRunner(wrong)
    adapter = SemanticTargetQueryAdapter(
        REPOSITORY_ROOT,
        profile_paths={'semantic_landmarks_v1': tmp_path / 'approved.json'},
        runner=runner,
    )
    with pytest.raises(SkillAdapterError, match='identity mismatch'):
        adapter.invoke(
            {'map_profile': 'semantic_landmarks_v1', 'target_id': 'green_box'},
            3.0,
        )


def test_adapter_timeout_is_bounded(tmp_path):
    """A stuck file query becomes a bounded adapter error."""
    def timeout_runner(command, **options):
        raise subprocess.TimeoutExpired(command, options['timeout'])

    adapter = SemanticTargetQueryAdapter(
        REPOSITORY_ROOT,
        profile_paths={'semantic_landmarks_v1': tmp_path / 'approved.json'},
        runner=timeout_runner,
    )
    with pytest.raises(SkillAdapterError, match='timed out'):
        adapter.invoke(
            {'map_profile': 'semantic_landmarks_v1', 'target_id': 'green_box'},
            3.0,
        )
