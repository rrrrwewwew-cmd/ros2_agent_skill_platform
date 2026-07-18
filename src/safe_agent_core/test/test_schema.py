"""Structural checks for repository Skill artifacts."""

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_json_schema_is_valid_json():
    """The machine-readable contract must remain parseable JSON."""
    schema_path = REPOSITORY_ROOT / 'schemas/skill.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    assert schema['$schema'].endswith('2020-12/schema')
    assert schema['properties']['schema_version']['const'] == 1


def test_reference_skill_has_governance_artifacts():
    """The reference Skill includes instructions, card, and eval cases."""
    skill_dir = REPOSITORY_ROOT / 'skills/check_robot_health'
    required = [
        skill_dir / 'SKILL.md',
        skill_dir / 'skill.yaml',
        skill_dir / 'skill-card.md',
        skill_dir / 'evals/evals.json',
    ]
    assert all(path.is_file() for path in required)
