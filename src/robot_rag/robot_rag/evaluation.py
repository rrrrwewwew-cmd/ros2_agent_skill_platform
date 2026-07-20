"""Reproducible retrieval evaluation over frozen RAG cases."""

import csv
import json
from pathlib import Path

from robot_rag.embedding import create_embedder
from robot_rag.retrieval import retrieve
from robot_rag.util import RagError, validate_document, write_json


def _load_manifest(path, schema_dir):
    try:
        manifest = json.loads(
            Path(path).expanduser().read_text(encoding='utf-8')
        )
    except (OSError, json.JSONDecodeError) as error:
        raise RagError(f'cannot read RAG evaluation manifest: {error}') from error
    validate_document(manifest, 'rag_evaluation_manifest', schema_dir)
    case_ids = [case['case_id'] for case in manifest['cases']]
    if len(case_ids) != len(set(case_ids)):
        raise RagError('RAG evaluation contains duplicate case_id')
    return manifest


def _citation_is_intact(hit, index_chunks):
    chunk = index_chunks.get(hit['chunk_id'])
    if chunk is None:
        return False
    citation = hit['citation']
    return all([
        citation['source_id'] == chunk['source_id'],
        citation['source_version'] == chunk['source_version'],
        citation['source_content_sha256'] == chunk['source_content_sha256'],
        citation['chunk_sha256'] == chunk['text_sha256'],
        citation['canonical_url'] == chunk['canonical_url'],
        citation['distribution'] == chunk['distribution'],
    ])


def evaluate_retrieval(
    index,
    manifest_path,
    output_dir=None,
    schema_dir=None,
    embedder=None,
    allow_model_download=False,
    embedding_device=None,
):
    """Evaluate retrieval relevance, version filtering and citation hashes."""
    manifest = _load_manifest(manifest_path, schema_dir)
    encoder = embedder or create_embedder(
        index['build_config']['embedding_config'],
        allow_download=allow_model_download,
        device=embedding_device,
    )
    index_chunks = {chunk['chunk_id']: chunk for chunk in index['chunks']}
    results = []
    recalls = []
    reciprocal_ranks = []
    version_checks = []
    citation_checks = []
    answerability_checks = []
    no_answer_checks = []
    answerable_count = 0
    for case in manifest['cases']:
        retrieval = retrieve(
            index,
            case['query'],
            top_k=case['top_k'],
            filters=case['filters'],
            embedder=encoder,
            allow_model_download=allow_model_download,
            embedding_device=embedding_device,
            schema_dir=schema_dir,
        )
        source_ids = [
            hit['citation']['source_id'] for hit in retrieval['hits']
        ]
        expected_answerable = case.get('expected_answerable', True)
        predicted_answerable = bool(retrieval['hits'])
        answerability_correct = expected_answerable == predicted_answerable
        expected = set(case['expected_source_ids'])
        found = expected.intersection(source_ids)
        recall = len(found) / len(expected) if expected else 1.0
        first_rank = next((
            rank for rank, source_id in enumerate(source_ids, start=1)
            if source_id in expected
        ), None)
        forbidden_absent = not set(
            case['forbidden_source_ids']
        ).intersection(source_ids)
        filter_respected = all(
            all(
                index_chunks[hit['chunk_id']].get(key) == value
                for key, value in case['filters'].items()
            )
            for hit in retrieval['hits']
        )
        citations_intact = all(
            _citation_is_intact(hit, index_chunks)
            for hit in retrieval['hits']
        )
        relevance_passed = (
            recall == 1.0 if expected_answerable else not source_ids
        )
        passed = all([
            relevance_passed,
            answerability_correct,
            forbidden_absent,
            filter_respected,
            citations_intact,
        ])
        results.append({
            'case_id': case['case_id'],
            'passed': passed,
            'expected_answerable': expected_answerable,
            'predicted_answerable': predicted_answerable,
            'answerability_correct': answerability_correct,
            'retrieved_source_ids': source_ids,
            'first_relevant_rank': first_rank,
            'citation_integrity': citations_intact,
        })
        if expected_answerable:
            answerable_count += 1
            recalls.append(recall)
            reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        else:
            no_answer_checks.append(answerability_correct)
        version_checks.append(forbidden_absent and filter_respected)
        citation_checks.append(citations_intact)
        answerability_checks.append(answerability_correct)
    passed_count = sum(result['passed'] for result in results)
    total = len(results)
    summary = {
        'schema_version': 1,
        'evaluation_id': manifest['evaluation_id'],
        'corpus_id': index['corpus_id'],
        'corpus_version': index['corpus_version'],
        'index_content_sha256': index['index_content_sha256'],
        'counts': {
            'total': total,
            'passed': passed_count,
            'failed': total - passed_count,
        },
        'metrics': {
            'recall_at_k': (
                sum(recalls) / answerable_count if answerable_count else 1.0
            ),
            'mean_reciprocal_rank': (
                sum(reciprocal_ranks) / answerable_count
                if answerable_count else 1.0
            ),
            'version_filter_accuracy': sum(version_checks) / total,
            'citation_integrity_rate': sum(citation_checks) / total,
            'answerability_accuracy': sum(answerability_checks) / total,
            'no_answer_accuracy': (
                sum(no_answer_checks) / len(no_answer_checks)
                if no_answer_checks else 1.0
            ),
            'interface_hallucination_rate': (
                1.0 - sum(no_answer_checks) / len(no_answer_checks)
                if no_answer_checks else 0.0
            ),
        },
        'case_results': results,
        'status': 'complete' if passed_count == total else 'failed',
    }
    validate_document(summary, 'rag_evaluation_summary', schema_dir)
    if output_dir is not None:
        output = Path(output_dir).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / 'summary.json', summary)
        with (output / 'case_results.csv').open(
            'w', encoding='utf-8', newline=''
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                'case_id',
                'passed',
                'expected_answerable',
                'predicted_answerable',
                'answerability_correct',
                'first_relevant_rank',
                'citation_integrity',
                'retrieved_source_ids',
            ])
            writer.writeheader()
            for result in results:
                row = dict(result)
                row['retrieved_source_ids'] = ';'.join(
                    result['retrieved_source_ids']
                )
                writer.writerow(row)
    return summary
