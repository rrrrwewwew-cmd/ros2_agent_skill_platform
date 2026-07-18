"""Tests for immutable Skill governance and transactional lifecycle state."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from robot_skill_registry import (
    RegistryConflictError,
    RegistryContractError,
    SkillRegistry,
)
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_MANIFEST = (
    REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'
)


class IncrementingClock:
    """Deterministic nanosecond clock for auditable tests."""

    def __init__(self, start=1_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


def load_manifest():
    """Load a fresh reference manifest mapping."""
    return yaml.safe_load(REFERENCE_MANIFEST.read_text(encoding='utf-8'))


def advance_to_simulation_tested(registry, record):
    """Advance through deterministic build and test gates."""
    current = record['state']
    for target in [
        'GENERATED',
        'STATIC_VALIDATED',
        'BUILT',
        'UNIT_TESTED',
        'SIMULATION_TESTED',
    ]:
        record = registry.advance(
            record['name'],
            record['version'],
            target,
            current,
            'ci',
            f'validated {target.lower()}',
        )
        current = target
    return record


def test_registration_is_idempotent_but_version_content_is_immutable(tmp_path):
    """Retries succeed while same-version mutation is rejected."""
    with SkillRegistry(tmp_path / 'registry.db', IncrementingClock()) as registry:
        original = registry.register_manifest(load_manifest())
        repeated = registry.register_manifest(load_manifest())
        assert repeated == original
        mutated = deepcopy(load_manifest())
        mutated['description'] += ' Changed after registration.'
        with pytest.raises(RegistryConflictError, match='immutable'):
            registry.register_manifest(mutated)


def test_lifecycle_cannot_skip_or_bypass_governance_operations(tmp_path):
    """Lifecycle edges, approval, and signing require their dedicated gates."""
    with SkillRegistry(tmp_path / 'registry.db', IncrementingClock()) as registry:
        record = registry.register_manifest(load_manifest())
        with pytest.raises(RegistryContractError, match='illegal Skill transition'):
            registry.advance(
                record['name'], record['version'], 'BUILT', 'DRAFT',
                'ci', 'attempted skip',
            )
        record = advance_to_simulation_tested(registry, record)
        with pytest.raises(RegistryContractError, match='dedicated'):
            registry.advance(
                record['name'], record['version'], 'HUMAN_APPROVED',
                'SIMULATION_TESTED', 'reviewer', 'attempted bypass',
            )


def test_approval_signature_and_activation_are_hash_bound(tmp_path):
    """Only the reviewed and signed artifact can become ACTIVE."""
    with SkillRegistry(tmp_path / 'registry.db', IncrementingClock()) as registry:
        record = advance_to_simulation_tested(
            registry,
            registry.register_manifest(load_manifest()),
        )
        with pytest.raises(RegistryConflictError, match='artifact hash'):
            registry.approve(
                record['name'], record['version'], '0' * 64,
                'reviewer', 'wrong artifact',
            )
        record = registry.approve(
            record['name'], record['version'], record['artifact_hash'],
            'reviewer', 'tests and diff reviewed',
        )
        assert record['state'] == 'HUMAN_APPROVED'
        record = registry.record_verified_signature(
            record['name'],
            record['version'],
            record['artifact_hash'],
            'fixture-signature:check_robot_health:0.2.0',
            'release_verifier',
            'detached signature verified',
        )
        assert record['state'] == 'SIGNED'
        record = registry.advance(
            record['name'], record['version'], 'ACTIVE', 'SIGNED',
            'release_manager', 'released to runtime',
        )
        assert record['state'] == 'ACTIVE'
        assert record['signature'].startswith('fixture-signature:')
        assert len(registry.list_events(record['name'], record['version'])) == 9
        approvals = registry.list_approvals(record['name'], record['version'])
        assert [approval['decision'] for approval in approvals] == ['APPROVED']


def test_rejected_approval_does_not_advance_state(tmp_path):
    """A rejected review is durable evidence but not an activation step."""
    with SkillRegistry(tmp_path / 'registry.db', IncrementingClock()) as registry:
        record = advance_to_simulation_tested(
            registry,
            registry.register_manifest(load_manifest()),
        )
        record = registry.approve(
            record['name'], record['version'], record['artifact_hash'],
            'reviewer', 'hidden test missing', decision='REJECTED',
        )
        assert record['state'] == 'SIMULATION_TESTED'
        assert registry.list_approvals(
            record['name'], record['version']
        )[0]['decision'] == 'REJECTED'


def test_state_survives_process_reopen_and_stale_writer_is_rejected(tmp_path):
    """Persistent state and expected-state checks prevent double advance."""
    database = tmp_path / 'registry.db'
    clock = IncrementingClock()
    first = SkillRegistry(database, clock)
    second = SkillRegistry(database, clock)
    try:
        record = first.register_manifest(load_manifest())
        second.advance(
            record['name'], record['version'], 'GENERATED', 'DRAFT',
            'generator_b', 'generation complete',
        )
        with pytest.raises(RegistryConflictError, match='stale Skill state'):
            first.advance(
                record['name'], record['version'], 'GENERATED', 'DRAFT',
                'generator_a', 'duplicate completion',
            )
    finally:
        first.close()
        second.close()
    with SkillRegistry(database, clock) as reopened:
        assert reopened.get_skill(
            record['name'], record['version']
        )['state'] == 'GENERATED'


def test_registry_record_matches_machine_contract(tmp_path):
    """Public Registry records satisfy the repository JSON Schema."""
    schema = json.loads(
        (REPOSITORY_ROOT / 'schemas/registry_skill_record.schema.json')
        .read_text(encoding='utf-8')
    )
    with SkillRegistry(tmp_path / 'registry.db', IncrementingClock()) as registry:
        record = registry.register_manifest(load_manifest())
    Draft202012Validator(schema).validate(record)
