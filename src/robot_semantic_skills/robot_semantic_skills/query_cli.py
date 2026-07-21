"""Machine-only CLI for one bounded semantic map query."""

import argparse
import json

from .query import query_semantic_target, SemanticQueryInputError


EXIT_CODES = {
    'found': 0,
    'not_found': 3,
    'unavailable': 4,
    'invalid': 5,
}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Query one canonical target from an explicit map file.'
    )
    parser.add_argument('--store-file', required=True)
    parser.add_argument('--map-profile', required=True)
    parser.add_argument('--target-id', required=True)
    return parser.parse_args(argv)


def main(argv=None):
    """Print exactly one JSON result for a fixed Runtime adapter."""
    options = _parse_args(argv)
    try:
        result = query_semantic_target(
            options.store_file,
            options.map_profile,
            options.target_id,
        )
    except SemanticQueryInputError as exception:
        result = {
            'schema_version': 1,
            'skill': 'query_semantic_target',
            'skill_version': '0.1.0',
            'state': 'invalid',
            'query': {
                'map_profile': str(options.map_profile),
                'target_id': str(options.target_id),
            },
            'source': {
                'store_profile': str(options.map_profile),
                'content_sha256': None,
                'frame_id': None,
                'updated_at': '',
            },
            'found': False,
            'landmark': None,
            'reasons': [str(exception)],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_CODES[result['state']]


if __name__ == '__main__':
    raise SystemExit(main())
