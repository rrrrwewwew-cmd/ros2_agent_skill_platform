"""CLI for local cited RAG retrieval."""

import argparse
import json
from pathlib import Path

from robot_rag.corpus import load_index
from robot_rag.paths import default_index_path
from robot_rag.retrieval import retrieve
from robot_rag.util import RagError


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--index', type=Path, default=default_index_path())
    parser.add_argument('--top-k', type=int, default=3)
    parser.add_argument('--distribution')
    parser.add_argument('--product')
    parser.add_argument('--source-type')
    parser.add_argument('--allow-model-download', action='store_true')
    parser.add_argument('--embedding-device')
    return parser


def main(argv=None):
    """Load a verified index and return structured cited hits."""
    args = _parser().parse_args(argv)
    filters = {
        key: value for key, value in {
            'distribution': args.distribution,
            'product': args.product,
            'source_type': args.source_type,
        }.items() if value is not None
    }
    try:
        index = load_index(args.index)
        result = retrieve(
            index,
            args.query,
            top_k=args.top_k,
            filters=filters,
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
