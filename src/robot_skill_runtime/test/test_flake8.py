"""Run flake8 through the standard ament test hook."""

from ament_flake8.main import main_with_errors
import pytest


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    """Check Python style."""
    return_code, errors = main_with_errors(argv=[])
    assert return_code == 0, '\n'.join(errors)
