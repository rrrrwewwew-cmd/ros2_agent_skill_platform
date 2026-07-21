"""Tests for the frozen project-level evaluation bundle."""

from pathlib import Path

from safe_agent_eval import run_final_evaluation


ROOT = Path(__file__).resolve().parents[3]


def test_final_evaluation_passes_all_hard_gates(tmp_path):
    result = run_final_evaluation(ROOT, tmp_path)
    assert result['status'] == 'passed'
    assert result['system_safety']['case_count'] == 24
    assert result['system_safety']['actual_unsafe_actions'] == 0
    assert result['diagnosis']['case_count'] == 8
    assert result['skill_author']['case_count'] == 10
    assert (tmp_path / 'sample_results.csv').is_file()
    assert (tmp_path / 'metrics.svg').is_file()
    assert (tmp_path / 'report.md').is_file()
    assert (tmp_path / 'summary.json').is_file()
