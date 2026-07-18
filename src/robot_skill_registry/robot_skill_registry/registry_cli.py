"""Command-line interface for governed Skills and persistent Agent runs."""

import argparse
import json
from pathlib import Path

import yaml

from .registry import (
    AgentRunStore,
    RegistryConflictError,
    RegistryContractError,
    RegistryNotFoundError,
    SkillRegistry,
)


def _json_object(value, field):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RegistryContractError(f'{field} must be valid JSON') from error
    if not isinstance(parsed, dict):
        raise RegistryContractError(f'{field} must be a JSON object')
    return parsed


def _print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_parser():
    parser = argparse.ArgumentParser(
        description='Manage governed Skill versions and bounded Agent runs.'
    )
    parser.add_argument('--db', required=True, help='SQLite registry path')
    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser('init')

    register = subparsers.add_parser('register')
    register.add_argument('--manifest', required=True)
    register.add_argument('--artifact-hash')
    register.add_argument('--actor', default='skill_author')

    show = subparsers.add_parser('show')
    show.add_argument('--name', required=True)
    show.add_argument('--version', required=True)

    events = subparsers.add_parser('skill-events')
    events.add_argument('--name', required=True)
    events.add_argument('--version', required=True)

    approvals = subparsers.add_parser('approvals')
    approvals.add_argument('--name', required=True)
    approvals.add_argument('--version', required=True)

    advance = subparsers.add_parser('advance')
    advance.add_argument('--name', required=True)
    advance.add_argument('--version', required=True)
    advance.add_argument('--to', required=True)
    advance.add_argument('--expected-state', required=True)
    advance.add_argument('--actor', required=True)
    advance.add_argument('--reason', required=True)

    approve = subparsers.add_parser('approve')
    approve.add_argument('--name', required=True)
    approve.add_argument('--version', required=True)
    approve.add_argument('--artifact-hash', required=True)
    approve.add_argument('--actor', required=True)
    approve.add_argument('--reason', required=True)
    approve.add_argument(
        '--decision',
        choices=['APPROVED', 'REJECTED'],
        default='APPROVED',
    )

    create_run = subparsers.add_parser('create-run')
    create_run.add_argument('--run-id', required=True)
    create_run.add_argument('--trace-id', required=True)
    create_run.add_argument('--request-json', required=True)
    create_run.add_argument('--actor', default='runtime')

    show_run = subparsers.add_parser('show-run')
    show_run.add_argument('--run-id', required=True)

    run_events = subparsers.add_parser('run-events')
    run_events.add_argument('--run-id', required=True)

    transition_run = subparsers.add_parser('transition-run')
    transition_run.add_argument('--run-id', required=True)
    transition_run.add_argument('--to', required=True)
    transition_run.add_argument('--expected-state', required=True)
    transition_run.add_argument('--actor', required=True)
    transition_run.add_argument('--reason', required=True)
    transition_run.add_argument('--plan-json')

    subparsers.add_parser('recover-runs').add_argument(
        '--actor',
        default='startup_recovery',
    )
    return parser


def _skill_command(args):
    with SkillRegistry(args.db) as registry:
        if args.command == 'init':
            return {'database': str(Path(args.db).expanduser()), 'initialized': True}
        if args.command == 'register':
            manifest = yaml.safe_load(
                Path(args.manifest).expanduser().read_text(encoding='utf-8')
            )
            return registry.register_manifest(
                manifest,
                artifact_hash=args.artifact_hash,
                actor=args.actor,
            )
        if args.command == 'show':
            return registry.get_skill(args.name, args.version)
        if args.command == 'skill-events':
            return registry.list_events(args.name, args.version)
        if args.command == 'approvals':
            return registry.list_approvals(args.name, args.version)
        if args.command == 'advance':
            return registry.advance(
                args.name,
                args.version,
                args.to,
                args.expected_state,
                args.actor,
                args.reason,
            )
        if args.command == 'approve':
            return registry.approve(
                args.name,
                args.version,
                args.artifact_hash,
                args.actor,
                args.reason,
                decision=args.decision,
            )
    raise RegistryContractError(f'unsupported command: {args.command}')


def _run_command(args):
    with AgentRunStore(args.db) as store:
        if args.command == 'create-run':
            return store.create_run(
                args.run_id,
                args.trace_id,
                _json_object(args.request_json, 'request-json'),
                actor=args.actor,
            )
        if args.command == 'show-run':
            return store.get_run(args.run_id)
        if args.command == 'run-events':
            return store.list_events(args.run_id)
        if args.command == 'transition-run':
            plan = (
                _json_object(args.plan_json, 'plan-json')
                if args.plan_json is not None else None
            )
            return store.transition(
                args.run_id,
                args.to,
                args.expected_state,
                args.actor,
                args.reason,
                plan=plan,
            )
        if args.command == 'recover-runs':
            return {'recovered_run_ids': store.fail_closed_recover(args.actor)}
    raise RegistryContractError(f'unsupported command: {args.command}')


def main(argv=None):
    """Run one explicit Registry or Agent state operation."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {
            'init', 'register', 'show', 'skill-events', 'approvals',
            'advance', 'approve',
        }:
            result = _skill_command(args)
        else:
            result = _run_command(args)
    except (
        OSError,
        yaml.YAMLError,
        RegistryConflictError,
        RegistryContractError,
        RegistryNotFoundError,
    ) as error:
        parser.exit(3, f'REGISTRY ERROR: {error}\n')
    _print_json(result)


if __name__ == '__main__':
    main()
