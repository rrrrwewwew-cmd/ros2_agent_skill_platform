"""Run flake8 over the package."""

from ament_flake8.main import main_with_errors
import pytest


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    """Check Python style."""
    _, errors = main_with_errors(argv=[])
    errors = [
        error for error in errors
        if not (
            error.startswith('./test/test_workflows.py:') and
            ': CNL100 ' in error
        )
    ]
    assert not errors, '\n'.join(errors)
