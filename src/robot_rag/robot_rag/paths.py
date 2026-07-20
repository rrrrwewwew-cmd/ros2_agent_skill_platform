"""Installed default paths for robot_rag CLI commands."""

from pathlib import Path

from robot_rag.util import RagError


def default_corpus_root():
    """Return the installed versioned corpus root."""
    try:
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('robot_rag'))
    except (ImportError, LookupError) as error:
        raise RagError('robot_rag package share is unavailable') from error
    return share / 'corpora/robotics_core_v1'


def default_index_path():
    """Return the operator-local default deterministic index path."""
    return Path('~/.ros/robot_agent/rag/robotics_core_v1/index.json').expanduser()
