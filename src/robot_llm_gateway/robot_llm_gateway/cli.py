"""Command-line entry point for plan-only MiMo task planning."""

import argparse
import json
import os
from pathlib import Path
import sys

from ament_index_python.packages import get_package_share_directory

from robot_llm_gateway.contracts import ContractError
from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import FakeProvider, MimoProvider, ProviderError


def _parser():
    """Create the bounded planner CLI parser."""
    parser = argparse.ArgumentParser(
        description='Generate a validated read-only robot plan; execute nothing.',
    )
    parser.add_argument('--task', required=True)
    parser.add_argument('--request-id', default='plan_cli_001')
    parser.add_argument(
        '--provider',
        choices=['xiaomi_mimo', 'fake'],
        default='xiaomi_mimo',
    )
    parser.add_argument('--model')
    parser.add_argument('--prompt-version', default='0.2.0')
    parser.add_argument('--max-output-tokens', type=int, default=1024)
    parser.add_argument('--timeout-sec', type=float, default=60.0)
    parser.add_argument('--output')
    parser.add_argument('--share-dir')
    return parser


def _fake_plan(prompt):
    """Build the deterministic health-check plan used only by offline tests."""
    skill = prompt.definition['allowed_skills'][0]
    return {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Check current robot health using read-only evidence.',
        'steps': [{
            'step_id': 1,
            'skill_name': skill['name'],
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': {},
            'reason': 'Safety state must be observed before later decisions.',
            'expected_evidence': ['Typed robot health result'],
        }],
        'clarification': None,
    }


def main(argv=None):
    """Generate and print one normalized plan-only gateway result."""
    args = _parser().parse_args(argv)
    share_dir = Path(
        args.share_dir or get_package_share_directory('robot_llm_gateway')
    )
    try:
        registry = PromptRegistry(
            share_dir / 'prompts',
            share_dir / 'schemas',
        )
        prompt = registry.resolve(
            'robot_task_planner',
            args.prompt_version,
        )
        if args.provider == 'fake':
            provider = FakeProvider(_fake_plan(prompt))
            model = args.model or 'fake-planner-v1'
        else:
            provider = MimoProvider.from_environment()
            model = args.model or os.environ.get(
                'MIMO_MODEL',
                MimoProvider.default_model,
            )
        request = build_plan_request(
            request_id=args.request_id,
            provider=args.provider,
            model=model,
            prompt=prompt,
            user_request=args.task,
            max_output_tokens=args.max_output_tokens,
            timeout_sec=args.timeout_sec,
        )
        result = LlmGateway(
            provider,
            registry,
            share_dir / 'schemas',
        ).plan(request)
    except (ContractError, ProviderError, OSError) as exc:
        print(json.dumps({
            'schema_version': 1,
            'state': 'failed',
            'error': {
                'code': 'gateway_configuration',
                'message': str(exc)[:1000],
            },
        }, ensure_ascii=False, indent=2))
        return 3
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).expanduser().write_text(
            f'{text}\n',
            encoding='utf-8',
        )
    print(text)
    return 0 if result['state'] == 'succeeded' else 3


if __name__ == '__main__':
    sys.exit(main())
