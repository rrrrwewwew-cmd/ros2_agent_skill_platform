"""Bounded tool implementations behind the robot diagnosis MCP server."""

import json
import os
from pathlib import Path
import re
import subprocess

from jsonschema import Draft202012Validator
from robot_rag import load_index, retrieve
from robot_rag.embedding import create_embedder
from robot_rag.util import canonical_sha256, write_json
from safe_agent_core import (
    analyze_experiment,
    ExperimentDataError,
    query_experiment_runs,
)
from safe_agent_core.experiment_analytics import (
    load_experiment_manifest,
    render_markdown_report,
    sha256_file,
    write_analysis_artifacts,
)


TOOL_VERSION = '0.1.0'
_RUN_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]{2,63}$')
_DISTRIBUTIONS = {'jazzy', 'project1-v1', 'project2-v1'}


class DiagnosisToolError(RuntimeError):
    """Reject unsafe tool input or untrusted evidence."""


def _read_schema(schema_directory, name):
    path = Path(schema_directory).expanduser().resolve() / f'{name}.schema.json'
    try:
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError) as error:
        raise DiagnosisToolError(f'cannot load schema {name}: {error}') from error
    return Draft202012Validator(schema)


def _validate(validator, value, label):
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = '.'.join(map(str, first.path)) or '<root>'
        raise DiagnosisToolError(
            f'{label} violates schema at {location}: {first.message}'
        )


class InProcessRagAdapter:
    """Query a verified RAG index inside the MCP server process."""

    def __init__(self, index_path, embedder=None, embedding_device=None):
        """Load one immutable index and its matching query encoder."""
        self.index = load_index(index_path)
        self.embedder = embedder or create_embedder(
            self.index['build_config']['embedding_config'],
            device=embedding_device,
        )

    def query(self, query, distribution, top_k):
        """Return cited retrieval evidence under a fixed distribution."""
        return retrieve(
            self.index,
            query,
            top_k=top_k,
            filters={'distribution': distribution},
            embedder=self.embedder,
        )


class SubprocessRagAdapter:
    """Run the pinned learned retriever in its isolated Python environment."""

    def __init__(
        self,
        python_executable,
        index_path,
        module_paths,
        embedding_device='cuda',
        timeout_sec=120.0,
        hf_home=None,
    ):
        """Bind an absolute executable, index and import roots without shell."""
        executable = Path(python_executable).expanduser().absolute()
        index = Path(index_path).expanduser().resolve()
        paths = [Path(item).expanduser().resolve() for item in module_paths]
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise DiagnosisToolError('RAG Python executable is unavailable')
        if not index.is_file():
            raise DiagnosisToolError('RAG index is unavailable')
        if not paths or any(not path.is_dir() for path in paths):
            raise DiagnosisToolError('RAG module paths must be existing directories')
        if not 1.0 <= float(timeout_sec) <= 300.0:
            raise DiagnosisToolError('RAG timeout must be between 1 and 300 seconds')
        self.python_executable = executable
        self.index_path = index
        self.module_paths = paths
        self.embedding_device = embedding_device
        self.timeout_sec = float(timeout_sec)
        self.hf_home = Path(
            hf_home or '~/.cache/huggingface'
        ).expanduser().resolve()

    def query(self, query, distribution, top_k):
        """Invoke only robot_rag.query_cli and parse its structured stdout."""
        command = [
            str(self.python_executable),
            '-m',
            'robot_rag.query_cli',
            query,
            '--index',
            str(self.index_path),
            '--top-k',
            str(top_k),
            '--distribution',
            distribution,
            '--embedding-device',
            self.embedding_device,
        ]
        environment = {
            'HOME': str(Path.home()),
            'HF_HOME': str(self.hf_home),
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
            'TOKENIZERS_PARALLELISM': 'false',
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PYTHONPATH': os.pathsep.join(map(str, self.module_paths)),
        }
        for name in ('CUDA_VISIBLE_DEVICES', 'LD_LIBRARY_PATH'):
            if name in os.environ:
                environment[name] = os.environ[name]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DiagnosisToolError(
                f'isolated RAG process failed: {error}'
            ) from error
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            detail = (completed.stderr or completed.stdout).strip()[-800:]
            raise DiagnosisToolError(
                'isolated RAG process returned non-JSON output '
                f'(exit {completed.returncode}): {detail}'
            ) from error
        if completed.returncode != 0 or result.get('status') == 'failed':
            message = result.get('error') or completed.stderr[-500:]
            raise DiagnosisToolError(f'isolated RAG query failed: {message}')
        return result


