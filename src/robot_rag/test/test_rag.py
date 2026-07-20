"""Tests for versioned, cited and deterministic RAG retrieval."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from robot_rag import (
    build_index,
    compare_retrievers,
    evaluate_retrieval,
    load_embedding_profile,
    load_index,
    load_manifest,
    RagError,
    retrieve,
)
from robot_rag.util import canonical_sha256


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = REPOSITORY_ROOT / 'rag/corpora/robotics_core_v1'
MANIFEST = CORPUS_ROOT / 'manifest.json'
EVALUATION = CORPUS_ROOT / 'evals/retrieval_eval_v1.json'
DEVELOPMENT = CORPUS_ROOT / 'evals/retrieval_dev_v2.json'
EMBEDDING_PROFILE = CORPUS_ROOT / 'profiles/bge_m3_dense_v1.json'
EMBEDDING_PROFILE_V2 = CORPUS_ROOT / 'profiles/bge_m3_dense_v2.json'


class _FakeLearnedEmbedder:
    """Tiny injected encoder for learned-provider contract tests."""

    provider = 'bge_m3_transformers_v1'
    dimensions = 1024

    @staticmethod
    def encode(texts):
        vectors = []
        for text in texts:
            seed = sum(text.encode('utf-8')) % 1024
            vector = [0.0] * 1024
            vector[seed] = 1.0
            vectors.append(vector)
        return vectors


def _schema(name):
    return json.loads((
        REPOSITORY_ROOT / f'schemas/{name}.schema.json'
    ).read_text(encoding='utf-8'))


def test_frozen_manifest_and_source_hashes_are_valid():
    """The committed corpus must validate and match every source byte hash."""
    path, manifest = load_manifest(MANIFEST)
    assert path == MANIFEST.resolve()
    assert manifest['corpus_id'] == 'robotics_core'
    assert manifest['corpus_version'] == '1.1.0'
    assert len(manifest['sources']) == 13


def test_index_build_is_byte_deterministic(tmp_path):
    """Identical source bytes must produce an identical persisted index."""
    first_path = tmp_path / 'first.json'
    second_path = tmp_path / 'second.json'
    first = build_index(MANIFEST, first_path)
    second = build_index(MANIFEST, second_path)
    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert len(first['chunks']) == 41


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
    """The v1 smoke remains valid under calibrated hybrid scoring."""
    index = build_index(MANIFEST)
    summary = evaluate_retrieval(index, EVALUATION, tmp_path)
    assert summary['counts'] == {'total': 8, 'passed': 8, 'failed': 0}
    assert summary['metrics']['recall_at_k'] == 1.0
    assert summary['metrics']['mean_reciprocal_rank'] >= 0.9
    assert summary['metrics']['version_filter_accuracy'] == 1.0
    assert summary['metrics']['citation_integrity_rate'] == 1.0
    assert summary['metrics']['answerability_accuracy'] == 1.0
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


def test_embedding_profile_is_bound_to_manifest_bytes():
    """A learned model profile cannot silently target different sources."""
    _, profile = load_embedding_profile(EMBEDDING_PROFILE, MANIFEST)
    assert profile['embedding']['model_revision'] == (
        '5617a9f61b028005a4858fdac845db406aefb181'
    )


def test_learned_profile_build_accepts_only_matching_embedder():
    """Injected test encoders must match the pinned provider and dimensions."""
    index = build_index(
        MANIFEST,
        embedding_profile_path=EMBEDDING_PROFILE,
        embedder=_FakeLearnedEmbedder(),
    )
    assert index['build_config']['embedding_profile_id'] == 'bge_m3_dense_v1'
    assert index['build_config']['embedding_provider'] == (
        'bge_m3_transformers_v1'
    )
    assert index['build_config']['embedding_dimensions'] == 1024
    assert len(index['chunks'][0]['vector']) == 1024


def test_inconsistent_embedding_metadata_fails_closed(tmp_path):
    """A valid outer hash cannot hide conflicting provider metadata."""
    path = tmp_path / 'index.json'
    index = build_index(MANIFEST)
    index['build_config']['embedding_provider'] = 'bge_m3_transformers_v1'
    unsigned = dict(index)
    del unsigned['index_content_sha256']
    index['index_content_sha256'] = canonical_sha256(unsigned)
    path.write_text(json.dumps(index), encoding='utf-8')
    with pytest.raises(RagError, match='provider metadata'):
        load_index(path)


def test_unknown_question_abstains_instead_of_citing_interface():
    """No-answer policy must not invent an unsupported battery threshold."""
    result = retrieve(
        build_index(MANIFEST),
        '该项目电池 SOC 自动返航阈值是多少？',
        filters={'distribution': 'project2-v1'},
    )
    assert result['abstained'] is True
    assert result['hits'] == []


def test_learned_policy_rejects_unknown_interface_identifier():
    """An uncovered technical identifier must fail closed before citation."""
    embedder = _FakeLearnedEmbedder()
    index = build_index(
        MANIFEST,
        embedding_profile_path=EMBEDDING_PROFILE_V2,
        embedder=embedder,
    )
    result = retrieve(
        index,
        'micro-ROS 的 MCU 传输延迟阈值是多少？',
        embedder=embedder,
    )
    assert result['abstained'] is True
    assert result['abstention_reason'] == 'unsupported_identifier'
    assert result['unsupported_identifiers'] == ['mcu', 'micro-ros']
    assert result['hits'] == []


@pytest.mark.parametrize(
    'query',
    [
        'safety_ok=false 时机器人是否还能继续规划？',
        'GroundingDINO 和 Qwen-VL 在级联中分别负责什么？',
        'Why must the report use an evidence-backed hypothesis?',
        'Which interface fits asynchronous one-way camera data?',
    ],
)
def test_identifier_gate_accepts_documented_identifier_variants(query):
    """Paths and versioned model names satisfy their shorter query forms."""
    embedder = _FakeLearnedEmbedder()
    index = build_index(
        MANIFEST,
        embedding_profile_path=EMBEDDING_PROFILE_V2,
        embedder=embedder,
    )
    result = retrieve(index, query, embedder=embedder)
    assert result['abstention_reason'] != 'unsupported_identifier'
    assert result['unsupported_identifiers'] == []


def test_development_manifest_contains_answerable_and_no_answer_cases():
    """The frozen development split exercises both retrieval outcomes."""
    manifest = json.loads(DEVELOPMENT.read_text(encoding='utf-8'))
    assert len(manifest['cases']) == 20
    assert sum(case['expected_answerable'] for case in manifest['cases']) == 16


def test_ab_evaluation_compares_identical_frozen_cases(tmp_path):
    """A/B evidence records both exact indexes and deterministic deltas."""
    index = build_index(MANIFEST)
    result = compare_retrievers(
        index,
        index,
        DEVELOPMENT,
        'unit_test_baseline_tie',
        tmp_path,
    )
    assert result['winner'] == 'tie'
    assert result['acceptance']['passed'] is True
    assert all(value == 0.0 for value in result['metric_delta'].values())
    assert (tmp_path / 'comparison.json').is_file()
