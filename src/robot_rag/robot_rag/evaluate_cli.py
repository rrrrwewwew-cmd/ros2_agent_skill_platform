"""CLI for frozen deterministic RAG retrieval evaluation."""

import argparse
import json
from pathlib import Path

from robot_rag.corpus import load_index
from robot_rag.evaluation import evaluate_retrieval
from robot_rag.paths import default_corpus_root, default_index_path
from robot_rag.util import RagError


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=default_index_path())
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--allow-model-download', action='store_true')
    parser.add_argument('--embedding-device')
    return parser


def main(argv=None):
    """Evaluate an index and persist JSON plus CSV evidence."""
    args = _parser().parse_args(argv)
    manifest = (
        args.manifest or
        default_corpus_root() / 'evals/retrieval_eval_v1.json'
    )
    try:
        index = load_index(args.index)
        summary = evaluate_retrieval(
            index,
            manifest,
            output_dir=args.output_dir,
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
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['counts']['failed'] == 0 else 4


if __name__ == '__main__':
    raise SystemExit(main())
