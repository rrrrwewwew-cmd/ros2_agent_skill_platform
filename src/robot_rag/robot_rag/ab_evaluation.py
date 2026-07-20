"""A/B evaluation for an offline baseline and learned RAG candidate."""

from pathlib import Path

from robot_rag.evaluation import evaluate_retrieval
from robot_rag.util import validate_document, write_json


_METRICS = (
    'recall_at_k',
    'mean_reciprocal_rank',
    'version_filter_accuracy',
    'citation_integrity_rate',
    'answerability_accuracy',
    'no_answer_accuracy',
    'interface_hallucination_rate',
)


def _arm(index, summary):
    return {
        'embedding_provider': index['build_config']['embedding_provider'],
        'embedding_profile_id': index['build_config']['embedding_profile_id'],
        'index_content_sha256': index['index_content_sha256'],
        'counts': summary['counts'],
        'metrics': summary['metrics'],
    }


def _quality_score(metrics):
    return sum([
        metrics['recall_at_k'],
        metrics['mean_reciprocal_rank'],
        metrics['answerability_accuracy'],
        metrics['no_answer_accuracy'],
        1.0 - metrics['interface_hallucination_rate'],
    ]) / 5.0


def compare_retrievers(
    baseline_index,
    candidate_index,
    manifest_path,
    comparison_id,
    output_dir=None,
    candidate_embedder=None,
    allow_model_download=False,
    embedding_device=None,
    schema_dir=None,
):
    """Evaluate both arms on identical frozen cases and report deltas."""
    output = Path(output_dir).expanduser() if output_dir else None
    baseline_output = output / 'baseline' if output else None
    candidate_output = output / 'candidate' if output else None
    baseline = evaluate_retrieval(
        baseline_index,
        manifest_path,
        baseline_output,
        schema_dir,
    )
    candidate = evaluate_retrieval(
        candidate_index,
        manifest_path,
        candidate_output,
        schema_dir,
        embedder=candidate_embedder,
        allow_model_download=allow_model_download,
        embedding_device=embedding_device,
    )
    deltas = {
        name: candidate['metrics'][name] - baseline['metrics'][name]
        for name in _METRICS
    }
    checks = {
        'candidate_recall_within_005': (
            deltas['recall_at_k'] >= -0.05
        ),
        'candidate_mrr_within_010': (
            deltas['mean_reciprocal_rank'] >= -0.10
        ),
        'version_filter_perfect': (
            candidate['metrics']['version_filter_accuracy'] == 1.0
        ),
        'citation_integrity_perfect': (
            candidate['metrics']['citation_integrity_rate'] == 1.0
        ),
        'no_answer_accuracy_at_least_080': (
            candidate['metrics']['no_answer_accuracy'] >= 0.80
        ),
        'interface_hallucination_at_most_020': (
            candidate['metrics']['interface_hallucination_rate'] <= 0.20
        ),
    }
    acceptance_passed = all(checks.values())
    baseline_score = _quality_score(baseline['metrics'])
    candidate_score = _quality_score(candidate['metrics'])
    if abs(candidate_score - baseline_score) <= 1e-9:
        winner = 'tie'
    elif candidate_score > baseline_score:
        winner = 'candidate'
    else:
        winner = 'baseline'
    result = {
        'schema_version': 1,
        'comparison_id': comparison_id,
        'evaluation_id': baseline['evaluation_id'],
        'baseline': _arm(baseline_index, baseline),
        'candidate': _arm(candidate_index, candidate),
        'metric_delta': deltas,
        'acceptance': {
            'passed': acceptance_passed,
            'checks': checks,
        },
        'winner': winner,
        'status': 'complete' if acceptance_passed else 'failed',
    }
    validate_document(result, 'rag_ab_evaluation_summary', schema_dir)
    if output:
        write_json(output / 'comparison.json', result)
    return result
