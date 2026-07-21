"""Exercise all diagnosis tools through a real MCP stdio session."""

import argparse
import asyncio
from datetime import timedelta
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from robot_rag.util import canonical_sha256, write_json
from safe_agent_core.experiment_analytics import sha256_file


EXPECTED_TOOLS = (
    'list_experiment_runs',
    'inspect_experiment_run',
    'analyze_experiment_run',
    'retrieve_robotics_knowledge',
    'materialize_diagnosis_report',
)


def _stage(message):
    print(f'[mcp-smoke] {message}', file=sys.stderr, flush=True)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--experiment-root', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path, required=True)
    parser.add_argument('--rag-index', type=Path, required=True)
    parser.add_argument('--schema-dir', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--distribution', default='project2-v1')
    parser.add_argument('--rag-python', type=Path)
    parser.add_argument('--rag-module-path', type=Path, action='append', default=[])
    parser.add_argument('--embedding-device', default='cuda')
    parser.add_argument('--hf-home', type=Path)
    parser.add_argument('--require-citation', action='store_true')
    parser.add_argument('--read-timeout-sec', type=float, default=30.0)
    return parser


def _source_snapshot(root):
    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob('*'))
        if path.is_file()
    }


def _payload(result, expected_tool):
    if result.isError:
        messages = [
            getattr(item, 'text', '')
            for item in result.content
            if getattr(item, 'type', None) == 'text'
        ]
        raise RuntimeError(
            f'MCP tool {expected_tool} failed: {" ".join(messages)}'
        )
    payload = result.structuredContent
    if payload is None:
        texts = [
            item.text
            for item in result.content
            if getattr(item, 'type', None) == 'text'
        ]
        if len(texts) != 1:
            raise RuntimeError(f'MCP tool {expected_tool} has no structured result')
        payload = json.loads(texts[0])
    if set(payload) == {'result'} and isinstance(payload['result'], dict):
        payload = payload['result']
    if payload.get('tool_name') != expected_tool:
        raise RuntimeError(f'MCP tool identity mismatch for {expected_tool}')
    return payload


def _server_arguments(args):
    values = [
        '-m',
        'robot_diagnosis_mcp.server_cli',
        '--experiment-root',
        str(args.experiment_root.resolve()),
        '--artifact-root',
        str(args.artifact_root.resolve()),
        '--rag-index',
        str(args.rag_index.resolve()),
        '--schema-dir',
        str(args.schema_dir.resolve()),
        '--embedding-device',
        args.embedding_device,
    ]
    if args.rag_python:
        values.extend(['--rag-python', str(args.rag_python.absolute())])
    for path in args.rag_module_path:
        values.extend(['--rag-module-path', str(path.resolve())])
    if args.hf_home:
        values.extend(['--hf-home', str(args.hf_home.resolve())])
    return values


def _server_environment():
    repository = Path(__file__).resolve().parents[3]
    module_paths = [
        repository / 'src/robot_diagnosis_mcp',
        repository / 'src/robot_rag',
        repository / 'src/safe_agent_core',
    ]
    current = os.environ.get('PYTHONPATH')
    if current:
        module_paths.extend(Path(item) for item in current.split(os.pathsep))
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join(
        str(path.resolve()) for path in module_paths
    )
    return environment


async def _run(args):
    if not 5.0 <= args.read_timeout_sec <= 300.0:
        raise ValueError('read timeout must be between 5 and 300 seconds')
    source_before = _source_snapshot(args.experiment_root.resolve())
    server = StdioServerParameters(
        command=str(args.server_python.expanduser().absolute()),
        args=_server_arguments(args),
        env=_server_environment(),
        cwd=Path(__file__).resolve().parents[3],
    )
    query = (
        '写机器人抖动假设前，如何把距离矩阵、异常时间窗、控制指令和 '
        'Trace 关联成证据链？'
    )
    _stage('starting stdio server')
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=args.read_timeout_sec),
        ) as session:
            _stage('initializing protocol session')
            initialized = await session.initialize()
            _stage('listing tools and checking annotations')
            listed_tools = await session.list_tools()
            by_name = {tool.name: tool for tool in listed_tools.tools}
            if tuple(by_name) != EXPECTED_TOOLS:
                raise RuntimeError(
                    f'unexpected MCP tools: {tuple(by_name)}'
                )
            annotations = {
                name: tool.annotations.model_dump(by_alias=True)
                for name, tool in by_name.items()
            }
            for name in EXPECTED_TOOLS[:4]:
                if annotations[name].get('readOnlyHint') is not True:
                    raise RuntimeError(f'{name} is not annotated read-only')
            report_annotations = annotations['materialize_diagnosis_report']
            if report_annotations.get('destructiveHint') is not False:
                raise RuntimeError('report tool must be non-destructive')
            if report_annotations.get('idempotentHint') is not True:
                raise RuntimeError('report tool must be idempotent')

            calls = {}
            requests = (
                ('list_experiment_runs', {}),
                ('inspect_experiment_run', {'run_id': args.run_id}),
                ('analyze_experiment_run', {'run_id': args.run_id}),
                (
                    'retrieve_robotics_knowledge',
                    {
                        'query': query,
                        'distribution': args.distribution,
                        'top_k': 3,
                    },
                ),
                (
                    'materialize_diagnosis_report',
                    {
                        'run_id': args.run_id,
                        'knowledge_queries': [{
                            'query': query,
                            'distribution': args.distribution,
                        }],
                    },
                ),
            )
            for name, arguments in requests:
                _stage(f'calling {name}')
                result = await session.call_tool(name, arguments)
                calls[name] = _payload(result, name)
                _stage(f'{name} passed')

            if args.require_citation:
                retrieval = calls['retrieve_robotics_knowledge']
                report = calls['materialize_diagnosis_report']
                if not retrieval['citations'] or not report['citations']:
                    raise RuntimeError(
                        'citation-required smoke received no cited evidence'
                    )

    _stage('checking source immutability and writing evidence')
    source_after = _source_snapshot(args.experiment_root.resolve())
    report = calls['materialize_diagnosis_report']['evidence']
    evidence = {
        'schema_version': 1,
        'status': 'passed',
        'transport': 'stdio',
        'mcp_sdk_version': version('mcp'),
        'anyio_version': version('anyio'),
        'protocol_version': initialized.protocolVersion,
        'server': initialized.serverInfo.model_dump(by_alias=True),
        'tool_names': list(EXPECTED_TOOLS),
        'tool_annotations': annotations,
        'calls': {
            name: {
                'input_sha256': result['input_sha256'],
                'evidence_sha256': result['evidence_sha256'],
                'safety_class': result['safety_class'],
                'citation_count': len(result['citations']),
            }
            for name, result in calls.items()
        },
        'report_artifact_directory': report['artifact_directory'],
        'report_artifact_hashes': report['artifact_hashes'],
        'source_file_count': len(source_before),
        'source_snapshot_sha256': canonical_sha256(source_before),
        'source_files_unchanged': source_before == source_after,
    }
    if not evidence['source_files_unchanged']:
        raise RuntimeError('MCP session modified source experiment evidence')
    write_json(args.output.expanduser().resolve(), evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv=None):
    """Run the asynchronous protocol check and persist structured evidence."""
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f'MCP PROTOCOL SMOKE FAILED: {error}') from error


if __name__ == '__main__':
    main()
