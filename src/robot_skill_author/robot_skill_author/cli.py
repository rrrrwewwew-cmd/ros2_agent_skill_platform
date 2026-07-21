"""CLI for RAG-assisted bounded ROS 2 Skill authoring."""

import argparse
import json
import os
from pathlib import Path
import sys

from ament_index_python.packages import get_package_share_directory

from robot_llm_gateway.gateway import LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import MimoProvider

from .contracts import RENDERER_HASH
from .generator import FixedDraftGenerator, GatewayDraftGenerator
from .pipeline import SkillAuthorPipeline
from .render import BoundedSkillRenderer
from .retriever import SubprocessRetriever
from .sandbox import CandidateSandbox


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument(
        '--provider',
        choices=['xiaomi_mimo', 'fake'],
        default='xiaomi_mimo',
    )
    parser.add_argument('--model')
    parser.add_argument('--prompt-version', default='0.1.0')
    parser.add_argument('--db', default='~/.ros/robot_agent/registry.db')
    parser.add_argument(
        '--candidate-root',
        default='~/.ros/robot_agent/skill_candidates',
    )
    parser.add_argument(
        '--rag-index',
        default=(
            '~/.ros/robot_agent/rag/robotics_core_v2/'
            'bge_m3_v2_index.json'
        ),
    )
    parser.add_argument('--rag-python', default='~/qwen_vl_env/bin/python')
    parser.add_argument('--embedding-device', default='cuda')
    parser.add_argument('--hf-home', default='~/.cache/huggingface')
    parser.add_argument('--max-repairs', type=int, default=2)
    parser.add_argument('--repository-root', default='~/robot_agent_ws')
    parser.add_argument('--gateway-share-dir')
    parser.add_argument('--author-share-dir')
    parser.add_argument('--output')
    return parser


def _fake_plan(request):
    dependencies = request['allowed_dependencies']
    controlled = request['safety_level'] == 'controlled'
    inputs = {}
    if any(name in dependencies for name in (
        'preview_safe_route', 'navigate_to_approved_pose',
    )):
        inputs = {
            'goal_x': {'type': 'number'},
            'goal_y': {'type': 'number'},
            'goal_yaw_deg': {'type': 'number'},
            'keepout_profile': {'type': 'string'},
        }
    scenarios = [
        {
            'name': 'success',
            'failed_step': None,
            'expected_state': 'succeeded',
        },
        {
            'name': 'dependency_failure',
            'failed_step': 1,
            'expected_state': 'aborted',
        },
        {
            'name': 'approval_boundary',
            'failed_step': None,
            'expected_state': (
                'waiting_approval' if controlled else 'succeeded'
            ),
        },
    ]
    draft = {
        'name': request['name'],
        'version': request['version'],
        'description': request['description'],
        'template_family': 'bounded_python_workflow_v1',
        'safety_level': request['safety_level'],
        'requires_human_approval': request['requires_human_approval'],
        'inputs': inputs,
        'dependency_steps': [
            {
                'step_id': index,
                'skill_name': name,
                'on_failure': 'abort',
            }
            for index, name in enumerate(dependencies, start=1)
        ],
        'preconditions': list(request['acceptance_criteria']),
        'effects': ['produce only evidence-gated governed Skill calls'],
        'test_scenarios': scenarios,
    }
    return {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Render one bounded workflow candidate.',
        'steps': [{
            'step_id': 1,
            'skill_name': 'render_bounded_ros2_skill',
            'skill_version': '0.1.0',
            'artifact_hash': RENDERER_HASH,
            'inputs': draft,
            'reason': 'Use deterministic source templates and safety gates.',
            'expected_evidence': [
                'RAG citations',
                'build and test hashes',
                'human diff approval',
            ],
        }],
        'clarification': None,
    }


def main(argv=None):
    """Generate and gate one candidate, stopping before human approval."""
    args = _parser().parse_args(argv)
    request = {}
    repository = Path(args.repository_root).expanduser().resolve()
    gateway_share = Path(
        args.gateway_share_dir
        or get_package_share_directory('robot_llm_gateway')
    )
    author_share = Path(
        args.author_share_dir
        or get_package_share_directory('robot_skill_author')
    )
    try:
        request = json.loads(
            Path(args.request).expanduser().read_text(encoding='utf-8')
        )
        prompt_registry = PromptRegistry(
            gateway_share / 'prompts',
            gateway_share / 'schemas',
        )
        prompt = prompt_registry.resolve(
            'skill_author_planner',
            args.prompt_version,
        )
        if args.provider == 'fake':
            generator = FixedDraftGenerator([_fake_plan(request)])
        else:
            provider = MimoProvider.from_environment()
            gateway = LlmGateway(
                provider,
                prompt_registry,
                gateway_share / 'schemas',
            )
            generator = GatewayDraftGenerator(
                gateway,
                prompt,
                args.provider,
                args.model or os.environ.get(
                    'MIMO_MODEL',
                    MimoProvider.default_model,
                ),
            )
        retriever = SubprocessRetriever(
            args.rag_python,
            args.rag_index,
            [repository / 'src/robot_rag'],
            embedding_device=args.embedding_device,
            hf_home=args.hf_home,
        )
        pipeline = SkillAuthorPipeline(
            author_share / 'schemas',
            args.db,
            retriever,
            generator,
            BoundedSkillRenderer(args.candidate_root),
            CandidateSandbox(),
            max_repairs=args.max_repairs,
        )
        result = pipeline.run(request)
    except Exception as error:
        result = {
            'schema_version': 1,
            'status': 'failed',
            'error': str(error)[:1000],
        }
        code = 3
    else:
        code = 0 if result['status'] == 'waiting_human_approval' else 4
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    output = args.output or (
        Path(args.candidate_root).expanduser()
        / request.get('request_id', 'invalid')
        / 'author_result.json'
    )
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f'{text}\n', encoding='utf-8')
    print(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
