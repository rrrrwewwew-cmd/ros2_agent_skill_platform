"""Tests for deterministic Skill artifact verification."""

import json
from pathlib import Path

import pytest
from robot_skill_runtime import (
    ArtifactVerificationError,
    compute_artifact_hash,
    verify_artifact_lock,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = (
    REPOSITORY_ROOT / 'artifacts/check_robot_health/0.2.0.json'
)
SEMANTIC_LOCK_PATH = (
    REPOSITORY_ROOT / 'artifacts/query_semantic_target/0.1.0.json'
)
PREVIEW_LOCK_PATH = (
    REPOSITORY_ROOT / 'artifacts/preview_safe_route/0.1.0.json'
)


def test_reference_artifact_matches_simulation_tested_hash():
    """Runtime code and contract reproduce the Registry-bound digest."""
    lock = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
    verified = verify_artifact_lock(
        REPOSITORY_ROOT,
        'check_robot_health',
        '0.2.0',
        lock['artifact_hash'],
    )
    assert verified == lock
    assert compute_artifact_hash(
        REPOSITORY_ROOT, lock['files'],
    ) == lock['artifact_hash']


def test_artifact_hash_changes_when_content_changes(tmp_path):
    """A same-path file mutation cannot retain its previous digest."""
    file_path = tmp_path / 'skill.py'
    file_path.write_text('first\n', encoding='utf-8')
    first = compute_artifact_hash(tmp_path, ['skill.py'])
    file_path.write_text('second\n', encoding='utf-8')
    second = compute_artifact_hash(tmp_path, ['skill.py'])
    assert first != second


def test_semantic_query_artifact_matches_its_file_list():
    """The second Skill has an independently reproducible identity."""
    lock = json.loads(SEMANTIC_LOCK_PATH.read_text(encoding='utf-8'))
    verified = verify_artifact_lock(
        REPOSITORY_ROOT,
        lock['name'],
        lock['version'],
        lock['artifact_hash'],
    )
    assert verified == lock


def test_route_preview_artifact_matches_its_file_list():
    """The third Skill has an independently reproducible identity."""
    lock = json.loads(PREVIEW_LOCK_PATH.read_text(encoding='utf-8'))
    verified = verify_artifact_lock(
        REPOSITORY_ROOT,
        lock['name'],
        lock['version'],
        lock['artifact_hash'],
    )
    assert verified == lock


@pytest.mark.parametrize('path', ['../secret', '/tmp/secret'])
def test_artifact_path_cannot_escape_repository(tmp_path, path):
    """Artifact locks cannot read files outside their repository root."""
    with pytest.raises(ArtifactVerificationError, match='escapes'):
        compute_artifact_hash(tmp_path, [path])
