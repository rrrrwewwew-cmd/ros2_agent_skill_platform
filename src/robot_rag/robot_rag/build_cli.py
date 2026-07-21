"""CLI for deterministic RAG index construction."""

import argparse
import json
from pathlib import Path

from robot_rag.corpus import build_index
from robot_rag.paths import default_corpus_root, default_index_path
from robot_rag.util import RagError


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--embedding-profile', type=Path)
    parser.add_argument('--output', type=Path, default=default_index_path())
    parser.add_argument('--allow-model-download', action='store_true')
    parser.add_argument('--embedding-device')
    return parser


def main(argv=None):
    """Build, validate and persist one version-pinned local index."""
    args = _parser().parse_args(argv)
    manifest = args.manifest or default_corpus_root() / 'manifest.json'
    try:
        index = build_index(
            manifest,
            args.output,
            embedding_profile_path=args.embedding_profile,
            allow_model_download=args.allow_model_download,
            embedding_device=args.embedding_device,
        )
    except RagError as error:
        print(json.dumps({
            'schema_version': 1,
            'status': 'failed',
            'error': str(error),
        }, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps({
        'schema_version': 1,
        'status': 'succeeded',
        'corpus_id': index['corpus_id'],
        'corpus_version': index['corpus_version'],
        'chunks': len(index['chunks']),
        'embedding_provider': index['build_config']['embedding_provider'],
        'index_content_sha256': index['index_content_sha256'],
        'output': str(args.output.expanduser().resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
