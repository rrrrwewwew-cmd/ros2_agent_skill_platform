"""CLI for one bounded plan-and-execute read-only Agent run."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from ament_index_python.packages import get_package_share_directory

from robot_agent_orchestrator.loop import AgentLoopError, ReadOnlyAgentLoop
from robot_llm_gateway.contracts import ContractError
from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import (
    FakeProvider,
    MimoProvider,
    ProviderError,
)
from robot_skill_runtime import (
    ExecutionPolicyError,
    SkillExecutor,
    SkillRuntimeError,
)


def _parser():
    """Build the explicit bounded Agent CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            'Plan and execute read-only governed robot Skills sequentially.'
        ),
    )
    parser.add_argument('--task', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--trace-id')
    parser.add_argument(
        '--provider',
        choices=['xiaomi_mimo', 'fake'],
        default='xiaomi_mimo',
    )
    parser.add_argument('--model')
    parser.add_argument('--prompt-version', default='0.2.0')
    parser.add_argument('--goal-x', type=float)
    parser.add_argument('--goal-y', type=float)
    parser.add_argument('--goal-yaw-deg', type=float)
    parser.add_argument(
        '--keepout-profile',
        default='rbot_water_puddle_v2',
    )
    parser.add_argument('--max-output-tokens', type=int, default=1024)
    parser.add_argument('--timeout-sec', type=float, default=60.0)
    parser.add_argument('--max-steps', type=int, default=6)
    parser.add_argument(
        '--db',
        default='~/.ros/robot_agent/registry.db',
    )
    parser.add_argument(
        '--repository-root',
        default='~/robot_agent_ws',
    )
    parser.add_argument(
        '--trace-dir',
        default='~/.ros/robot_agent/traces',
    )
    parser.add_argument(
        '--trusted-public-key',
        default='~/.ros/robot_agent/keys/release_ed25519.pub.pem',
    )
    parser.add_argument('--use-sim-time', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--gateway-share-dir')
    parser.add_argument('--orchestrator-share-dir')
    return parser


def _context(args):
    """Return an optional exact route context or reject partial coordinates."""
    coordinates = [args.goal_x, args.goal_y, args.goal_yaw_deg]
    if all(value is None for value in coordinates):
        return None
    if any(value is None for value in coordinates):
        raise AgentLoopError(
            'goal-x, goal-y, and goal-yaw-deg must be provided together'
        )
    return {
        'goal_x': args.goal_x,
        'goal_y': args.goal_y,
        'goal_yaw_deg': args.goal_yaw_deg,
        'keepout_profile': args.keepout_profile,
    }


def _fake_plan(prompt, context):
    """Return one deterministic plan for installed offline smoke tests."""
    catalog = {
        item['name']: item
        for item in prompt.definition['allowed_skills']
    }
    skill_names = ['check_robot_health']
    if context is not None:
        skill_names.append('preview_safe_route')
    steps = []
    for index, name in enumerate(skill_names, start=1):
        skill = catalog[name]
        steps.append({
            'step_id': index,
            'skill_name': name,
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': context if name == 'preview_safe_route' else {},
            'reason': 'Deterministic offline Agent Loop smoke plan.',
            'expected_evidence': ['typed read-only Skill result'],
        })
    return {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Execute a deterministic bounded read-only smoke plan.',
        'steps': steps,
        'clarification': None,
    }


def main(argv=None):
    """Run one Agent Loop and print its complete structured evidence."""
    args = _parser().parse_args(argv)
    identifier = uuid.uuid4().hex[:16]
    run_id = args.run_id or f'agent_{identifier}'
    trace_id = args.trace_id or f'trace_{identifier}'
    gateway_share = Path(
        args.gateway_share_dir or
        get_package_share_directory('robot_llm_gateway')
    )
    orchestrator_share = Path(
        args.orchestrator_share_dir or
        get_package_share_directory('robot_agent_orchestrator')
    )
    try:
        context = _context(args)
        registry = PromptRegistry(
            gateway_share / 'prompts',
            gateway_share / 'schemas',
        )
        prompt = registry.resolve(
            'robot_task_planner',
            args.prompt_version,
        )
        if args.provider == 'fake':
            provider = FakeProvider(_fake_plan(prompt, context))
            model = args.model or 'fake-planner-v1'
        else:
            provider = MimoProvider.from_environment()
            model = args.model or os.environ.get(
                'MIMO_MODEL',
                MimoProvider.default_model,
            )
        gateway = LlmGateway(
            provider,
            registry,
            gateway_share / 'schemas',
        )
        plan_request = build_plan_request(
            request_id=f'{run_id}.plan',
            provider=args.provider,
            model=model,
            prompt=prompt,
            user_request=args.task,
            context=context,
            max_output_tokens=args.max_output_tokens,
            timeout_sec=args.timeout_sec,
        )
        repository_root = Path(args.repository_root).expanduser()
        trace_directory = Path(args.trace_dir).expanduser()
        executor = SkillExecutor(
            Path(args.db).expanduser(),
            repository_root,
            trace_directory,
            use_sim_time=args.use_sim_time,
            trusted_public_key=Path(
                args.trusted_public_key
            ).expanduser(),
        )
        loop = ReadOnlyAgentLoop(
            database_path=Path(args.db).expanduser(),
            trace_directory=trace_directory,
            schema_directory=orchestrator_share / 'schemas',
            gateway=gateway,
            prompt=prompt,
            skill_executor=executor,
            max_steps=args.max_steps,
        )
        result = loop.run(run_id, trace_id, plan_request)
    except (
        AgentLoopError,
        ContractError,
        ExecutionPolicyError,
        ProviderError,
        SkillRuntimeError,
        OSError,
    ) as exc:
        print(json.dumps({
            'schema_version': 1,
            'state': 'failed',
            'error': str(exc)[:1000],
        }, ensure_ascii=False, indent=2))
        return 3
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).expanduser().write_text(
            f'{text}\n',
            encoding='utf-8',
        )
    print(text)
    if result['status'] == 'succeeded':
        return 0
    if result['status'] == 'failed':
        return 3
    return 4


if __name__ == '__main__':
    sys.exit(main())
