"""Record explicit human approval for one unchanged generated candidate."""

import argparse
import json
from pathlib import Path
import sys

from robot_skill_registry import SkillRegistry

from .contracts import sha256_file


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('--db', default='~/.ros/robot_agent/registry.db')
    return parser


def main(argv=None):
    """Verify the diff target and advance only to HUMAN_APPROVED."""
    args = _parser().parse_args(argv)
    try:
        result = json.loads(
            Path(args.result).expanduser().read_text(encoding='utf-8')
        )
        if result.get('status') != 'waiting_human_approval':
            raise ValueError('candidate is not waiting for approval')
        candidate = result['candidate']
        if candidate['artifact_hash'] != args.candidate_sha256:
            raise ValueError('candidate hash differs from reviewed hash')
        root = Path(candidate['root']).resolve()
        for relative, expected in candidate['source_files_sha256'].items():
            if sha256_file(root / relative) != expected:
                raise ValueError(f'candidate changed after review: {relative}')
        manifest = candidate['manifest']
        with SkillRegistry(args.db) as registry:
            record = registry.approve(
                manifest['name'],
                manifest['version'],
                candidate['artifact_hash'],
                args.actor,
                args.reason,
                decision='APPROVED',
            )
        output = {
            'schema_version': 1,
            'status': 'human_approved',
            'record': record,
            'next_required_gate': 'signed_release_and_adapter_review',
        }
        code = 0
    except (OSError, ValueError, KeyError) as error:
        output = {
            'schema_version': 1,
            'status': 'failed',
            'error': str(error)[:1000],
        }
        code = 3
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
