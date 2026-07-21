"""PEP 257 conformance test."""

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    """Check docstrings."""
    assert main(argv=['.', 'test']) == 0
