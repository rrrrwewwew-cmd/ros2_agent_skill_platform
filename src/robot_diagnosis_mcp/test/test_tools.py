"""Tests for governed robot experiment diagnosis MCP tools."""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from robot_diagnosis_mcp import (
    DiagnosisToolError,
    DiagnosisToolService,
    SubprocessRagAdapter,
)
from robot_rag.util import canonical_sha256
from safe_agent_core.experiment_analytics import sha256_file


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_ROOT = REPOSITORY_ROOT / 'examples'
SCHEMA_DIRECTORY = REPOSITORY_ROOT / 'schemas'
RUN_ID = 'jitter_demo_001'


class _FakeRagAdapter:
    """Return one deterministic cited chunk without loading a model."""

    @staticmethod
    def query(query, distribution, top_k):
        citation = {
            'source_id': 'project2.experiment_diagnosis_contract',
            'source_version': 'test-version',
            'source_content_sha256': '1' * 64,
            'chunk_sha256': '2' * 64,
            'canonical_url': 'https://example.invalid/diagnosis',
            'distribution': distribution,
        }
        hit = {
            'rank': 1,
            'score': 0.9,
            'bm25_raw_score': 1.0,
            'bm25_score': 0.8,
            'embedding_score': 0.9,
            'chunk_id': 'project2.experiment_diagnosis_contract:000',
            'heading': 'Evidence boundary',
            'text': 'Correlation supports a hypothesis, not causal proof.',
            'citation': citation,
        }
        abstained = 'unsupported' in query
        return {
            'schema_version': 1,
            'query': query,
            'filters': {'distribution': distribution},
            'corpus_id': 'robotics_core',
            'corpus_version': 'test',
            'index_content_sha256': '3' * 64,
            'retrieval_config': {
                'algorithm': 'test',
                'embedding_provider': 'fake',
            },
            'abstained': abstained,
            'abstention_reason': (
                'no_candidate_above_threshold' if abstained else None
            ),
            'unsupported_identifiers': [],
            'hits': [] if abstained else [hit][:top_k],
        }


def _service(tmp_path, experiment_root=EXPERIMENT_ROOT):
    return DiagnosisToolService(
        experiment_root=experiment_root,
        artifact_root=tmp_path / 'artifacts',
        rag_adapter=_FakeRagAdapter(),
        schema_directory=SCHEMA_DIRECTORY,
    )


def test_list_and_inspect_return_hash_bound_envelopes(tmp_path):
    """Run discovery and inspection expose only verified typed evidence."""
    service = _service(tmp_path)
    listed = service.list_experiment_runs()
    assert listed['evidence']['count'] == 1
    assert listed['evidence']['runs'][0]['run_id'] == RUN_ID
    assert listed['evidence_sha256'] == canonical_sha256(listed['evidence'])

    inspected = service.inspect_experiment_run(RUN_ID)
    assert inspected['evidence']['time_base'] == 'nanoseconds'
    assert inspected['evidence']['frame_id'] == 'map'
    assert len(inspected['evidence']['sources']) == 3
    assert all(source['size_bytes'] > 0 for source in inspected['evidence']['sources'])


def test_analysis_returns_bounded_matrix_and_control_evidence(tmp_path):
    """MCP context contains anomaly evidence, not the full quadratic matrix."""
    result = _service(tmp_path).analyze_experiment_run(RUN_ID)
    evidence = result['evidence']
    assert evidence['summary']['anomaly_window_count'] == 1
    assert evidence['distance_matrix']['rows'] == 12
    assert evidence['distance_matrix']['columns'] == 12
    assert len(evidence['distance_matrix']['sha256']) == 64
    assert len(evidence['anomaly_control_evidence']) == 5
    mechanisms = {
        item['mechanism'] for item in evidence['candidate_mechanisms']
    }
    assert 'controller_oscillation' in mechanisms
    assert result['safety_class'] == 'read_only'


def test_retrieval_preserves_citations_and_can_abstain(tmp_path):
    """Knowledge evidence is cited, while unsupported queries stay empty."""
    service = _service(tmp_path)
    result = service.retrieve_robotics_knowledge(
        'Why is correlation not causal proof?',
        'project2-v1',
        2,
    )
    assert result['evidence']['abstained'] is False
    assert result['citations'][0]['source_id'] == (
        'project2.experiment_diagnosis_contract'
    )
    abstained = service.retrieve_robotics_knowledge(
        'unsupported battery chemistry threshold',
        'project2-v1',
    )
    assert abstained['evidence']['abstained'] is True
    assert abstained['citations'] == []


