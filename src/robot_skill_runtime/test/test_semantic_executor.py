"""End-to-end Runtime tests for the governed semantic query Skill."""

import json
from pathlib import Path
from types import SimpleNamespace

from robot_skill_registry import (
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    SkillRegistry,
)
from robot_skill_runtime import SkillExecutor
from robot_skill_runtime.adapters import SemanticTargetQueryAdapter
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / 'skills/query_semantic_target/skill.yaml'
LOCK_PATH = REPOSITORY_ROOT / 'artifacts/query_semantic_target/0.1.0.json'


class IncrementingClock:
    """Provide deterministic timestamps across release and execution."""

    def __init__(self, start=8_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


class FixedRunner:
    """Return one semantic query result without reading operator files."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(self.result),
            stderr='',
        )


def _semantic_result():
    return {
        'schema_version': 1,
        'skill': 'query_semantic_target',
        'skill_version': '0.1.0',
        'state': 'found',
        'query': {
            'map_profile': 'semantic_landmarks_v1',
            'target_id': 'green_box',
        },
        'source': {
            'store_profile': 'semantic_landmarks_v1',
            'content_sha256': 'b' * 64,
            'frame_id': 'map',
            'updated_at': 'timestamp',
        },
        'found': True,
        'landmark': {
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
        },
        'reasons': [],
    }


def _register_active(database, tmp_path, clock):
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding='utf-8'))
    artifact_hash = json.loads(
        LOCK_PATH.read_text(encoding='utf-8')
    )['artifact_hash']
    private_key = tmp_path / 'release.pem'
    public_key = tmp_path / 'release.pub.pem'
    generate_ed25519_keypair(private_key, public_key)
    with SkillRegistry(database, clock_ns=clock) as registry:
        record = registry.register_manifest(
            manifest, artifact_hash=artifact_hash,
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
            'test_policy', 'read-only test approval',
        )
        envelope = create_signature_envelope(
            REPOSITORY_ROOT,
            record['name'],
            record['version'],
            record['artifact_hash'],
            private_key,
            'test_signer',
            clock_ns=clock,
        )
        record = registry.record_verified_signature(
            record['name'], record['version'], record['artifact_hash'],
            canonical_json(envelope), 'test_verifier', 'verified fixture',
        )
        record = registry.advance(
            record['name'], record['version'], 'ACTIVE', 'SIGNED',
            'test_release', 'activated fixture',
        )
    return record, public_key


def _invocation(run_id, artifact_hash, inputs=None):
    return {
        'schema_version': 1,
        'run_id': run_id,
        'trace_id': f'trace_{run_id}',
        'skill_name': 'query_semantic_target',
        'skill_version': '0.1.0',
        'artifact_hash': artifact_hash,
        'inputs': inputs or {
            'map_profile': 'semantic_landmarks_v1',
            'target_id': 'green_box',
        },
    }


def test_signed_active_semantic_query_executes_through_runtime(tmp_path):
    """The second Skill crosses every Registry and Runtime gate."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    record, public_key = _register_active(database, tmp_path, clock)
    runner = FixedRunner(_semantic_result())
    adapter = SemanticTargetQueryAdapter(
        REPOSITORY_ROOT,
        profile_paths={
            'semantic_landmarks_v1': tmp_path / 'approved_store.json',
        },
        runner=runner,
    )
    executor = SkillExecutor(
        database,
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
        trusted_public_key=public_key,
    )

    result = executor.execute(
        _invocation('semantic_found', record['artifact_hash'])
    )

    assert result['status'] == 'succeeded'
    assert result['output']['state'] == 'found'
    assert result['output']['landmark']['target_id'] == 'green_box'
    assert len(runner.calls) == 1


def test_manifest_rejects_noncanonical_target_before_adapter(tmp_path):
    """Runtime input Schema blocks aliases and path-like target values."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    record, public_key = _register_active(database, tmp_path, clock)
    runner = FixedRunner(_semantic_result())
    adapter = SemanticTargetQueryAdapter(REPOSITORY_ROOT, runner=runner)
    executor = SkillExecutor(
        database,
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
        trusted_public_key=public_key,
    )

    result = executor.execute(_invocation(
        'semantic_alias_rejected',
        record['artifact_hash'],
        {
            'map_profile': 'semantic_landmarks_v1',
            'target_id': '../green_box',
        },
    ))

    assert result['status'] == 'failed'
    assert 'invalid Skill inputs' in result['error']
    assert runner.calls == []
