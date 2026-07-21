"""CLI for the reproducible Project 2 final policy evaluation."""

import argparse
import json
import sys

from .final_evaluation import run_final_evaluation


def main(argv=None):
    """Run frozen suites and return nonzero unless every hard gate passes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', default='~/robot_agent_ws')
    parser.add_argument(
        '--output-dir',
        default='~/.ros/robot_agent/final_evaluation_v1',
    )
    args = parser.parse_args(argv)
    try:
        result = run_final_evaluation(
            args.repository_root,
            args.output_dir,
        )
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({
            'schema_version': 1,
            'status': 'failed',
            'error': str(error)[:1000],
        }, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result['status'] == 'passed' else 4


if __name__ == '__main__':
    sys.exit(main())
