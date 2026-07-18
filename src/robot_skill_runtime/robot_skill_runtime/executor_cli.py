"""CLI for one explicit Registry-gated Skill invocation."""

import argparse
import json
from pathlib import Path
import sys

from .executor import (
    ExecutionPolicyError,
    SkillExecutor,
    SkillRuntimeError,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Execute one exact ACTIVE Skill through the safe runtime.'
    )
    parser.add_argument(
        '--db', default='~/.ros/robot_agent/registry.db',
    )
    parser.add_argument(
        '--repository-root', default='~/robot_agent_ws',
    )
    parser.add_argument(
        '--trace-dir', default='~/.ros/robot_agent/traces',
    )
    parser.add_argument(
        '--trusted-public-key',
        default='~/.ros/robot_agent/keys/release_ed25519.pub.pem',
    )
    parser.add_argument('--invocation', required=True)
    parser.add_argument('--use-sim-time', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    """Load one invocation, execute it, and print the typed result."""
    args = _parse_args(argv)
    try:
        invocation = json.loads(
            Path(args.invocation).expanduser().read_text(encoding='utf-8')
        )
        executor = SkillExecutor(
            Path(args.db).expanduser(),
            Path(args.repository_root).expanduser(),
            Path(args.trace_dir).expanduser(),
            use_sim_time=args.use_sim_time,
            trusted_public_key=Path(args.trusted_public_key).expanduser(),
        )
        result = executor.execute(invocation)
    except (
        OSError,
        json.JSONDecodeError,
        ExecutionPolicyError,
        SkillRuntimeError,
    ) as exception:
        print(f'RUNTIME ERROR: {exception}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result['status'] == 'succeeded' else 3


if __name__ == '__main__':
    raise SystemExit(main())
