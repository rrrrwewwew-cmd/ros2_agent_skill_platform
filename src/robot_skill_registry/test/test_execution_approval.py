"""Tests for exact, expiring, one-time execution approvals."""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from jsonschema import Draft202012Validator
import pytest
from robot_skill_registry import (
    RegistryConflictError,
    RegistryContractError,
    SkillRegistry,
)
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HEALTH_MANIFEST = REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'


class MutableClock:
    """Provide explicit wall-clock values for expiry tests."""

    def __init__(self, value=10_000_000_000):
        self.value = value

    def __call__(self):
        return self.value


def _controlled_manifest():
    manifest = yaml.safe_load(HEALTH_MANIFEST.read_text(encoding='utf-8'))
    manifest.update({
        'name': 'navigate_to_approved_pose',
        'version': '0.1.0',
        'description': 'Execute one exact human-approved Nav2 pose goal.',
        'entrypoint': 'robot_navigation_skills.navigation:navigate',
        'safety_level': 'controlled',
        'requires_human_approval': True,
    })
    manifest['ros_permissions']['topics_write'] = []
    return manifest


def _activate(registry):
    artifact_hash = 'a' * 64
    record = registry.register_manifest(
        _controlled_manifest(), artifact_hash=artifact_hash,
    )
    current = 'DRAFT'
    for target in (
        'GENERATED', 'STATIC_VALIDATED', 'BUILT', 'UNIT_TESTED',
        'SIMULATION_TESTED',
    ):
        record = registry.advance(
            record['name'], record['version'], target, current,
            'test_pipeline', f'passed {target}',
        )
        current = target
    record = registry.approve(
        record['name'], record['version'], artifact_hash,
        'human_reviewer', 'fixture release approval',
    )
    record = registry.record_verified_signature(
        record['name'], record['version'], artifact_hash,
        'fixture-signature', 'fixture-signer', 'fixture verification',
    )
    return registry.advance(
        record['name'], record['version'], 'ACTIVE', 'SIGNED',
        'test_release', 'fixture activation',
    )


def _invocation(artifact_hash='a' * 64):
    return {
        'schema_version': 1,
        'approval_id': 'approval_nav_001',
        'run_id': 'run_nav_001',
        'trace_id': 'trace_nav_001',
        'skill_name': 'navigate_to_approved_pose',
        'skill_version': '0.1.0',
        'artifact_hash': artifact_hash,
        'inputs': {
            'goal_x': 4.5,
            'goal_y': 0.0,
            'goal_yaw_deg': 0.0,
        },
    }


def test_exact_approval_is_consumed_once_and_matches_schema(tmp_path):
    """One human decision authorizes exactly one immutable invocation."""
    clock = MutableClock()
    with SkillRegistry(tmp_path / 'registry.db', clock) as registry:
        _activate(registry)
        approval = registry.issue_execution_approval(
            _invocation(), 'human_li', 'approved exact test goal', 60.0,
        )
        schema = json.loads((
            REPOSITORY_ROOT / 'schemas/execution_approval.schema.json'
        ).read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(approval)
        assert approval['consumed_at_ns'] is None
        clock.value += 1
        consumed = registry.consume_execution_approval(
            approval['approval_id'], _invocation(),
        )
        assert consumed['consumed_by_run_id'] == 'run_nav_001'
        with pytest.raises(RegistryConflictError, match='already'):
            registry.consume_execution_approval(
                approval['approval_id'], _invocation(),
            )


def test_approval_rejects_input_tampering_and_expiry(tmp_path):
    """Changing a goal or waiting past TTL cannot start motion."""
    clock = MutableClock()
    with SkillRegistry(tmp_path / 'registry.db', clock) as registry:
        _activate(registry)
        registry.issue_execution_approval(
            _invocation(), 'human_li', 'approved exact test goal', 1.0,
        )
        changed = deepcopy(_invocation())
        changed['inputs']['goal_x'] = 3.0
        with pytest.raises(RegistryContractError, match='not bound'):
            registry.consume_execution_approval(
                'approval_nav_001', changed,
            )
        clock.value += 1_000_000_001
        with pytest.raises(RegistryContractError, match='expired'):
            registry.consume_execution_approval(
                'approval_nav_001', _invocation(),
            )


def test_read_only_skill_cannot_receive_execution_approval(tmp_path):
    """Per-run approval records are reserved for physical/high actions."""
    clock = MutableClock()
    manifest = yaml.safe_load(HEALTH_MANIFEST.read_text(encoding='utf-8'))
    with SkillRegistry(tmp_path / 'registry.db', clock) as registry:
        record = registry.register_manifest(
            manifest, artifact_hash='b' * 64,
        )
        current = 'DRAFT'
        for target in (
            'GENERATED', 'STATIC_VALIDATED', 'BUILT', 'UNIT_TESTED',
            'SIMULATION_TESTED',
        ):
            record = registry.advance(
                record['name'], record['version'], target, current,
                'test_pipeline', f'passed {target}',
            )
            current = target
        record = registry.approve(
            record['name'], record['version'], record['artifact_hash'],
            'test_policy', 'read-only release approval',
        )
        record = registry.record_verified_signature(
            record['name'], record['version'], record['artifact_hash'],
            'fixture-signature', 'fixture-signer', 'fixture verification',
        )
        registry.advance(
            record['name'], record['version'], 'ACTIVE', 'SIGNED',
            'test_release', 'fixture activation',
        )
        invocation = _invocation('b' * 64)
        invocation['skill_name'] = manifest['name']
        invocation['skill_version'] = manifest['version']
        with pytest.raises(RegistryContractError, match='read-only'):
            registry.issue_execution_approval(
                invocation, 'human_li', 'should not be allowed',
            )


def test_version_one_database_migrates_in_place(tmp_path):
    """Existing local Registry data opens after adding approval storage."""
    database = tmp_path / 'registry.db'
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE schema_metadata ('
            'component TEXT PRIMARY KEY, schema_version INTEGER NOT NULL)'
        )
        connection.execute(
            'INSERT INTO schema_metadata VALUES (?, ?)',
            ('robot_skill_registry', 1),
        )
    with SkillRegistry(database, MutableClock()):
        pass
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            'SELECT schema_version FROM schema_metadata '
            'WHERE component = ?',
            ('robot_skill_registry',),
        ).fetchone()[0]
    assert version == 2
