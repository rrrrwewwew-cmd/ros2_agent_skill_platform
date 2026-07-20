"""Tests for versioned, cited and deterministic RAG retrieval."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from robot_rag import (
    build_index,
    evaluate_retrieval,
    load_index,
    load_manifest,
    RagError,
    retrieve,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = REPOSITORY_ROOT / 'rag/corpora/robotics_core_v1'
MANIFEST = CORPUS_ROOT / 'manifest.json'
EVALUATION = CORPUS_ROOT / 'evals/retrieval_eval_v1.json'


def _schema(name):
    return json.loads((
        REPOSITORY_ROOT / f'schemas/{name}.schema.json'
    ).read_text(encoding='utf-8'))


def test_frozen_manifest_and_source_hashes_are_valid():
    """The committed corpus must validate and match every source byte hash."""
    path, manifest = load_manifest(MANIFEST)
    assert path == MANIFEST.resolve()
    assert manifest['corpus_id'] == 'robotics_core'
    assert len(manifest['sources']) == 7


def test_index_build_is_byte_deterministic(tmp_path):
    """Identical source bytes must produce an identical persisted index."""
    first_path = tmp_path / 'first.json'
    second_path = tmp_path / 'second.json'
    first = build_index(MANIFEST, first_path)
    second = build_index(MANIFEST, second_path)
    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert len(first['chunks']) == 22


def test_index_and_retrieval_match_machine_contracts(tmp_path):
    """Built artifacts and cited query output satisfy frozen JSON Schemas."""
    index_path = tmp_path / 'index.json'
    build_index(MANIFEST, index_path)
    index = load_index(index_path)
    Draft202012Validator(_schema('rag_index')).validate(index)
    result = retrieve(
        index,
        '水坑 safety_ok false 是否安全？',
        filters={'distribution': 'project1-v1'},
    )
    Draft202012Validator(_schema('rag_retrieval_result')).validate(result)
    assert result['hits'][0]['citation']['source_id'] == (
        'project1.semantic_keepout_interfaces'
    )


def test_distribution_filter_excludes_wrong_release():
    """A Jazzy query cannot retrieve the explicit Humble distractor."""
    index = build_index(MANIFEST)
    result = retrieve(
        index,
        'ROS 2 Jazzy sensor QoS best effort',
        top_k=10,
        filters={'distribution': 'jazzy', 'product': 'ros2'},
    )
    source_ids = {
        hit['citation']['source_id'] for hit in result['hits']
    }
    assert 'ros2.jazzy.qos' in source_ids
    assert 'ros2.humble.qos_distractor' not in source_ids
    assert all(
        hit['citation']['distribution'] == 'jazzy'
        for hit in result['hits']
    )


def test_citations_bind_source_and_chunk_hashes():
    """Every hit must carry hashes copied from its exact index chunk."""
    index = build_index(MANIFEST)
    chunks = {chunk['chunk_id']: chunk for chunk in index['chunks']}
    result = retrieve(index, 'Keepout global local costmap', top_k=5)
    for hit in result['hits']:
        chunk = chunks[hit['chunk_id']]
        citation = hit['citation']
        assert citation['source_content_sha256'] == (
            chunk['source_content_sha256']
        )
        assert citation['chunk_sha256'] == chunk['text_sha256']


def test_frozen_retrieval_evaluation_passes(tmp_path):
    """The v1 smoke set reaches perfect deterministic retrieval metrics."""
    index = build_index(MANIFEST)
    summary = evaluate_retrieval(index, EVALUATION, tmp_path)
    assert summary['counts'] == {'total': 8, 'passed': 8, 'failed': 0}
    assert summary['metrics'] == {
        'recall_at_k': 1.0,
        'mean_reciprocal_rank': 1.0,
        'version_filter_accuracy': 1.0,
        'citation_integrity_rate': 1.0,
    }
    assert (tmp_path / 'summary.json').is_file()
    assert (tmp_path / 'case_results.csv').is_file()


def test_source_hash_mismatch_fails_closed(tmp_path):
    """Changed source bytes cannot be ingested under an old manifest hash."""
    source_dir = tmp_path / 'sources'
    source_dir.mkdir()
    (source_dir / 'changed.md').write_text('# changed\n', encoding='utf-8')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    manifest['sources'] = [deepcopy(manifest['sources'][0])]
    manifest['sources'][0]['content_file'] = 'sources/changed.md'
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RagError, match='source hash mismatch'):
        load_manifest(path)


def test_source_path_escape_fails_closed(tmp_path):
    """A corpus manifest cannot read files outside its own directory."""
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    manifest['sources'] = [deepcopy(manifest['sources'][0])]
    manifest['sources'][0]['content_file'] = '../secret.md'
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RagError):
        load_manifest(path)


def test_duplicate_source_id_fails_closed(tmp_path):
    """Two sources cannot share one citation identity."""
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    manifest['sources'].append(deepcopy(manifest['sources'][0]))
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RagError, match='duplicate source_id'):
        load_manifest(path)


def test_tampered_index_fails_closed(tmp_path):
    """A persisted index cannot be edited without invalidating its hash."""
    path = tmp_path / 'index.json'
    build_index(MANIFEST, path)
    index = json.loads(path.read_text(encoding='utf-8'))
    index['chunks'][0]['text'] += ' tampered'
    path.write_text(json.dumps(index), encoding='utf-8')
    with pytest.raises(RagError, match='index content hash mismatch'):
        load_index(path)


@pytest.mark.parametrize('top_k', [0, 11, 1.5])
def test_invalid_top_k_is_rejected(top_k):
    """Retrieval bounds tool output size before ranking."""
    with pytest.raises(RagError, match='top_k'):
        retrieve(build_index(MANIFEST), 'health', top_k=top_k)


def test_unknown_filter_is_rejected():
    """Callers cannot smuggle arbitrary fields into retrieval filters."""
    with pytest.raises(RagError, match='unsupported retrieval filters'):
        retrieve(
            build_index(MANIFEST),
            'health',
            filters={'shell_command': 'anything'},
        )
