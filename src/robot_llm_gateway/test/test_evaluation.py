"""Tests for resumable deterministic Prompt evaluation."""

import csv
import json
from pathlib import Path

from robot_llm_gateway.evaluate_cli import main
from robot_llm_gateway.evaluation import (
    load_evaluation_manifest,
    run_evaluation,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPOSITORY_ROOT / 'prompts/robot_task_planner/evals/0.1.0.json'
)


def test_frozen_manifest_is_valid_and_semantically_bounded():
    """The six cases satisfy the machine contract and subset rules."""
    manifest = load_evaluation_manifest(
        MANIFEST_PATH,
        REPOSITORY_ROOT / 'schemas',
    )
    assert len(manifest['cases']) == 6
    assert manifest['cases'][4]['expected']['decision'] == 'refuse'


def test_fake_cli_scores_all_cases_and_resumes_without_calls(tmp_path, capsys):
    """Offline oracle obtains perfect metrics and reuses persisted results."""
    arguments = [
        '--provider', 'fake',
        '--output-dir', str(tmp_path),
        '--evaluation-id', 'fake_eval_001',
        '--share-dir', str(REPOSITORY_ROOT),
    ]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['status'] == 'complete'
    assert first['counts'] == {
        'selected': 6,
        'completed': 6,
        'passed': 6,
        'failed': 0,
        'errors': 0,
        'reused': 0,
    }
    assert first['metrics'] == {
        'schema_success_rate': 1.0,
        'decision_accuracy': 1.0,
        'skill_policy_accuracy': 1.0,
        'injection_refusal_rate': 1.0,
    }
    assert first['runtime']['total_tokens'] == 180
    with (tmp_path / 'sample_results.csv').open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert {row['status'] for row in rows} == {'PASS'}

    assert main(arguments) == 0
    second = json.loads(capsys.readouterr().out)
    assert second['counts']['reused'] == 6
    assert second['runtime'] == first['runtime']


def test_provider_failure_stops_after_first_paid_case(tmp_path):
    """Fail-fast prevents repeated calls after one provider error."""
    manifest = load_evaluation_manifest(
        MANIFEST_PATH,
        REPOSITORY_ROOT / 'schemas',
    )
    calls = []

    def failed_plan(case, request_id):
        """Return one valid normalized provider failure."""
        calls.append(case['case_id'])
        return {
            'schema_version': 1,
            'request_id': request_id,
            'provider': 'fake',
            'model': 'fake-planner-v1',
            'prompt_id': manifest['prompt_id'],
            'prompt_version': manifest['prompt_version'],
            'prompt_sha256': manifest['prompt_sha256'],
            'request_sha256': '0' * 64,
            'state': 'failed',
            'plan': None,
            'error': {
                'code': 'provider_unavailable',
                'message': 'offline test failure',
            },
            'runtime': {
                'latency_ms': 1.0,
                'provider_request_id': None,
                'usage': {
                    'input_tokens': None,
                    'output_tokens': None,
                    'total_tokens': None,
                },
            },
        }

    summary, rows = run_evaluation(
        manifest=manifest,
        evaluation_id='failure_eval_001',
        provider='fake',
        model='fake-planner-v1',
        output_dir=tmp_path,
        plan_case=failed_plan,
        schema_dir=REPOSITORY_ROOT / 'schemas',
    )
    assert calls == ['health_read_only']
    assert len(rows) == 1
    assert rows[0]['status'] == 'ERROR'
    assert summary['status'] == 'partial'
    assert summary['counts']['errors'] == 1


def test_case_selection_limits_calls_and_summary_scope(tmp_path, capsys):
    """Operators may run a cheap subset before the complete paid suite."""
    return_code = main([
        '--provider', 'fake',
        '--output-dir', str(tmp_path),
        '--evaluation-id', 'subset_eval_001',
        '--case-id', 'prompt_injection_shell',
        '--share-dir', str(REPOSITORY_ROOT),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert return_code == 0
    assert summary['counts']['selected'] == 1
    assert summary['metrics']['injection_refusal_rate'] == 1.0
