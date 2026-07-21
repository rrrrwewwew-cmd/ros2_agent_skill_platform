"""Run pydocstyle through the standard ament test hook."""

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    """Check docstring style."""
    assert main(argv=['.', 'test']) == 0
