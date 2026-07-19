"""Structural checks for repository Skill artifacts."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from safe_agent_core import analyze_experiment


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_json_schemas_are_valid_json():
    """Every machine-readable contract remains parseable Draft 2020-12."""
    schema_paths = sorted((REPOSITORY_ROOT / 'schemas').glob('*.schema.json'))
    assert len(schema_paths) == 16
    for schema_path in schema_paths:
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        assert schema['$schema'].endswith('2020-12/schema')
        assert schema['properties']['schema_version']['const'] == 1


def test_experiment_fixture_manifest_is_valid_json():
    """The frozen Phase 1 experiment manifest remains machine-readable."""
    manifest_path = (
        REPOSITORY_ROOT / 'examples/experiment_jitter_v1/manifest.json'
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['schema_version'] == 1
    assert manifest['run_id'] == 'jitter_demo_001'


def _load_schema(name):
    path = REPOSITORY_ROOT / f'schemas/{name}.schema.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_experiment_fixture_and_analysis_match_schemas():
    """Frozen inputs and deterministic outputs satisfy their contracts."""
    fixture_dir = REPOSITORY_ROOT / 'examples/experiment_jitter_v1'
    manifest = json.loads(
        (fixture_dir / 'manifest.json').read_text(encoding='utf-8')
    )
    Draft202012Validator(_load_schema('experiment_run')).validate(manifest)
    analysis = analyze_experiment(fixture_dir / 'manifest.json')
    Draft202012Validator(_load_schema('experiment_analysis')).validate(
        analysis
    )


def test_agent_trace_lines_match_event_schema():
    """Every JSONL Trace event satisfies the frozen event contract."""
    trace_path = (
        REPOSITORY_ROOT / 'examples/experiment_jitter_v1/agent_trace.jsonl'
    )
    validator = Draft202012Validator(_load_schema('agent_trace_event'))
    events = [
        json.loads(line)
        for line in trace_path.read_text(encoding='utf-8').splitlines()
    ]
    assert len(events) == 2
    for event in events:
        validator.validate(event)


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


def test_live_health_evidence_matches_result_schema():
    """Operator-captured rbot evidence remains machine-verifiable."""
    result = json.loads((
        REPOSITORY_ROOT /
        'evidence/check_robot_health/rbot_live_simulation_v1.json'
    ).read_text(encoding='utf-8'))
    Draft202012Validator(_load_schema('robot_health_result')).validate(result)


def test_runtime_invocation_and_artifact_lock_match_schemas():
    """Versioned runtime examples satisfy their machine contracts."""
    invocation = json.loads((
        REPOSITORY_ROOT / 'examples/check_robot_health_invocation_v1.json'
    ).read_text(encoding='utf-8'))
    lock = json.loads((
        REPOSITORY_ROOT / 'artifacts/check_robot_health/0.2.0.json'
    ).read_text(encoding='utf-8'))
    Draft202012Validator(_load_schema('skill_invocation')).validate(
        invocation
    )
    Draft202012Validator(_load_schema('skill_artifact_lock')).validate(lock)
