"""Versioned, cited retrieval for the governed robot Agent."""

from robot_rag.corpus import build_index, load_index, load_manifest
from robot_rag.evaluation import evaluate_retrieval
from robot_rag.retrieval import retrieve
from robot_rag.util import RagError


__all__ = [
    'RagError',
    'build_index',
    'evaluate_retrieval',
    'load_index',
    'load_manifest',
    'retrieve',
]
