"""CLI for the frozen governed Skill Author evaluation."""

import argparse
import json
import sys

from .evaluation import run_author_evaluation


def main(argv=None):
    """Run ten requirements and return nonzero when a gate fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', default='~/robot_agent_ws')
    parser.add_argument(
        '--output-dir',
        default='~/.ros/robot_agent/skill_author_evaluation_v1',
    )
    args = parser.parse_args(argv)
    try:
        summary = run_author_evaluation(
            args.repository_root,
            args.output_dir,
        )
    except Exception as error:
        print(json.dumps({
            'schema_version': 1,
            'status': 'failed',
            'error': str(error)[:1000],
        }, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['status'] == 'passed' else 4


if __name__ == '__main__':
    sys.exit(main())
