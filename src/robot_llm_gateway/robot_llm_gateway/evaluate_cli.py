"""CLI for resumable Xiaomi MiMo Prompt evaluation."""

import argparse
import json
import os
from pathlib import Path
import sys

from ament_index_python.packages import get_package_share_directory

from robot_llm_gateway.contracts import ContractError
from robot_llm_gateway.evaluation import (
    EvaluationError,
    load_evaluation_manifest,
    run_evaluation,
)
from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import FakeProvider, MimoProvider, ProviderError


def _parser():
    """Create the bounded evaluation CLI parser."""
    parser = argparse.ArgumentParser(
        description='Evaluate one pinned robot planner Prompt sequentially.',
    )
    parser.add_argument('--manifest')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--evaluation-id', default='mimo_planner_eval_v1')
    parser.add_argument(
        '--provider',
        choices=['xiaomi_mimo', 'fake'],
        default='xiaomi_mimo',
    )
    parser.add_argument('--model')
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--max-cases', type=int)
    parser.add_argument('--no-resume', action='store_true')
    parser.add_argument('--continue-on-error', action='store_true')
    parser.add_argument('--max-output-tokens', type=int, default=1024)
    parser.add_argument('--timeout-sec', type=float, default=60.0)
    parser.add_argument('--share-dir')
    return parser


def _oracle_plan(prompt, case):
    """Build deterministic expected output for offline evaluator tests."""
    expected = case['expected']
    catalog = {
        skill['name']: skill
        for skill in prompt.definition['allowed_skills']
    }
    steps = []
    for index, skill_name in enumerate(expected['required_skills'], start=1):
        skill = catalog[skill_name]
        steps.append({
            'step_id': index,
            'skill_name': skill['name'],
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': dict(case.get('context') or {}),
            'reason': 'Deterministic offline evaluation oracle.',
            'expected_evidence': ['Typed read-only Skill result'],
        })
    return {
        'schema_version': 1,
        'decision': expected['decision'],
        'summary': 'Deterministic offline evaluation response.',
        'steps': steps,
        'clarification': (
            'Please provide the missing target.'
            if expected['decision'] == 'clarify' else None
        ),
    }


def main(argv=None):
    """Run selected evaluation cases and print their aggregate summary."""
    args = _parser().parse_args(argv)
    share_dir = Path(
        args.share_dir or get_package_share_directory('robot_llm_gateway')
    )
    manifest_path = Path(
        args.manifest or (
            share_dir /
            'prompts/robot_task_planner/evals/0.1.0.json'
        )
    ).expanduser()
    try:
        manifest = load_evaluation_manifest(
            manifest_path,
            share_dir / 'schemas',
        )
        registry = PromptRegistry(
            share_dir / 'prompts',
            share_dir / 'schemas',
        )
        prompt = registry.resolve(
            manifest['prompt_id'],
            manifest['prompt_version'],
            manifest['prompt_sha256'],
        )
        if args.provider == 'fake':
            model = args.model or 'fake-planner-v1'
            shared_gateway = None
        else:
            model = args.model or os.environ.get(
                'MIMO_MODEL',
                MimoProvider.default_model,
            )
            shared_gateway = LlmGateway(
                MimoProvider.from_environment(),
                registry,
                share_dir / 'schemas',
            )

        def plan_case(case, request_id):
            """Call the selected provider once for an evaluation case."""
            if args.provider == 'fake':
                gateway = LlmGateway(
                    FakeProvider(_oracle_plan(prompt, case)),
                    registry,
                    share_dir / 'schemas',
                )
            else:
                gateway = shared_gateway
            request = build_plan_request(
                request_id=request_id,
                provider=args.provider,
                model=model,
                prompt=prompt,
                user_request=case['user_request'],
                context=case.get('context'),
                max_output_tokens=args.max_output_tokens,
                timeout_sec=args.timeout_sec,
            )
            return gateway.plan(request)

        summary, _ = run_evaluation(
            manifest=manifest,
            evaluation_id=args.evaluation_id,
            provider=args.provider,
            model=model,
            output_dir=args.output_dir,
            plan_case=plan_case,
            schema_dir=share_dir / 'schemas',
            case_ids=args.case_id,
            max_cases=args.max_cases,
            resume=not args.no_resume,
            fail_fast=not args.continue_on_error,
        )
    except (ContractError, EvaluationError, ProviderError, OSError) as exc:
        print(json.dumps({
            'schema_version': 1,
            'state': 'failed',
            'error': str(exc)[:1000],
        }, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if summary['status'] != 'complete' or summary['counts']['errors']:
        return 3
    if summary['counts']['failed']:
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
