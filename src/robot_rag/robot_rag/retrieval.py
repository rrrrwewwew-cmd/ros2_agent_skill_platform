"""Version-aware BM25 plus embedding retrieval with abstention."""

from collections import Counter
import math
import re

from robot_rag.embedding import create_embedder
from robot_rag.util import (
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


_IDENTIFIER_PATTERN = re.compile(
    r'\b(?:[A-Z]{2,}(?:-[A-Z0-9]+)*|'
    r'[A-Za-z]+_[A-Za-z0-9_]+|'
    r'[A-Z][a-z]+[A-Z][A-Za-z0-9]*|'
    r'[A-Za-z]+-[A-Z0-9][A-Za-z0-9-]*)\b'
)


def _unsupported_identifiers(index, query):
    supported = {
        term.lower()
        for chunk in index['chunks']
        for term in chunk['terms']
    }
    supported_compact = {
        re.sub(r'[^a-z]', '', term)
        for term in supported
    }
    requested = {
        match.group(0).lower()
        for match in _IDENTIFIER_PATTERN.finditer(query)
    }

    def is_supported(identifier):
        if identifier in supported:
            return True
        compact = re.sub(r'[^a-z]', '', identifier)
        return any(
            compact and compact in corpus_term
            for corpus_term in supported_compact
        )

    return sorted(
        identifier for identifier in requested
        if not is_supported(identifier)
    )


def retrieve(
    index,
    query,
    top_k=3,
    filters=None,
    bm25_weight=None,
    embedding_weight=None,
    minimum_score=None,
    minimum_embedding_score=None,
    bm25_saturation=None,
    embedder=None,
    allow_model_download=False,
    embedding_device=None,
    schema_dir=None,
):
    """Retrieve cited chunks from an already verified in-memory index."""
    query = query.strip()
    if not query or len(query) > 1000:
        raise RagError('query must contain 1 to 1000 characters')
    if not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise RagError('top_k must be an integer between 1 and 10')
    policy = index['build_config']['retrieval_policy']
    bm25_weight = (
        policy['bm25_weight'] if bm25_weight is None else bm25_weight
    )
    embedding_weight = (
        policy['embedding_weight']
        if embedding_weight is None else embedding_weight
    )
    minimum_score = (
        policy['minimum_score'] if minimum_score is None else minimum_score
    )
    minimum_embedding_score = (
        policy['minimum_embedding_score']
        if minimum_embedding_score is None else minimum_embedding_score
    )
    bm25_saturation = (
        policy['bm25_saturation']
        if bm25_saturation is None else bm25_saturation
    )
    require_embedding_gate = policy.get('require_embedding_gate', False)
    reject_unknown_identifiers = policy.get(
        'reject_unknown_identifiers',
        False,
    )
    unsupported_identifiers = (
        _unsupported_identifiers(index, query)
        if reject_unknown_identifiers else []
    )
    if abs((bm25_weight + embedding_weight) - 1.0) > 1e-9:
        raise RagError('retrieval weights must sum to 1.0')
    if min(bm25_weight, embedding_weight) < 0:
        raise RagError('retrieval weights must be non-negative')
    if not 0 <= minimum_score <= 1:
        raise RagError('minimum_score must be between 0 and 1')
    if not 0 <= minimum_embedding_score <= 1:
        raise RagError('minimum_embedding_score must be between 0 and 1')
    if bm25_saturation <= 0:
        raise RagError('bm25_saturation must be positive')
    filters = dict(filters or {})
    chunks = _filter_chunks(index['chunks'], filters)
    query_terms = tokenize(query)
    bm25_scores = _bm25_scores(chunks, query_terms)
    embedding_config = index['build_config']['embedding_config']
    encoder = embedder or create_embedder(
        embedding_config,
        allow_download=allow_model_download,
        device=embedding_device,
    )
    if encoder.provider != index['build_config']['embedding_provider']:
        raise RagError('query embedder does not match index provider')
    query_vector = encoder.encode([query])[0]
    scored = []
    for chunk, raw_bm25 in zip(chunks, bm25_scores):
        normalized_bm25 = raw_bm25 / (raw_bm25 + bm25_saturation)
        embedding_score = max(0.0, _dot(query_vector, chunk['vector']))
        score = (
            bm25_weight * normalized_bm25 +
            embedding_weight * embedding_score
        )
        embedding_gate = embedding_score >= minimum_embedding_score
        evidence_gate = (
            embedding_gate if require_embedding_gate
            else raw_bm25 > 0.0 or embedding_gate
        )
        accepted = score >= minimum_score and evidence_gate
        if accepted:
            scored.append((
                score,
                raw_bm25,
                normalized_bm25,
                embedding_score,
                chunk,
            ))
    scored.sort(key=lambda item: (
        -item[0],
        item[4]['source_id'],
        item[4]['ordinal'],
    ))
    hits = []
    for rank, (score, raw_bm25, bm25, embedding, chunk) in enumerate(
        scored[:top_k],
        start=1,
    ):
        hits.append({
            'rank': rank,
            'score': round(score, 8),
            'bm25_raw_score': round(raw_bm25, 8),
            'bm25_score': round(bm25, 8),
            'embedding_score': round(embedding, 8),
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
            'algorithm': 'bm25_embedding_abstention_v2',
            'bm25_weight': bm25_weight,
            'embedding_weight': embedding_weight,
            'embedding_provider': encoder.provider,
            'minimum_score': minimum_score,
            'minimum_embedding_score': minimum_embedding_score,
            'bm25_saturation': bm25_saturation,
            'require_embedding_gate': require_embedding_gate,
            'reject_unknown_identifiers': reject_unknown_identifiers,
            'top_k': top_k,
        },
        'abstained': not hits or bool(unsupported_identifiers),
        'abstention_reason': (
            'unsupported_identifier' if unsupported_identifiers
            else 'no_candidate_above_threshold' if not hits else None
        ),
        'unsupported_identifiers': unsupported_identifiers,
        'hits': [] if unsupported_identifiers else hits,
    }
    validate_document(result, 'rag_retrieval_result', schema_dir)
    return result
