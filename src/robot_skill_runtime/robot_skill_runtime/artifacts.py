"""Deterministically verify immutable Skill artifact file lists."""

import hashlib
import json
from pathlib import Path


class ArtifactVerificationError(ValueError):
    """Raised when an artifact lock or one of its files is invalid."""


def _resolve_file(repository_root, relative_path):
    if not isinstance(relative_path, str) or not relative_path:
        raise ArtifactVerificationError('artifact file path must be text')
    relative = Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ArtifactVerificationError('artifact file escapes repository root')
    root = Path(repository_root).resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise ArtifactVerificationError('artifact files cannot be symlinks')
    path = candidate.resolve()
    if root not in path.parents:
        raise ArtifactVerificationError('artifact file escapes repository root')
    if path.is_symlink() or not path.is_file():
        raise ArtifactVerificationError(
            f'artifact file is missing or unsupported: {relative_path}'
        )
    return path


def compute_artifact_hash(repository_root, files):
    """Return the canonical ``sha256-file-list-v1`` digest."""
    if not isinstance(files, list) or not files:
        raise ArtifactVerificationError('artifact files must be a non-empty list')
    if len(files) != len(set(files)):
        raise ArtifactVerificationError('artifact files must be unique')
    lines = []
    for relative_path in files:
        path = _resolve_file(repository_root, relative_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f'{digest}  {relative_path}\n')
    return hashlib.sha256(''.join(lines).encode('utf-8')).hexdigest()


def verify_artifact_lock(repository_root, name, version, expected_hash):
    """Validate one lock and return its verified content."""
    lock_path = (
        Path(repository_root).resolve() /
        'artifacts' / name / f'{version}.json'
    )
    try:
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exception:
        raise ArtifactVerificationError(
            f'cannot load artifact lock: {lock_path}'
        ) from exception
    if lock.get('schema_version') != 1:
        raise ArtifactVerificationError('unsupported artifact lock schema')
    if lock.get('name') != name or lock.get('version') != version:
        raise ArtifactVerificationError('artifact lock identity mismatch')
    if lock.get('hash_algorithm') != 'sha256-file-list-v1':
        raise ArtifactVerificationError('unsupported artifact hash algorithm')
    if lock.get('artifact_hash') != expected_hash:
        raise ArtifactVerificationError('artifact lock hash mismatch')
    actual_hash = compute_artifact_hash(repository_root, lock.get('files'))
    if actual_hash != expected_hash:
        raise ArtifactVerificationError(
            f'artifact content hash mismatch: {actual_hash}'
        )
    return lock
