"""CLI for frozen baseline-versus-learned RAG evaluation."""

import argparse
import json
from pathlib import Path

from robot_rag.ab_evaluation import compare_retrievers
from robot_rag.corpus import load_index
from robot_rag.util import RagError


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-index', type=Path, required=True)
    parser.add_argument('--candidate-index', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--comparison-id', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--allow-model-download', action='store_true')
    parser.add_argument('--embedding-device')
    return parser


def main(argv=None):
    """Run both retrieval arms and persist their evidence separately."""
    args = _parser().parse_args(argv)
    try:
        result = compare_retrievers(
            load_index(args.baseline_index),
            load_index(args.candidate_index),
            args.manifest,
            args.comparison_id,
            args.output_dir,
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
    return 0 if result['acceptance']['passed'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
