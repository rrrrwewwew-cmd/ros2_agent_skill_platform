"""CLI for one governed MiMo-to-MCP experiment diagnosis run."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from ament_index_python.packages import get_package_share_directory

from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import FakeProvider, MimoProvider

from .client import SubprocessMcpDiagnosisClient
from .contracts import TOOL_ORDER
from .loop import DiagnosisAgentLoop


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--experiment-run-id', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--trace-id')
    parser.add_argument(
        '--provider',
        choices=['xiaomi_mimo', 'fake'],
        default='xiaomi_mimo',
    )
    parser.add_argument('--model')
    parser.add_argument('--prompt-version', default='0.1.0')
    parser.add_argument('--distribution', default='project2-v1')
    parser.add_argument('--db', default='~/.ros/robot_agent/registry.db')
    parser.add_argument('--trace-dir', default='~/.ros/robot_agent/traces')
    parser.add_argument(
        '--experiment-root',
        default='~/robot_agent_ws/examples',
    )
    parser.add_argument(
        '--artifact-root',
        default='~/.ros/robot_agent/diagnosis_reports',
    )
    parser.add_argument(
        '--rag-index',
        default=(
            '~/.ros/robot_agent/rag/robotics_core_v2/'
            'bge_m3_v2_index.json'
        ),
    )
    parser.add_argument(
        '--mcp-python',
        default='~/robot_agent_mcp_env/bin/python',
    )
    parser.add_argument(
        '--rag-python',
        default='~/qwen_vl_env/bin/python',
    )
    parser.add_argument('--embedding-device', default='cuda')
    parser.add_argument('--hf-home', default='~/.cache/huggingface')
    parser.add_argument('--max-output-tokens', type=int, default=1536)
    parser.add_argument('--planner-timeout-sec', type=float, default=60.0)
    parser.add_argument('--tool-timeout-sec', type=float, default=120.0)
    parser.add_argument('--max-duration-sec', type=float, default=300.0)
    parser.add_argument('--output')
    parser.add_argument('--repository-root', default='~/robot_agent_ws')
    parser.add_argument('--gateway-share-dir')
    parser.add_argument('--diagnosis-share-dir')
    parser.add_argument('--mcp-share-dir')
    return parser


def _fake_plan(prompt, experiment_run_id, distribution):
    catalog = {
        item['name']: item for item in prompt.definition['allowed_tools']
    }
    query = (
        'ROS 2 Jazzy 中如何根据轨迹抖动、控制指令相关性和 TF/里程计'
        '证据形成非因果机制假设？'
    )
    inputs = (
        {},
        {'run_id': experiment_run_id},
        {'run_id': experiment_run_id},
        {'query': query, 'distribution': distribution, 'top_k': 3},
        {
            'run_id': experiment_run_id,
            'knowledge_queries': [{
                'query': query,
                'distribution': distribution,
            }],
        },
    )
    steps = []
    for number, (name, step_inputs) in enumerate(
        zip(TOOL_ORDER, inputs),
        start=1,
    ):
        tool = catalog[name]
        steps.append({
            'step_id': number,
            'tool_name': name,
            'tool_version': tool['version'],
            'contract_sha256': tool['contract_sha256'],
            'inputs': step_inputs,
            'reason': 'Deterministic diagnosis Agent offline plan.',
            'expected_evidence': ['hash-bound structured evidence'],
        })
    return {
        'schema_version': 1,
        'decision': 'plan',
        'run_id': experiment_run_id,
        'summary': 'Run the five-stage evidence-first diagnosis workflow.',
        'steps': steps,
        'clarification': None,
    }


def _module_paths(repository_root):
    source_root = repository_root / 'src'
    return sorted(
        path.resolve() for path in source_root.iterdir() if path.is_dir()
    )


def main(argv=None):
    """Run one diagnosis Agent and retain structured result plus Trace."""
    args = _parser().parse_args(argv)
    token = uuid.uuid4().hex[:16]
    run_id = args.run_id or f'diagnosis_{token}'
    trace_id = args.trace_id or f'trace_diagnosis_{token}'
    gateway_share = Path(
        args.gateway_share_dir
        or get_package_share_directory('robot_llm_gateway')
    )
    diagnosis_share = Path(
        args.diagnosis_share_dir
        or get_package_share_directory('robot_diagnosis_agent')
    )
    mcp_share = Path(
        args.mcp_share_dir
        or get_package_share_directory('robot_diagnosis_mcp')
    )
    repository_root = Path(args.repository_root).expanduser().resolve()
    try:
        registry = PromptRegistry(
            gateway_share / 'prompts',
            gateway_share / 'schemas',
        )
        prompt = registry.resolve(
            'experiment_diagnosis_planner',
            args.prompt_version,
        )
        if args.provider == 'fake':
            provider = FakeProvider(_fake_plan(
                prompt,
                args.experiment_run_id,
                args.distribution,
            ))
            model = args.model or 'fake-diagnosis-planner-v1'
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
        request = build_plan_request(
            request_id=f'{run_id}.plan',
            provider=args.provider,
            model=model,
            prompt=prompt,
            user_request=args.task,
            context={
                'run_id': args.experiment_run_id,
                'distribution': args.distribution,
            },
            max_output_tokens=args.max_output_tokens,
            timeout_sec=args.planner_timeout_sec,
        )
        module_paths = _module_paths(repository_root)
        client = SubprocessMcpDiagnosisClient(
            args.mcp_python,
            args.experiment_root,
            args.artifact_root,
            args.rag_index,
            mcp_share / 'schemas',
            module_paths,
            rag_python=args.rag_python,
            rag_module_paths=[
                repository_root / 'src/robot_rag',
                Path('/usr/lib/python3/dist-packages'),
            ],
            embedding_device=args.embedding_device,
            hf_home=args.hf_home,
        )
        loop = DiagnosisAgentLoop(
            args.db,
            args.trace_dir,
            diagnosis_share / 'schemas',
            gateway,
            prompt,
            client,
            max_duration_sec=args.max_duration_sec,
            tool_timeout_sec=args.tool_timeout_sec,
        )
        result = loop.run(
            run_id,
            trace_id,
            request,
            args.experiment_run_id,
        )
    except Exception as error:
        result = {
            'schema_version': 1,
            'status': 'failed',
            'error': str(error)[:1000],
        }
        code = 3
    else:
        code = 0 if result['status'] == 'succeeded' else 4
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).expanduser().write_text(
            f'{text}\n',
            encoding='utf-8',
        )
    print(text)
    return code


if __name__ == '__main__':
    sys.exit(main())
