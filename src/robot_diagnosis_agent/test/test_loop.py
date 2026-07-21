"""Tests for the evidence-first diagnosis Agent Loop."""

from pathlib import Path

from robot_diagnosis_agent.contracts import TOOL_ORDER
from robot_diagnosis_agent.loop import DiagnosisAgentLoop
from robot_llm_gateway.contracts import sha256_json
from robot_llm_gateway.prompt_registry import PromptRegistry


ROOT = Path(__file__).resolve().parents[3]
RUN_ID = 'jitter_demo_001'


def _prompt():
    return PromptRegistry(
        ROOT / 'prompts',
        ROOT / 'schemas',
    ).resolve('experiment_diagnosis_planner', '0.1.0')


def _plan(run_id=RUN_ID):
    prompt = _prompt()
    catalog = {item['name']: item for item in prompt.definition['allowed_tools']}
    query = 'ROS 2 Jazzy 轨迹抖动与控制相关性如何形成机制假设？'
    inputs = (
        {},
        {'run_id': run_id},
        {'run_id': run_id},
        {'query': query, 'distribution': 'project2-v1', 'top_k': 3},
        {
            'run_id': run_id,
            'knowledge_queries': [{
                'query': query,
                'distribution': 'project2-v1',
            }],
        },
    )
    return {
        'schema_version': 1,
        'decision': 'plan',
        'run_id': run_id,
        'summary': 'Diagnose one verified run.',
        'steps': [
            {
                'step_id': number,
                'tool_name': name,
                'tool_version': catalog[name]['version'],
                'contract_sha256': catalog[name]['contract_sha256'],
                'inputs': arguments,
                'reason': 'Collect the next required evidence stage.',
                'expected_evidence': ['hash-bound evidence'],
            }
            for number, (name, arguments) in enumerate(
                zip(TOOL_ORDER, inputs),
                start=1,
            )
        ],
        'clarification': None,
    }


class _Gateway:
    def __init__(self, plan):
        self.plan_value = plan

    def plan(self, request):
        return {
            'state': 'succeeded',
            'plan': self.plan_value,
            'request_sha256': sha256_json(request),
        }


class _ToolClient:
    def __init__(self, include_run=True):
        self.calls = []
        self.include_run = include_run

    @staticmethod
    def _citation():
        return {
            'source_id': 'project2.agent_traces',
            'source_version': '1.0.0',
            'source_content_sha256': 'a' * 64,
            'chunk_sha256': 'b' * 64,
            'canonical_url': 'https://example.invalid/project2',
            'distribution': 'project2-v1',
        }

    def call_tool(self, name, arguments, timeout_sec=None):
        self.calls.append(name)
        source_hashes = {'pose': 'c' * 64, 'command': 'd' * 64}
        if name == 'list_experiment_runs':
            evidence = {
                'count': int(self.include_run),
                'runs': ([{'run_id': RUN_ID}] if self.include_run else []),
            }
        elif name == 'inspect_experiment_run':
            evidence = {
                'run_id': RUN_ID,
                'sources': [
                    {'name': key, 'sha256': value}
                    for key, value in source_hashes.items()
                ],
            }
        elif name == 'analyze_experiment_run':
            evidence = {
                'run_id': RUN_ID,
                'analysis_sha256': 'e' * 64,
                'source_hashes': source_hashes,
                'anomaly_windows': [{'start_ns': 1, 'end_ns': 2}],
                'candidate_mechanisms': [{'mechanism': 'tracking lag'}],
            }
        elif name == 'retrieve_robotics_knowledge':
            evidence = {
                'run_id': RUN_ID,
                'index_content_sha256': 'f' * 64,
                'abstained': False,
            }
        else:
            evidence = {
                'run_id': RUN_ID,
                'analysis_sha256': 'e' * 64,
                'bundle_sha256': '1' * 64,
                'artifact_directory': 'jitter/report',
                'artifact_hashes': {'report': '2' * 64},
            }
        citations = (
            [self._citation()]
            if name in {
                'retrieve_robotics_knowledge',
                'materialize_diagnosis_report',
            }
            else []
        )
        return {
            'schema_version': 1,
            'tool_name': name,
            'tool_version': '0.1.0',
            'safety_class': (
                'artifact_write'
                if name == 'materialize_diagnosis_report' else 'read_only'
            ),
            'input_sha256': sha256_json(arguments),
            'evidence_sha256': sha256_json(evidence),
            'evidence': evidence,
            'citations': citations,
        }


def _loop(tmp_path, client, plan=None):
    return DiagnosisAgentLoop(
        tmp_path / 'registry.db',
        tmp_path / 'traces',
        ROOT / 'schemas',
        _Gateway(plan or _plan()),
        _prompt(),
        client,
    )


def test_diagnosis_loop_runs_exact_sequence_and_never_claims_root_cause(
    tmp_path,
):
    client = _ToolClient()
    result = _loop(tmp_path, client).run(
        'diagnosis_test_001',
        'trace_diagnosis_test_001',
        {'request': 'diagnose'},
        RUN_ID,
    )
    assert result['status'] == 'succeeded'
    assert tuple(client.calls) == TOOL_ORDER
    assert result['conclusion']['root_cause_proven'] is False
    assert result['conclusion']['citation_count'] == 1
    assert all(step['evidence_gate_passed'] for step in result['steps'])


def test_missing_run_blocks_before_inspection(tmp_path):
    client = _ToolClient(include_run=False)
    result = _loop(tmp_path, client).run(
        'diagnosis_test_002',
        'trace_diagnosis_test_002',
        {'request': 'diagnose'},
        RUN_ID,
    )
    assert result['status'] == 'blocked_by_evidence'
    assert client.calls == ['list_experiment_runs']


def test_model_cannot_change_trusted_run_id(tmp_path):
    client = _ToolClient()
    result = _loop(tmp_path, client, _plan('other_run')).run(
        'diagnosis_test_003',
        'trace_diagnosis_test_003',
        {'request': 'diagnose'},
        RUN_ID,
    )
    assert result['status'] == 'failed'
    assert client.calls == []