@pytest.mark.parametrize('run_id', ['../secret', '/tmp/run', 'UNKNOWN'])
def test_run_id_cannot_be_used_as_a_path(tmp_path, run_id):
    """MCP callers cannot turn run lookup into arbitrary file access."""
    with pytest.raises(DiagnosisToolError):
        _service(tmp_path).inspect_experiment_run(run_id)


@pytest.mark.parametrize(
    ('distribution', 'top_k'),
    [('humble', 3), ('jazzy', 0), ('jazzy', 4)],
)
def test_retrieval_bounds_are_enforced(tmp_path, distribution, top_k):
    """Distribution and result cardinality are fixed by local policy."""
    with pytest.raises(DiagnosisToolError):
        _service(tmp_path).retrieve_robotics_knowledge(
            'valid diagnostic query',
            distribution,
            top_k,
        )


def test_report_is_idempotent_and_does_not_modify_sources(tmp_path):
    """Repeated materialization keeps artifact hashes and inputs unchanged."""
    service = _service(tmp_path)
    source_files = sorted(
        path for path in (EXPERIMENT_ROOT / 'experiment_jitter_v1').iterdir()
        if path.is_file()
    )
    before = {str(path): sha256_file(path) for path in source_files}
    queries = [{
        'query': 'Why is correlation only a diagnosis hypothesis?',
        'distribution': 'project2-v1',
    }]
    first = service.materialize_diagnosis_report(RUN_ID, queries)
    second = service.materialize_diagnosis_report(RUN_ID, queries)
    assert first == second
    assert first['safety_class'] == 'artifact_write'
    assert first['evidence']['citation_count'] == 1
    after = {str(path): sha256_file(path) for path in source_files}
    assert before == after
    output = tmp_path / 'artifacts' / first['evidence']['artifact_directory']
    bundle = json.loads(
        (output / 'diagnosis_bundle.json').read_text(encoding='utf-8')
    )
    assert bundle['analysis_sha256'] == first['evidence']['analysis_sha256']
    report = (output / 'report.md').read_text(encoding='utf-8')
    assert 'Versioned knowledge evidence' in report
    assert 'hypotheses' in report
    assert 'before claiming a root cause' in report


def test_one_corrupt_run_fails_discovery_closed(tmp_path):
    """A modified source prevents the catalog from presenting partial trust."""
    copied_root = tmp_path / 'experiments'
    shutil.copytree(EXPERIMENT_ROOT, copied_root)
    command = copied_root / 'experiment_jitter_v1/command.csv'
    command.write_text(command.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    service = _service(tmp_path, copied_root)
    with pytest.raises(DiagnosisToolError, match='sha256 mismatch'):
        service.list_experiment_runs()


def test_subprocess_adapter_rejects_untrusted_configuration(tmp_path):
    """The learned-model process boundary requires fixed existing paths."""
    with pytest.raises(DiagnosisToolError, match='executable'):
        SubprocessRagAdapter(
            tmp_path / 'missing-python',
            tmp_path / 'missing-index',
            [tmp_path],
        )


def test_subprocess_adapter_preserves_virtual_environment_entry(tmp_path):
    """A virtualenv Python symlink must not collapse to the system binary."""
    executable = tmp_path / 'venv-python'
    executable.symlink_to(Path('/usr/bin/python3'))
    index = tmp_path / 'index.json'
    index.write_text('{}', encoding='utf-8')
    adapter = SubprocessRagAdapter(executable, index, [tmp_path])
    assert adapter.python_executable == executable.absolute()


def test_subprocess_adapter_forces_offline_model_loading(tmp_path, monkeypatch):
    """The isolated retriever cannot make an implicit model hub request."""
    executable = tmp_path / 'python'
    executable.symlink_to(Path('/usr/bin/python3'))
    index = tmp_path / 'index.json'
    index.write_text('{}', encoding='utf-8')
    captured = {}

    def fake_run(command, **kwargs):
        captured['command'] = command
        captured['environment'] = kwargs['env']
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'status': 'ok'}),
            stderr='',
        )

    monkeypatch.setattr('robot_diagnosis_mcp.tools.subprocess.run', fake_run)
    adapter = SubprocessRagAdapter(executable, index, [tmp_path])
    assert adapter.query('query', 'project2-v1', 1) == {'status': 'ok'}
    environment = captured['environment']
    assert environment['HF_HUB_OFFLINE'] == '1'
    assert environment['TRANSFORMERS_OFFLINE'] == '1'
    assert 'HTTP_PROXY' not in environment
    assert 'HTTPS_PROXY' not in environment
