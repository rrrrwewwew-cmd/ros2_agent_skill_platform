"""Deterministic hashing, text normalization and schema helpers."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from jsonschema import Draft202012Validator, SchemaError, ValidationError


class RagError(RuntimeError):
    """Raised when a RAG artifact cannot be trusted or processed."""


_TOKEN_PATTERN = re.compile(
    r'[a-zA-Z0-9_./:-]+|[\u3400-\u4dbf\u4e00-\u9fff]+'
)
_CJK_PATTERN = re.compile(r'^[\u3400-\u4dbf\u4e00-\u9fff]+$')


def canonical_json(value):
    """Return stable UTF-8 JSON text for hashing and persisted artifacts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def sha256_bytes(value):
    """Return a lowercase SHA-256 digest for bytes."""
    return hashlib.sha256(value).hexdigest()


def sha256_text(value):
    """Return a lowercase SHA-256 digest for UTF-8 text."""
    return sha256_bytes(value.encode('utf-8'))


def canonical_sha256(value):
    """Hash a JSON-compatible value using canonical serialization."""
    return sha256_text(canonical_json(value))


def normalize_text(value):
    """Normalize Unicode and collapse whitespace without changing meaning."""
    normalized = unicodedata.normalize('NFKC', value).lower()
    return ' '.join(normalized.split())


def tokenize(value):
    """Tokenize bilingual ROS text into stable English and CJK features."""
    result = []
    for match in _TOKEN_PATTERN.finditer(normalize_text(value)):
        token = match.group(0)
        if not _CJK_PATTERN.match(token):
            result.append(token)
            continue
        result.append(token)
        if len(token) == 1:
            result.append('zh:' + token)
            continue
        result.extend(
            'zh:' + token[index:index + 2]
            for index in range(len(token) - 1)
        )
    return result


def feature_hash_vector(value, dimensions):
    """
    Create a deterministic normalized feature-hashing vector.

    This is an offline retrieval feature, not a learned semantic embedding.
    It combines bilingual tokens with character trigrams so CI and replay do
    not depend on a model download or an external API.
    """
    if dimensions < 64:
        raise RagError('feature hash dimensions must be at least 64')
    features = [('token:' + term, 1.0) for term in tokenize(value)]
    compact = ''.join(normalize_text(value).split())
    features.extend(
        ('char3:' + compact[index:index + 3], 0.35)
        for index in range(max(0, len(compact) - 2))
    )
    vector = [0.0] * dimensions
    for feature, weight in features:
        digest = hashlib.sha256(feature.encode('utf-8')).digest()
        bucket = int.from_bytes(digest[:4], 'big') % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(component * component for component in vector))
    if norm:
        vector = [round(component / norm, 10) for component in vector]
    return vector


def schema_directory(explicit=None):
    """Resolve repository or installed package schema directory."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    repository_candidate = Path(__file__).resolve().parents[3] / 'schemas'
    if repository_candidate.is_dir():
        return repository_candidate
    try:
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('robot_rag'))
    except (ImportError, LookupError) as error:
        raise RagError('robot_rag schema directory is unavailable') from error
    return share / 'schemas'


def validate_document(document, schema_name, schema_dir=None):
    """Validate a machine artifact against one named Draft 2020-12 schema."""
    path = schema_directory(schema_dir) / f'{schema_name}.schema.json'
    try:
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(document)
    except (
        OSError,
        json.JSONDecodeError,
        SchemaError,
        ValidationError,
    ) as error:
        raise RagError(f'cannot load schema {schema_name}: {error}') from error


def write_json(path, value):
    """Atomically write stable JSON, creating parent directories."""
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    )
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=output.parent,
            prefix=output.name + '.',
            suffix='.tmp',
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
