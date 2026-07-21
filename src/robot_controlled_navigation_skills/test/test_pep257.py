"""Run pydocstyle for the controlled navigation package."""

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    """Check Python docstrings."""
    rc = main(argv=['.'])
    assert rc == 0, 'Found code style errors / warnings'
