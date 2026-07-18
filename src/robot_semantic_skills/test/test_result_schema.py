"""Machine contract tests for semantic query results."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from robot_semantic_skills import query_semantic_target


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_found_and_not_found_results_match_schema(tmp_path):
    """Both positive and negative query outcomes remain machine-readable."""
    store = tmp_path / 'semantic_map.json'
    store.write_text(json.dumps({
        'schema_version': 1,
        'frame_id': 'map',
        'updated_at': 'timestamp',
        'landmarks': {
            'green_box': {
                'target_id': 'green_box',
                'observations_total': 1,
                'accepted_observations': 1,
                'rejected_observations': 0,
                'mean_position_m': {'x': 1.0, 'y': 2.0, 'z': 0.5},
                'position_stddev_m': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'last_observation_stamp_ns': 123,
                'last_wall_timestamp': 'timestamp',
                'last_evidence': {},
            },
        },
    }), encoding='utf-8')
    schema = json.loads((
        REPOSITORY_ROOT /
        'skills/query_semantic_target/schemas/'
        'semantic_target_query_result.schema.json'
    ).read_text(encoding='utf-8'))
    validator = Draft202012Validator(schema)

    for target in ('green_box', 'blue_cylinder'):
        result = query_semantic_target(
            store, 'semantic_landmarks_v1', target,
        )
        validator.validate(result)
