"""Read one project-one semantic landmark through a strict data contract."""

import hashlib
import json
import math
from pathlib import Path
import re


SKILL_NAME = 'query_semantic_target'
SKILL_VERSION = '0.1.0'
ALLOWED_MAP_PROFILES = {
    'semantic_landmarks_v1',
    'rbot_water_puddle_v2',
}
TARGET_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
AXES = ('x', 'y', 'z')


class SemanticQueryInputError(ValueError):
    """Raised when a caller tries to expand the bounded query surface."""


class _StoreContractError(ValueError):
    """Raised internally for malformed project-one semantic map data."""


def _require_nonnegative_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _StoreContractError(f'{field} must be a non-negative integer')
    return value


def _vector(record, field, nonnegative=False):
    mapping = record.get(field)
    if not isinstance(mapping, dict) or set(mapping) != set(AXES):
        raise _StoreContractError(f'{field} must contain exactly x, y, and z')
    result = {}
    for axis in AXES:
        value = mapping[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _StoreContractError(f'{field}.{axis} must be numeric')
        number = float(value)
        if not math.isfinite(number) or (nonnegative and number < 0.0):
            raise _StoreContractError(f'{field}.{axis} is invalid')
        result[axis] = number
    return result


def _optional_number(evidence, field, minimum=None, maximum=None):
    value = evidence.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _StoreContractError(f'last_evidence.{field} must be numeric')
    number = float(value)
    if not math.isfinite(number):
        raise _StoreContractError(f'last_evidence.{field} must be finite')
    if minimum is not None and number < minimum:
        raise _StoreContractError(f'last_evidence.{field} is below minimum')
    if maximum is not None and number > maximum:
        raise _StoreContractError(f'last_evidence.{field} is above maximum')
    return number


def _normalize_evidence(record):
    evidence = record.get('last_evidence', {})
    if not isinstance(evidence, dict):
        raise _StoreContractError('last_evidence must be an object')
    backend = evidence.get('perception_backend')
    if backend is not None and not isinstance(backend, str):
        raise _StoreContractError(
            'last_evidence.perception_backend must be text'
        )
    request_count = evidence.get('service_request_count')
    if request_count is not None:
        request_count = _require_nonnegative_integer(
            request_count, 'last_evidence.service_request_count',
        )
    return {
        'perception_backend': backend,
        'model_score': _optional_number(
            evidence, 'model_score', minimum=0.0, maximum=1.0,
        ),
        'verified_score': _optional_number(
            evidence, 'verified_score', minimum=0.0, maximum=1.0,
        ),
        'service_request_count': request_count,
        'inference_ms': _optional_number(
            evidence, 'inference_ms', minimum=0.0,
        ),
    }


def _source(profile, content_hash=None, frame_id=None, updated_at=''):
    return {
        'store_profile': profile,
        'content_sha256': content_hash,
        'frame_id': frame_id,
        'updated_at': updated_at,
    }


def _result(profile, target_id, state, source, landmark=None, reasons=None):
    return {
        'schema_version': 1,
        'skill': SKILL_NAME,
        'skill_version': SKILL_VERSION,
        'state': state,
        'query': {
            'map_profile': profile,
            'target_id': target_id,
        },
        'source': source,
        'found': state == 'found',
        'landmark': landmark,
        'reasons': list(reasons or []),
    }


def _validate_inputs(map_profile, target_id):
    profile = str(map_profile).strip()
    target = str(target_id).strip()
    if profile not in ALLOWED_MAP_PROFILES:
        raise SemanticQueryInputError('map_profile is not approved')
    if not TARGET_PATTERN.fullmatch(target):
        raise SemanticQueryInputError('target_id must be a canonical id')
    return profile, target


def _read_document(store_file):
    path = Path(store_file).expanduser()
    content = path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exception:
        raise _StoreContractError('semantic map is not valid UTF-8 JSON') from exception
    if not isinstance(document, dict):
        raise _StoreContractError('semantic map root must be an object')
    if document.get('schema_version') != 1:
        raise _StoreContractError('semantic map schema_version is unsupported')
    frame_id = document.get('frame_id')
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise _StoreContractError('semantic map frame_id is missing')
    updated_at = document.get('updated_at', '')
    if not isinstance(updated_at, str):
        raise _StoreContractError('semantic map updated_at must be text')
    landmarks = document.get('landmarks')
    if not isinstance(landmarks, dict):
        raise _StoreContractError('semantic map landmarks must be an object')
    return document, content_hash, frame_id.strip(), updated_at


def _normalize_landmark(record, target_id):
    if not isinstance(record, dict):
        raise _StoreContractError('landmark record must be an object')
    if record.get('target_id') != target_id:
        raise _StoreContractError('landmark target_id does not match its key')
    total = _require_nonnegative_integer(
        record.get('observations_total'), 'observations_total',
    )
    accepted = _require_nonnegative_integer(
        record.get('accepted_observations'), 'accepted_observations',
    )
    rejected = _require_nonnegative_integer(
        record.get('rejected_observations'), 'rejected_observations',
    )
    if total != accepted + rejected:
        raise _StoreContractError('observation counters are inconsistent')
    if accepted < 1:
        raise _StoreContractError('landmark has no accepted observation')
    stamp = _require_nonnegative_integer(
        record.get('last_observation_stamp_ns'),
        'last_observation_stamp_ns',
    )
    timestamp = record.get('last_wall_timestamp')
    if not isinstance(timestamp, str):
        raise _StoreContractError('last_wall_timestamp must be text')
    return {
        'target_id': target_id,
        'mean_position_m': _vector(record, 'mean_position_m'),
        'position_stddev_m': _vector(
            record, 'position_stddev_m', nonnegative=True,
        ),
        'observations': {
            'total': total,
            'accepted': accepted,
            'rejected': rejected,
        },
        'last_observation_stamp_ns': stamp,
        'last_wall_timestamp': timestamp,
        'last_evidence': _normalize_evidence(record),
    }


def query_semantic_target(store_file, map_profile, target_id):
    """Return one typed landmark result without modifying the source map."""
    profile, target = _validate_inputs(map_profile, target_id)
    try:
        document, content_hash, frame_id, updated_at = _read_document(
            store_file
        )
    except FileNotFoundError:
        return _result(
            profile,
            target,
            'unavailable',
            _source(profile),
            reasons=['approved semantic map file is unavailable'],
        )
    except OSError as exception:
        return _result(
            profile,
            target,
            'unavailable',
            _source(profile),
            reasons=[f'approved semantic map cannot be read: {exception}'],
        )
    except _StoreContractError as exception:
        return _result(
            profile,
            target,
            'invalid',
            _source(profile),
            reasons=[str(exception)],
        )

    source = _source(profile, content_hash, frame_id, updated_at)
    record = document['landmarks'].get(target)
    if record is None:
        return _result(
            profile,
            target,
            'not_found',
            source,
            reasons=['target has no accepted semantic map record'],
        )
    try:
        landmark = _normalize_landmark(record, target)
    except _StoreContractError as exception:
        return _result(
            profile,
            target,
            'invalid',
            source,
            reasons=[str(exception)],
        )
    return _result(profile, target, 'found', source, landmark=landmark)
