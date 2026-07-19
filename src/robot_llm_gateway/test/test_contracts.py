"""Tests for canonical LLM gateway contracts."""

import json
from pathlib import Path

from robot_llm_gateway.contracts import (
    canonical_json,
    load_schema,
    sha256_json,
    validate_instance,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_canonical_json_and_hash_ignore_mapping_order():
    """Equivalent objects retain one stable request identity."""
    first = {'b': 2, 'a': {'y': 1, 'x': 0}}
    second = {'a': {'x': 0, 'y': 1}, 'b': 2}
    assert canonical_json(first) == canonical_json(second)
    assert sha256_json(first) == sha256_json(second)
    assert len(sha256_json(first)) == 64


def test_frozen_mimo_request_matches_public_contract():
    """The checked-in real-provider request remains schema-valid."""
    request = json.loads((
        REPOSITORY_ROOT / 'examples/mimo_plan_request_v1.json'
    ).read_text(encoding='utf-8'))
    schema = load_schema(
        REPOSITORY_ROOT / 'schemas',
        'llm_plan_request.schema.json',
    )
    validate_instance(request, schema, 'example request')
