"""Ed25519 release signing and verification for immutable Skill artifacts."""

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from safe_agent_core import (
    ArtifactVerificationError,
    verify_artifact_lock,
)

from .registry import RegistryContractError, SkillRegistry


SIGNATURE_FIELDS = {
    'schema_version',
    'signature_algorithm',
    'artifact_hash_algorithm',
    'name',
    'version',
    'artifact_hash',
    'signer',
    'created_at_ns',
    'public_key_fingerprint',
    'signature',
}
UNSIGNED_FIELDS = SIGNATURE_FIELDS - {'signature'}


class ReleaseSignatureError(ValueError):
    """Raised when release keys, envelopes, or signatures are invalid."""


def canonical_json(value):
    """Serialize one release value into its deterministic UTF-8 form."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )


def _atomic_write(path, content, mode, overwrite=False):
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists() and not overwrite:
        raise ReleaseSignatureError(f'refusing to overwrite: {target}')
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{target.name}.', dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        target.chmod(mode)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _public_bytes(public_key):
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def public_key_fingerprint(public_key):
    """Return a SHA-256 fingerprint for one Ed25519 public key."""
    return hashlib.sha256(_public_bytes(public_key)).hexdigest()


def generate_ed25519_keypair(private_path, public_path, overwrite=False):
    """Create one local release keypair with a mode-0600 private key."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_target = _atomic_write(
        private_path, private_pem, 0o600, overwrite=overwrite,
    )
    try:
        public_target = _atomic_write(
            public_path, public_pem, 0o644, overwrite=overwrite,
        )
    except Exception:
        if not overwrite:
            private_target.unlink(missing_ok=True)
        raise
    return {
        'private_key': str(private_target),
        'public_key': str(public_target),
        'public_key_fingerprint': public_key_fingerprint(public_key),
    }


def _load_private_key(path):
    key_path = Path(path).expanduser().resolve()
    try:
        mode = stat.S_IMODE(key_path.stat().st_mode)
        if mode & 0o077:
            raise ReleaseSignatureError(
                'private key permissions must not allow group or other access'
            )
        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None,
        )
    except ReleaseSignatureError:
        raise
    except (OSError, ValueError, TypeError) as exception:
        raise ReleaseSignatureError('cannot load release private key') from exception
    if not isinstance(key, Ed25519PrivateKey):
        raise ReleaseSignatureError('release private key must be Ed25519')
    return key


def load_public_key(path):
    """Load and type-check one trusted Ed25519 public key."""
    try:
        key = serialization.load_pem_public_key(
            Path(path).expanduser().read_bytes()
        )
    except (OSError, ValueError, TypeError) as exception:
        raise ReleaseSignatureError('cannot load trusted public key') from exception
    if not isinstance(key, Ed25519PublicKey):
        raise ReleaseSignatureError('trusted public key must be Ed25519')
    return key


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ReleaseSignatureError(f'{field} must be non-empty text')
    return value.strip()


def _validate_envelope_shape(envelope):
    if not isinstance(envelope, dict):
        raise ReleaseSignatureError('signature envelope must be an object')
    if set(envelope) != SIGNATURE_FIELDS:
        raise ReleaseSignatureError('signature envelope fields do not match schema')
    if envelope['schema_version'] != 1:
        raise ReleaseSignatureError('unsupported signature envelope schema')
    if envelope['signature_algorithm'] != 'ed25519':
        raise ReleaseSignatureError('unsupported signature algorithm')
    if envelope['artifact_hash_algorithm'] != 'sha256-file-list-v1':
        raise ReleaseSignatureError('unsupported artifact hash algorithm')
    for field in (
        'name', 'version', 'artifact_hash', 'signer',
        'public_key_fingerprint', 'signature',
    ):
        _require_text(envelope[field], field)
    for field in ('artifact_hash', 'public_key_fingerprint'):
        value = envelope[field]
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ReleaseSignatureError(f'{field} must be lowercase SHA-256')
    created_at_ns = envelope['created_at_ns']
    if (
        isinstance(created_at_ns, bool) or
        not isinstance(created_at_ns, int) or
        created_at_ns < 0
    ):
        raise ReleaseSignatureError('created_at_ns must be a non-negative integer')


