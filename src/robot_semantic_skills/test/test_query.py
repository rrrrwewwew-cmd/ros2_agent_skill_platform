"""Tests for deterministic project-one semantic map consumption."""

import json

import pytest
from robot_semantic_skills import (
    query_semantic_target,
    SemanticQueryInputError,
)


def _record(target_id='green_box'):
    return {
        'target_id': target_id,
        'observations_total': 2,
        'accepted_observations': 2,
        'rejected_observations': 0,
        'mean_position_m': {'x': 1.0, 'y': 2.0, 'z': 0.5},
        'position_stddev_m': {'x': 0.01, 'y': 0.02, 'z': 0.03},
        'last_observation_stamp_ns': 123,
        'last_wall_timestamp': '2026-07-18T12:00:00+08:00',
        'last_evidence': {
            'perception_backend': 'groundingdino_service',
            'model_score': 0.8,
            'verified_score': 0.7,
            'service_request_count': 2,
            'inference_ms': 300.0,
        },
    }


def _write_store(path, landmarks=None):
    document = {
        'schema_version': 1,
        'frame_id': 'map',
        'updated_at': '2026-07-18T12:00:00+08:00',
        'landmarks': landmarks or {},
    }
    path.write_text(json.dumps(document), encoding='utf-8')


def test_found_query_is_typed_and_does_not_modify_store(tmp_path):
    """A valid record is normalized from one immutable byte snapshot."""
    store = tmp_path / 'semantic_map.json'
    _write_store(store, {'green_box': _record()})
    original = store.read_bytes()

    result = query_semantic_target(
        store, 'semantic_landmarks_v1', 'green_box',
    )

    assert result['state'] == 'found'
    assert result['found'] is True
    assert result['source']['frame_id'] == 'map'
    assert len(result['source']['content_sha256']) == 64
    assert result['landmark']['observations']['accepted'] == 2
    assert store.read_bytes() == original


def test_missing_target_is_not_a_process_failure(tmp_path):
    """A valid map can truthfully report that one target is absent."""
    store = tmp_path / 'semantic_map.json'
    _write_store(store, {'green_box': _record()})

    result = query_semantic_target(
        store, 'semantic_landmarks_v1', 'blue_cylinder',
    )

    assert result['state'] == 'not_found'
    assert result['found'] is False
    assert result['landmark'] is None
    assert result['reasons']


def test_missing_and_malformed_stores_fail_closed(tmp_path):
    """Unavailable and inconsistent evidence are never treated as found."""
    missing = query_semantic_target(
        tmp_path / 'missing.json',
        'rbot_water_puddle_v2',
        'water_puddle',
    )
    assert missing['state'] == 'unavailable'

    store = tmp_path / 'semantic_map.json'
    record = _record()
    record['observations_total'] = 99
    _write_store(store, {'green_box': record})
    invalid = query_semantic_target(
        store, 'semantic_landmarks_v1', 'green_box',
    )
    assert invalid['state'] == 'invalid'
    assert 'inconsistent' in invalid['reasons'][0]


@pytest.mark.parametrize(
    'profile,target',
    [
        ('../../private', 'green_box'),
        ('semantic_landmarks_v1', '../secret'),
        ('semantic_landmarks_v1', '绿色箱子'),
    ],
)
def test_inputs_cannot_expand_profile_or_path_surface(
        tmp_path, profile, target):
    """The core accepts only approved profiles and canonical target ids."""
    with pytest.raises(SemanticQueryInputError):
        query_semantic_target(tmp_path / 'unused', profile, target)
