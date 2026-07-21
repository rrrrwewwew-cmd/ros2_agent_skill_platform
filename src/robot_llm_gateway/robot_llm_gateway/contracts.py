"""Canonical JSON, hashing, and local schema validation helpers."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


class ContractError(ValueError):
    """Report a bounded contract violation without exposing secrets."""


def canonical_json(value):
    """Return deterministic UTF-8 JSON text for hashing and transport."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )


def sha256_json(value):
    """Hash a JSON-compatible value using its canonical representation."""
    encoded = canonical_json(value).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def load_json(path):
    """Load one JSON object and fail with a path-bounded error."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f'cannot load JSON file {path.name}') from exc
    if not isinstance(value, dict):
        raise ContractError(f'{path.name} must contain a JSON object')
    return value


def load_schema(schema_dir, name):
    """Load a named repository schema from a trusted directory."""
    return load_json(Path(schema_dir) / name)


def validate_instance(instance, schema, label):
    """Validate an instance and report the first stable error location."""
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = '.'.join(str(item) for item in error.absolute_path) or '$'
    raise ContractError(f'{label} invalid at {location}: {error.message}')