def parse_signature_envelope(value):
    """Parse and validate an envelope object or canonical JSON text."""
    if isinstance(value, str):
        try:
            envelope = json.loads(value)
        except json.JSONDecodeError as exception:
            raise ReleaseSignatureError(
                'signature envelope is not valid JSON'
            ) from exception
    else:
        envelope = value
    _validate_envelope_shape(envelope)
    return dict(envelope)


def create_signature_envelope(repository_root, name, version, artifact_hash,
                              private_key_path, signer,
                              clock_ns=time.time_ns):
    """Verify an artifact lock and create its Ed25519 release envelope."""
    try:
        verify_artifact_lock(repository_root, name, version, artifact_hash)
    except ArtifactVerificationError as exception:
        raise ReleaseSignatureError(str(exception)) from exception
    private_key = _load_private_key(private_key_path)
    public_key = private_key.public_key()
    envelope = {
        'schema_version': 1,
        'signature_algorithm': 'ed25519',
        'artifact_hash_algorithm': 'sha256-file-list-v1',
        'name': _require_text(name, 'name'),
        'version': _require_text(version, 'version'),
        'artifact_hash': _require_text(artifact_hash, 'artifact_hash'),
        'signer': _require_text(signer, 'signer'),
        'created_at_ns': clock_ns(),
        'public_key_fingerprint': public_key_fingerprint(public_key),
    }
    payload = canonical_json(envelope).encode('utf-8')
    envelope['signature'] = base64.b64encode(
        private_key.sign(payload)
    ).decode('ascii')
    _validate_envelope_shape(envelope)
    return envelope


def verify_signature_envelope(value, public_key_path, expected_name=None,
                              expected_version=None, expected_hash=None,
                              repository_root=None):
    """Verify identity, optional local artifact content, and Ed25519 proof."""
    envelope = parse_signature_envelope(value)
    expectations = {
        'name': expected_name,
        'version': expected_version,
        'artifact_hash': expected_hash,
    }
    for field, expected in expectations.items():
        if expected is not None and envelope[field] != expected:
            raise ReleaseSignatureError(f'signature {field} mismatch')
    if repository_root is not None:
        try:
            verify_artifact_lock(
                repository_root,
                envelope['name'],
                envelope['version'],
                envelope['artifact_hash'],
            )
        except ArtifactVerificationError as exception:
            raise ReleaseSignatureError(str(exception)) from exception
    public_key = load_public_key(public_key_path)
    fingerprint = public_key_fingerprint(public_key)
    if envelope['public_key_fingerprint'] != fingerprint:
        raise ReleaseSignatureError('signature public key fingerprint mismatch')
    unsigned = {field: envelope[field] for field in UNSIGNED_FIELDS}
    try:
        signature = base64.b64decode(
            envelope['signature'], validate=True,
        )
        public_key.verify(
            signature, canonical_json(unsigned).encode('utf-8')
        )
    except (binascii.Error, InvalidSignature) as exception:
        raise ReleaseSignatureError('release signature verification failed') from exception
    return envelope


def verify_and_record_signature(database_path, repository_root, envelope,
                                public_key_path, reason,
                                clock_ns=time.time_ns):
    """Verify one envelope externally, then atomically record it in Registry."""
    parsed = parse_signature_envelope(envelope)
    verified = verify_signature_envelope(
        parsed,
        public_key_path,
        expected_name=parsed['name'],
        expected_version=parsed['version'],
        expected_hash=parsed['artifact_hash'],
        repository_root=repository_root,
    )
    signer_identity = (
        f"{verified['signer']}@{verified['public_key_fingerprint'][:16]}"
    )
    with SkillRegistry(database_path, clock_ns=clock_ns) as registry:
        record = registry.get_skill(verified['name'], verified['version'])
        if record['artifact_hash'] != verified['artifact_hash']:
            raise RegistryContractError(
                'signature artifact hash does not match Registry'
            )
        return registry.record_verified_signature(
            verified['name'],
            verified['version'],
            verified['artifact_hash'],
            canonical_json(verified),
            signer_identity,
            reason,
        )
