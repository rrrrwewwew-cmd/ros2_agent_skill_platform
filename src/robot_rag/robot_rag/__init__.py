"""Versioned, cited retrieval for the governed robot Agent."""

from robot_rag.ab_evaluation import compare_retrievers
from robot_rag.corpus import (
    build_index,
    load_embedding_profile,
    load_index,
    load_manifest,
)
from robot_rag.evaluation import evaluate_retrieval
from robot_rag.retrieval import retrieve
from robot_rag.util import RagError


__all__ = [
    'RagError',
    'build_index',
    'compare_retrievers',
    'evaluate_retrieval',
    'load_index',
    'load_embedding_profile',
    'load_manifest',
    'retrieve',
]