class DiagnosisToolService:
    """Implement governed experiment tools independently of MCP transport."""

    def __init__(
        self,
        experiment_root,
        artifact_root,
        rag_adapter,
        schema_directory,
    ):
        """Bind allowlisted roots, one retriever and machine contracts."""
        self.experiment_root = Path(experiment_root).expanduser().resolve()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        if not self.experiment_root.is_dir():
            raise DiagnosisToolError('experiment root is not a directory')
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.rag_adapter = rag_adapter
        self.result_validator = _read_schema(
            schema_directory,
            'mcp_tool_result',
        )
        self.bundle_validator = _read_schema(
            schema_directory,
            'diagnosis_report_bundle',
        )

    def _result(
        self,
        tool_name,
        inputs,
        evidence,
        citations=None,
        safety_class='read_only',
    ):
        result = {
            'schema_version': 1,
            'tool_name': tool_name,
            'tool_version': TOOL_VERSION,
            'safety_class': safety_class,
            'input_sha256': canonical_sha256(inputs),
            'evidence_sha256': canonical_sha256(evidence),
            'evidence': evidence,
            'citations': list(citations or []),
        }
        _validate(self.result_validator, result, 'MCP tool result')
        return result

    def _run_catalog(self):
        try:
            runs = query_experiment_runs(self.experiment_root)
        except ExperimentDataError as error:
            raise DiagnosisToolError(str(error)) from error
        identifiers = [run['run_id'] for run in runs]
        if len(identifiers) != len(set(identifiers)):
            raise DiagnosisToolError('experiment root contains duplicate run_id')
        return runs

    def _manifest_path(self, run_id):
        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
            raise DiagnosisToolError('run_id violates the allowlisted format')
        run = next(
            (item for item in self._run_catalog() if item['run_id'] == run_id),
            None,
        )
        if run is None:
            raise DiagnosisToolError(f'unknown experiment run_id: {run_id}')
        path = (self.experiment_root / run['manifest']).resolve()
        if not path.is_relative_to(self.experiment_root):
            raise DiagnosisToolError('experiment manifest escapes root')
        return path

    def list_experiment_runs(self):
        """List only hash-verified runs beneath the configured root."""
        runs = self._run_catalog()
        evidence = {'count': len(runs), 'runs': runs}
        return self._result('list_experiment_runs', {}, evidence)

    def inspect_experiment_run(self, run_id):
        """Verify one run and expose its typed manifest plus source hashes."""
        manifest_path = self._manifest_path(run_id)
        try:
            manifest, sources = load_experiment_manifest(manifest_path)
        except ExperimentDataError as error:
            raise DiagnosisToolError(str(error)) from error
        evidence = {
            'run_id': manifest['run_id'],
            'scenario': manifest['scenario'],
            'started_at': manifest['started_at'],
            'time_base': manifest['time_base'],
            'frame_id': manifest['frame_id'],
            'manifest_sha256': sha256_file(manifest_path),
            'sources': [{
                'name': name,
                'relative_path': manifest['sources'][name]['path'],
                'sha256': manifest['sources'][name]['sha256'],
                'size_bytes': path.stat().st_size,
            } for name, path in sorted(sources.items())],
        }
        return self._result(
            'inspect_experiment_run',
            {'run_id': run_id},
            evidence,
        )

    def analyze_experiment_run(self, run_id):
        """Return bounded deterministic anomaly and control evidence."""
        manifest_path = self._manifest_path(run_id)
        try:
            analysis = analyze_experiment(manifest_path)
        except ExperimentDataError as error:
            raise DiagnosisToolError(str(error)) from error
        evidence_samples = []
        for sample in analysis['correlated_samples']:
            if any(
                window['start_ns'] <= sample['timestamp_ns'] <= window['end_ns']
                for window in analysis['anomaly_windows']
            ):
                evidence_samples.append(sample)
        evidence = {
            'run_id': run_id,
            'analyzer_version': analysis['analyzer_version'],
            'analysis_sha256': canonical_sha256(analysis),
            'parameters': analysis['parameters'],
            'source_hashes': analysis['source_hashes'],
            'summary': analysis['summary'],
            'distance_matrix': {
                'rows': len(analysis['distance_matrix_m']),
                'columns': (
                    len(analysis['distance_matrix_m'][0])
                    if analysis['distance_matrix_m'] else 0
                ),
                'sha256': canonical_sha256(analysis['distance_matrix_m']),
                'sample_timestamps_ns': analysis[
                    'distance_matrix_sample_timestamps_ns'
                ],
            },
            'anomaly_windows': analysis['anomaly_windows'],
            'candidate_mechanisms': analysis['candidate_mechanisms'],
            'anomaly_control_evidence': evidence_samples,
        }
        return self._result(
            'analyze_experiment_run',
            {'run_id': run_id},
            evidence,
        )

    def retrieve_robotics_knowledge(
        self,
        query,
        distribution='jazzy',
        top_k=3,
    ):
        """Retrieve version-filtered, hash-bound diagnostic knowledge."""
        if not isinstance(query, str) or not 3 <= len(query.strip()) <= 300:
            raise DiagnosisToolError('query must contain 3 to 300 characters')
        if distribution not in _DISTRIBUTIONS:
            raise DiagnosisToolError('distribution is not allowlisted')
        if not isinstance(top_k, int) or not 1 <= top_k <= 3:
            raise DiagnosisToolError('top_k must be an integer from 1 to 3')
        try:
            retrieval = self.rag_adapter.query(
                query.strip(),
                distribution,
                top_k,
            )
        except Exception as error:
            if isinstance(error, DiagnosisToolError):
                raise
            raise DiagnosisToolError(f'RAG retrieval failed: {error}') from error
        citations = [hit['citation'] for hit in retrieval['hits']]
        evidence = {
            'query': retrieval['query'],
            'distribution': distribution,
            'index_content_sha256': retrieval['index_content_sha256'],
            'retrieval_config': retrieval['retrieval_config'],
            'abstained': retrieval['abstained'],
            'abstention_reason': retrieval['abstention_reason'],
            'unsupported_identifiers': retrieval['unsupported_identifiers'],
            'hits': retrieval['hits'],
        }
        return self._result(
            'retrieve_robotics_knowledge',
            {
                'query': query.strip(),
                'distribution': distribution,
                'top_k': top_k,
            },
            evidence,
            citations,
        )

    def materialize_diagnosis_report(self, run_id, knowledge_queries):
        """Write an idempotent evidence bundle outside the source run root."""
        queries = self._validate_knowledge_queries(knowledge_queries)
        manifest_path = self._manifest_path(run_id)
        try:
            analysis = analyze_experiment(manifest_path)
        except ExperimentDataError as error:
            raise DiagnosisToolError(str(error)) from error
        retrieval_results = [
            self.retrieve_robotics_knowledge(
                item['query'],
                item['distribution'],
                top_k=3,
            )
            for item in queries
        ]
        retrieval_evidence = [result['evidence'] for result in retrieval_results]
        citations = self._deduplicate_citations(
            citation
            for result in retrieval_results
            for citation in result['citations']
        )
        bundle = {
            'schema_version': 1,
            'bundle_version': TOOL_VERSION,
            'run_id': run_id,
            'analysis_sha256': canonical_sha256(analysis),
            'knowledge_queries': queries,
            'retrieval_evidence': retrieval_evidence,
            'candidate_mechanisms': analysis['candidate_mechanisms'],
            'limitations': [
                'Candidate mechanisms are evidence-backed hypotheses, not causal proof.',
                (
                    'RAG citations explain interfaces and plausible mechanisms; '
                    'they do not replace intervention experiments.'
                ),
                'An abstained retrieval contributes no factual support.',
            ],
        }
        _validate(self.bundle_validator, bundle, 'diagnosis report bundle')
        bundle_hash = canonical_sha256(bundle)
        output = (self.artifact_root / run_id / bundle_hash[:16]).resolve()
        if not output.is_relative_to(self.artifact_root):
            raise DiagnosisToolError('diagnosis output escapes artifact root')
        artifacts = write_analysis_artifacts(analysis, output)
        report_text = self._report_with_citations(
            render_markdown_report(analysis),
            retrieval_results,
        )
        artifacts['report_markdown'].write_text(
            report_text,
            encoding='utf-8',
        )
        bundle_path = output / 'diagnosis_bundle.json'
        write_json(bundle_path, bundle)
        artifacts['diagnosis_bundle'] = bundle_path
        artifact_hashes = {
            name: sha256_file(path)
            for name, path in sorted(artifacts.items())
        }
        evidence = {
            'run_id': run_id,
            'bundle_sha256': bundle_hash,
            'artifact_directory': str(output.relative_to(self.artifact_root)),
            'artifact_hashes': artifact_hashes,
            'analysis_sha256': bundle['analysis_sha256'],
            'candidate_mechanisms': bundle['candidate_mechanisms'],
            'retrieval_count': len(retrieval_results),
            'citation_count': len(citations),
        }
        return self._result(
            'materialize_diagnosis_report',
            {'run_id': run_id, 'knowledge_queries': queries},
            evidence,
            citations,
            safety_class='artifact_write',
        )

    @staticmethod
    def _validate_knowledge_queries(value):
        if not isinstance(value, list) or not 1 <= len(value) <= 3:
            raise DiagnosisToolError('knowledge_queries must contain 1 to 3 items')
        normalized = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {'query', 'distribution'}:
                raise DiagnosisToolError(
                    'each knowledge query requires only query and distribution'
                )
            query = item['query']
            distribution = item['distribution']
            if not isinstance(query, str) or not 3 <= len(query.strip()) <= 300:
                raise DiagnosisToolError('knowledge query length is invalid')
            if distribution not in _DISTRIBUTIONS:
                raise DiagnosisToolError('knowledge query distribution is invalid')
            normalized.append({
                'query': query.strip(),
                'distribution': distribution,
            })
        return normalized

    @staticmethod
    def _deduplicate_citations(citations):
        unique = {}
        for citation in citations:
            key = (
                citation['source_id'],
                citation['chunk_sha256'],
            )
            unique[key] = citation
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _report_with_citations(base_report, retrieval_results):
        lines = [base_report.rstrip(), '', '## Versioned knowledge evidence', '']
        for result in retrieval_results:
            evidence = result['evidence']
            lines.append(f'### Query: {evidence["query"]}')
            lines.append('')
            if evidence['abstained']:
                lines.append(
                    f'- Retrieval abstained: `{evidence["abstention_reason"]}`'
                )
                lines.append('')
                continue
            for hit in evidence['hits']:
                citation = hit['citation']
                lines.append(
                    f'- `{citation["source_id"]}` / `{hit["chunk_id"]}`: '
                    f'{citation["canonical_url"]} '
                    f'(chunk `{citation["chunk_sha256"]}`)'
                )
            lines.append('')
        lines.extend([
            '## Causality boundary',
            '',
            'The mechanisms above are evidence-backed hypotheses. '
            'A controlled intervention or additional evidence is required '
            'before claiming a root cause.',
            '',
        ])
        return '\n'.join(lines)
