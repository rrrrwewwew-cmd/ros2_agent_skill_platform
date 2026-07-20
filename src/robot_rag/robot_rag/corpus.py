"""Versioned corpus validation and deterministic index construction."""

import json
from pathlib import Path

from robot_rag.chunking import chunk_markdown
from robot_rag.util import (
    canonical_sha256,
    feature_hash_vector,
    RagError,
    sha256_bytes,
    sha256_text,
    tokenize,
    validate_document,
    write_json,
)


def _read_json(path, label):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise RagError(f'cannot read {label}: {error}') from error


def load_manifest(path, schema_dir=None):
    """Load a source manifest and verify every local source byte hash."""
    manifest_path = Path(path).expanduser().resolve()
    manifest = _read_json(manifest_path, 'RAG source manifest')
    validate_document(manifest, 'rag_source_manifest', schema_dir)
    source_ids = [source['source_id'] for source in manifest['sources']]
    if len(source_ids) != len(set(source_ids)):
        raise RagError('RAG source manifest contains duplicate source_id')
    root = manifest_path.parent.resolve()
    for source in manifest['sources']:
        content_path = (root / source['content_file']).resolve()
        try:
            content_path.relative_to(root)
        except ValueError as error:
            raise RagError(
                f"source {source['source_id']} escapes the corpus directory"
            ) from error
        try:
            content = content_path.read_bytes()
        except OSError as error:
            raise RagError(
                f"cannot read source {source['source_id']}: {error}"
            ) from error
        actual = sha256_bytes(content)
        if actual != source['content_sha256']:
            raise RagError(
                f"source hash mismatch for {source['source_id']}: "
                f"expected {source['content_sha256']}, got {actual}"
            )
    return manifest_path, manifest


def build_index(manifest_path, output_path=None, schema_dir=None):
    """Build a deterministic JSON index from one verified corpus manifest."""
    path, manifest = load_manifest(manifest_path, schema_dir)
    config = manifest['chunking']
    dimensions = manifest['embedding']['dimensions']
    chunks = []
    for source in manifest['sources']:
        content_path = path.parent / source['content_file']
        markdown = content_path.read_text(encoding='utf-8')
        source_chunks = chunk_markdown(
            markdown,
            config['max_terms'],
            config['overlap_terms'],
        )
        for ordinal, chunk in enumerate(source_chunks):
            text = chunk['text']
            chunks.append({
                'chunk_id': f"{source['source_id']}:{ordinal:03d}",
                'source_id': source['source_id'],
                'source_version': source['version'],
                'source_type': source['source_type'],
                'source_content_sha256': source['content_sha256'],
                'product': source['product'],
                'distribution': source['distribution'],
                'canonical_url': source['canonical_url'],
                'ordinal': ordinal,
                'heading': chunk['heading'],
                'text': text,
                'text_sha256': sha256_text(text),
                'terms': tokenize(text),
                'vector': feature_hash_vector(text, dimensions),
            })
    index = {
        'schema_version': 1,
        'corpus_id': manifest['corpus_id'],
        'corpus_version': manifest['corpus_version'],
        'manifest_sha256': sha256_bytes(path.read_bytes()),
        'build_config': {
            'splitter': config['splitter'],
            'max_terms': config['max_terms'],
            'overlap_terms': config['overlap_terms'],
            'embedding_provider': manifest['embedding']['provider'],
            'embedding_dimensions': dimensions,
        },
        'chunks': chunks,
    }
    index['index_content_sha256'] = canonical_sha256(index)
    validate_document(index, 'rag_index', schema_dir)
    if output_path is not None:
        write_json(output_path, index)
    return index


def load_index(path, schema_dir=None):
    """Load an index and fail closed on artifact or chunk tampering."""
    index = _read_json(Path(path).expanduser(), 'RAG index')
    validate_document(index, 'rag_index', schema_dir)
    claimed = index['index_content_sha256']
    unsigned = dict(index)
    del unsigned['index_content_sha256']
    actual = canonical_sha256(unsigned)
    if claimed != actual:
        raise RagError(
            f'index content hash mismatch: expected {claimed}, got {actual}'
        )
    dimensions = index['build_config']['embedding_dimensions']
    chunk_ids = set()
    for chunk in index['chunks']:
        if chunk['chunk_id'] in chunk_ids:
            raise RagError(f"duplicate chunk_id {chunk['chunk_id']}")
        chunk_ids.add(chunk['chunk_id'])
        if sha256_text(chunk['text']) != chunk['text_sha256']:
            raise RagError(f"chunk hash mismatch for {chunk['chunk_id']}")
        if len(chunk['vector']) != dimensions:
            raise RagError(f"vector size mismatch for {chunk['chunk_id']}")
    return index
