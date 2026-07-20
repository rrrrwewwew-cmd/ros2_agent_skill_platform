"""Deterministic BM25 plus feature-hash retrieval with citations."""

from collections import Counter
import math

from robot_rag.util import (
    feature_hash_vector,
    RagError,
    tokenize,
    validate_document,
)


def _filter_chunks(chunks, filters):
    allowed = {'distribution', 'product', 'source_type'}
    unknown = set(filters) - allowed
    if unknown:
        raise RagError(f'unsupported retrieval filters: {sorted(unknown)}')
    return [
        chunk for chunk in chunks
        if all(chunk.get(key) == value for key, value in filters.items())
    ]


def _bm25_scores(chunks, query_terms, k1=1.5, b=0.75):
    if not chunks:
        return []
    document_terms = [chunk['terms'] for chunk in chunks]
    average_length = sum(map(len, document_terms)) / len(document_terms)
    average_length = average_length or 1.0
    frequencies = [Counter(terms) for terms in document_terms]
    document_frequency = {
        term: sum(term in frequency for frequency in frequencies)
        for term in set(query_terms)
    }
    scores = []
    for terms, frequency in zip(document_terms, frequencies):
        score = 0.0
        for term in query_terms:
            count = frequency.get(term, 0)
            if not count:
                continue
            df = document_frequency[term]
            inverse = math.log(1.0 + (len(chunks) - df + 0.5) / (df + 0.5))
            denominator = count + k1 * (
                1.0 - b + b * len(terms) / average_length
            )
            score += inverse * count * (k1 + 1.0) / denominator
        scores.append(score)
    return scores


def _dot(left, right):
    return sum(first * second for first, second in zip(left, right))


def retrieve(
    index,
    query,
    top_k=3,
    filters=None,
    bm25_weight=0.65,
    feature_hash_weight=0.35,
    schema_dir=None,
):
    """Retrieve cited chunks from an already verified in-memory index."""
    query = query.strip()
    if not query or len(query) > 1000:
        raise RagError('query must contain 1 to 1000 characters')
    if not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise RagError('top_k must be an integer between 1 and 10')
    if abs((bm25_weight + feature_hash_weight) - 1.0) > 1e-9:
        raise RagError('retrieval weights must sum to 1.0')
    if min(bm25_weight, feature_hash_weight) < 0:
        raise RagError('retrieval weights must be non-negative')
    filters = dict(filters or {})
    chunks = _filter_chunks(index['chunks'], filters)
    query_terms = tokenize(query)
    bm25_scores = _bm25_scores(chunks, query_terms)
    maximum_bm25 = max(bm25_scores, default=0.0)
    query_vector = feature_hash_vector(
        query,
        index['build_config']['embedding_dimensions'],
    )
    scored = []
    for chunk, raw_bm25 in zip(chunks, bm25_scores):
        normalized_bm25 = (
            raw_bm25 / maximum_bm25 if maximum_bm25 else 0.0
        )
        feature_score = max(0.0, _dot(query_vector, chunk['vector']))
        score = (
            bm25_weight * normalized_bm25 +
            feature_hash_weight * feature_score
        )
        scored.append((score, normalized_bm25, feature_score, chunk))
    scored.sort(key=lambda item: (
        -item[0],
        item[3]['source_id'],
        item[3]['ordinal'],
    ))
    hits = []
    for rank, (score, bm25, feature, chunk) in enumerate(
        scored[:top_k],
        start=1,
    ):
        hits.append({
            'rank': rank,
            'score': round(score, 8),
            'bm25_score': round(bm25, 8),
            'feature_hash_score': round(feature, 8),
            'chunk_id': chunk['chunk_id'],
            'heading': chunk['heading'],
            'text': chunk['text'],
            'citation': {
                'source_id': chunk['source_id'],
                'source_version': chunk['source_version'],
                'source_content_sha256': chunk['source_content_sha256'],
                'chunk_sha256': chunk['text_sha256'],
                'canonical_url': chunk['canonical_url'],
                'distribution': chunk['distribution'],
            },
        })
    result = {
        'schema_version': 1,
        'query': query,
        'filters': filters,
        'corpus_id': index['corpus_id'],
        'corpus_version': index['corpus_version'],
        'index_content_sha256': index['index_content_sha256'],
        'retrieval_config': {
            'algorithm': 'bm25_feature_hash_v1',
            'bm25_weight': bm25_weight,
            'feature_hash_weight': feature_hash_weight,
            'top_k': top_k,
        },
        'hits': hits,
    }
    validate_document(result, 'rag_retrieval_result', schema_dir)
    return result
