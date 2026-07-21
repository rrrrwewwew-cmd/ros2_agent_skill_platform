"""Validate representative route preview results against the contract."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from robot_navigation_skills.preview import (
    normalize_request,
    preview_safe_route,
    unavailable_result,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    REPOSITORY_ROOT / 'skills/preview_safe_route/schemas/'
    'safe_route_preview_result.schema.json'
)


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def test_safe_and_unavailable_results_match_schema():
    """Both evidence-rich and fail-closed outcomes are typed."""
    request = normalize_request(4.5, 0.0, 0.0, 'rbot_water_puddle_v2')
    zone = {
        'target_id': 'water_puddle',
        'center_m': {'x': 1.67, 'y': 0.0},
        'radius_m': 0.6,
        'source_content_sha256': 'a' * 64,
        'source_updated_at': 'timestamp',
    }
    safe = preview_safe_route(
        request,
        [(0.0, 0.0), (1.67, 1.0), (4.5, 0.0)],
        zone,
        254,
        {
            'error_code': 0,
            'error_message': '',
            'planning_time_ms': 12.0,
            'path_frame': 'map',
            'observed_at_ns': 100,
        },
    )
    validator = Draft202012Validator(_schema())
    validator.validate(safe)
    validator.validate(unavailable_result(request, 'planner unavailable'))
