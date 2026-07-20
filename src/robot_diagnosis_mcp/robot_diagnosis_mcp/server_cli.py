"""Launch the local robot diagnosis MCP server over stdio."""

import argparse
from pathlib import Path

from robot_rag import load_index

from .tools import (
    DiagnosisToolError,
    DiagnosisToolService,
    InProcessRagAdapter,
    SubprocessRagAdapter,
)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-root', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path, required=True)
    parser.add_argument('--rag-index', type=Path, required=True)
    parser.add_argument('--schema-dir', type=Path, required=True)
    parser.add_argument('--rag-python', type=Path)
    parser.add_argument(
        '--rag-module-path',
        type=Path,
        action='append',
        default=[],
    )
    parser.add_argument('--embedding-device', default='cuda')
    parser.add_argument('--rag-timeout-sec', type=float, default=120.0)
    parser.add_argument('--hf-home', type=Path)
    return parser


def _rag_adapter(args):
    index = load_index(args.rag_index)
    learned = index['build_config']['embedding_provider'] != 'feature_hash_v1'
    if args.rag_python:
        if not args.rag_module_path:
            raise DiagnosisToolError(
                '--rag-module-path is required with --rag-python'
            )
        return SubprocessRagAdapter(
            args.rag_python,
            args.rag_index,
            args.rag_module_path,
            embedding_device=args.embedding_device,
            timeout_sec=args.rag_timeout_sec,
            hf_home=args.hf_home,
        )
    if learned:
        raise DiagnosisToolError(
            'learned index requires --rag-python process isolation'
        )
    return InProcessRagAdapter(args.rag_index)


def main(argv=None):
    """Configure dependencies before importing the official MCP adapter."""
    args = _parser().parse_args(argv)
    try:
        service = DiagnosisToolService(
            experiment_root=args.experiment_root,
            artifact_root=args.artifact_root,
            rag_adapter=_rag_adapter(args),
            schema_directory=args.schema_dir,
        )
        from .server import create_server
    except (DiagnosisToolError, ImportError) as error:
        raise SystemExit(f'MCP CONFIGURATION ERROR: {error}') from error
    create_server(service).run(transport='stdio')


if __name__ == '__main__':
    main()
