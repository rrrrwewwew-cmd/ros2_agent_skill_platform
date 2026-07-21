"""Call one diagnosis tool through an official MCP stdio session."""

import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .contracts import TOOL_ORDER


def _error_message(error):
    """Flatten async exception groups into a bounded transport diagnosis."""
    if isinstance(error, BaseExceptionGroup):
        details = [_error_message(item) for item in error.exceptions]
        return f'{error}: ' + ' | '.join(details)
    return f'{type(error).__name__}: {error}'


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-root', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path, required=True)
    parser.add_argument('--rag-index', type=Path, required=True)
    parser.add_argument('--schema-dir', type=Path, required=True)
    parser.add_argument('--tool-name', choices=TOOL_ORDER, required=True)
    parser.add_argument('--arguments-json', required=True)
    parser.add_argument('--read-timeout-sec', type=float, default=120.0)
    parser.add_argument('--rag-python', type=Path)
    parser.add_argument('--rag-module-path', type=Path, action='append', default=[])
    parser.add_argument('--embedding-device', default='cuda')
    parser.add_argument('--hf-home', type=Path)
    return parser


def _server_args(args):
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


def _payload(call_result):
    if call_result.isError:
        text = ' '.join(
            getattr(item, 'text', '') for item in call_result.content
        )
        raise RuntimeError(text or 'MCP tool returned an error')
    payload = call_result.structuredContent
    if payload is None:
        text_items = [
            item.text for item in call_result.content
            if getattr(item, 'type', None) == 'text'
        ]
        if len(text_items) != 1:
            raise RuntimeError('MCP tool omitted structured output')
        payload = json.loads(text_items[0])
    if set(payload) == {'result'} and isinstance(payload['result'], dict):
        payload = payload['result']
    if not isinstance(payload, dict):
        raise RuntimeError('MCP structured output is not an object')
    return payload


async def _call(args, arguments):
    environment = dict(os.environ)
    server = StdioServerParameters(
        command=sys.executable,
        args=_server_args(args),
        env=environment,
        cwd=Path(__file__).resolve().parents[3],
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(
                seconds=float(args.read_timeout_sec)
            ),
        ) as session:
            await session.initialize()
            result = await session.call_tool(args.tool_name, arguments)
            return _payload(result)


def main(argv=None):
    """Validate input, perform one MCP call, and print JSON only."""
    args = _parser().parse_args(argv)
    try:
        arguments = json.loads(args.arguments_json)
        if not isinstance(arguments, dict):
            raise ValueError('arguments-json must contain an object')
        if not 5.0 <= float(args.read_timeout_sec) <= 300.0:
            raise ValueError('read timeout must be in [5, 300] seconds')
        result = asyncio.run(_call(args, arguments))
        output = {'schema_version': 1, 'state': 'succeeded', 'result': result}
        code = 0
    except Exception as error:
        output = {
            'schema_version': 1,
            'state': 'failed',
            'error': _error_message(error)[:1000],
        }
        code = 3
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
