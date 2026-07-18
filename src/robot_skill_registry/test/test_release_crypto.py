"""Tests for Ed25519 Skill release signing and Registry recording."""

import json
from pathlib import Path
import stat

import pytest
from robot_skill_registry import (
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    ReleaseSignatureError,
    SkillRegistry,
    verify_and_record_signature,
    verify_signature_envelope,
)
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'
LOCK_PATH = REPOSITORY_ROOT / 'artifacts/check_robot_health/0.2.0.json'


class IncrementingClock:
    """Provide deterministic non-repeating nanosecond timestamps."""

    def __init__(self, start=7_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


def _identity():
    lock = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
    return lock['name'], lock['version'], lock['artifact_hash']


def _keypair(tmp_path, name='release'):
    private_key = tmp_path / f'{name}.pem'
    public_key = tmp_path / f'{name}.pub.pem'
    result = generate_ed25519_keypair(private_key, public_key)
    return private_key, public_key, result


def _approved_registry(database, clock):
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding='utf-8'))
    name, version, artifact_hash = _identity()
    with SkillRegistry(database, clock_ns=clock) as registry:
        registry.register_manifest(manifest, artifact_hash=artifact_hash)
        current = 'DRAFT'
        for target in (
            'GENERATED', 'STATIC_VALIDATED', 'BUILT', 'UNIT_TESTED',
            'SIMULATION_TESTED',
        ):
            registry.advance(
                name, version, target, current,
                'test_pipeline', f'passed {target}',
            )
            current = target
        return registry.approve(
            name, version, artifact_hash,
            'test_policy', 'read-only test approval',
        )


def test_keygen_sign_and_verify_round_trip(tmp_path):
    """A private key signs the exact lock and its public key verifies it."""
    private_key, public_key, key_result = _keypair(tmp_path)
    assert stat.S_IMODE(private_key.stat().st_mode) == 0o600
    assert stat.S_IMODE(public_key.stat().st_mode) == 0o644
    name, version, artifact_hash = _identity()
    envelope = create_signature_envelope(
        REPOSITORY_ROOT,
        name,
        version,
        artifact_hash,
        private_key,
        'test_signer',
        clock_ns=lambda: 123,
    )
    verified = verify_signature_envelope(
        canonical_json(envelope),
        public_key,
        expected_name=name,
        expected_version=version,
        expected_hash=artifact_hash,
        repository_root=REPOSITORY_ROOT,
    )
    assert verified == envelope
    assert (
        verified['public_key_fingerprint'] ==
        key_result['public_key_fingerprint']
    )


def test_tampered_signed_field_and_wrong_key_are_rejected(tmp_path):
    """Neither envelope mutation nor a different trusted key can verify."""
    private_key, public_key, _result = _keypair(tmp_path, 'first')
    _unused_private, wrong_public, _wrong_result = _keypair(tmp_path, 'wrong')
    name, version, artifact_hash = _identity()
    envelope = create_signature_envelope(
        REPOSITORY_ROOT,
        name,
        version,
        artifact_hash,
        private_key,
        'test_signer',
        clock_ns=lambda: 123,
    )
    tampered = dict(envelope)
    tampered['signer'] = 'attacker'
    with pytest.raises(ReleaseSignatureError, match='verification failed'):
        verify_signature_envelope(tampered, public_key)
    with pytest.raises(ReleaseSignatureError, match='fingerprint mismatch'):
        verify_signature_envelope(envelope, wrong_public)


def test_verified_envelope_is_recorded_only_after_crypto_check(tmp_path):
    """Registry enters SIGNED only through a valid hash-bound proof."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    approved = _approved_registry(database, clock)
    private_key, public_key, _result = _keypair(tmp_path)
    envelope = create_signature_envelope(
        REPOSITORY_ROOT,
        approved['name'],
        approved['version'],
        approved['artifact_hash'],
        private_key,
        'test_signer',
        clock_ns=clock,
    )
    forged = dict(envelope)
    forged['signature'] = 'AAAA'
    with pytest.raises(ReleaseSignatureError, match='verification failed'):
        verify_and_record_signature(
            database,
            REPOSITORY_ROOT,
            forged,
            public_key,
            'forged attempt',
            clock_ns=clock,
        )
    with SkillRegistry(database, clock_ns=clock) as registry:
        assert registry.get_skill(
            approved['name'], approved['version']
        )['state'] == 'HUMAN_APPROVED'
    signed = verify_and_record_signature(
        database,
        REPOSITORY_ROOT,
        envelope,
        public_key,
        'cryptographic release proof verified',
        clock_ns=clock,
    )
    assert signed['state'] == 'SIGNED'
    assert json.loads(signed['signature']) == envelope
