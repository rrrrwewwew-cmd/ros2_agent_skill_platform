"""Tests for deterministic robot experiment evidence analysis."""

import json
from pathlib import Path
import shutil

import pytest
from safe_agent_core import (
    analyze_experiment,
    ExperimentDataError,
    query_experiment_runs,
)
from safe_agent_core.experiment_analytics import (
    sha256_file,
    write_analysis_artifacts,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPOSITORY_ROOT / 'examples/experiment_jitter_v1'
MANIFEST = FIXTURE_DIR / 'manifest.json'


def test_query_returns_only_verified_run():
    """The experiment query returns a hash-verified run summary."""
    runs = query_experiment_runs(REPOSITORY_ROOT / 'examples')
    assert runs == [{
        'run_id': 'jitter_demo_001',
        'scenario': 'controller_jitter_fixture',
        'started_at': '2026-07-18T14:00:00+08:00',
        'manifest': 'experiment_jitter_v1/manifest.json',
    }]


def test_jitter_fixture_detects_expected_evidence_window():
    """The frozen fixture exposes low progress and alternating commands."""
    analysis = analyze_experiment(MANIFEST)
    assert analysis['summary']['anomaly_window_count'] == 1
    window = analysis['anomaly_windows'][0]
    assert window['start_ns'] == 1_400_000_000
    assert window['end_ns'] == 1_800_000_000
    assert window['types'] == [
        'angular_command_oscillation',
        'commanded_motion_without_progress',
        'nav_recovery_activity',
    ]
    mechanisms = {
        candidate['mechanism']
        for candidate in analysis['candidate_mechanisms']
    }
    assert mechanisms == {
        'controller_oscillation',
        'nav2_recovery_activity',
        'obstruction_or_controller_stall',
    }


def test_distance_matrix_and_control_join_are_auditable():
    """Matrix symmetry and command-match latency remain explicit."""
    analysis = analyze_experiment(MANIFEST)
    matrix = analysis['distance_matrix_m']
    assert len(matrix) == 12
    assert analysis['distance_matrix_sample_timestamps_ns'][0] == 1_000_000_000
    assert analysis['distance_matrix_sample_timestamps_ns'][-1] == 2_100_000_000
    assert all(matrix[index][index] == 0 for index in range(len(matrix)))
    assert all(
        matrix[row][column] == matrix[column][row]
        for row in range(len(matrix))
        for column in range(len(matrix))
    )
    assert matrix[0][-1] == 0.12
    assert all(
        sample['command_delta_ns'] == 0
        for sample in analysis['correlated_samples']
    )


def test_report_artifacts_are_deterministic(tmp_path):
    """Repeated runs over identical evidence produce byte-identical reports."""
    analysis = analyze_experiment(MANIFEST)
    first = write_analysis_artifacts(analysis, tmp_path / 'first')
    second = write_analysis_artifacts(analysis, tmp_path / 'second')
    assert set(first) == set(second)
    for name in first:
        assert first[name].read_bytes() == second[name].read_bytes()
    report = first['report_markdown'].read_text(encoding='utf-8')
    assert 'not proven root causes' in report


def test_modified_source_fails_hash_verification(tmp_path):
    """Analysis fails closed when an input artifact no longer matches its hash."""
    copied = tmp_path / 'run'
    shutil.copytree(FIXTURE_DIR, copied)
    command_path = copied / 'command.csv'
    command_path.write_text(
        command_path.read_text(encoding='utf-8') + '\n',
        encoding='utf-8',
    )
    with pytest.raises(ExperimentDataError, match='sha256 mismatch'):
        analyze_experiment(copied / 'manifest.json')


def test_source_path_cannot_escape_run_directory(tmp_path):
    """A manifest cannot turn the read-only tool into arbitrary file access."""
    copied = tmp_path / 'run'
    shutil.copytree(FIXTURE_DIR, copied)
    outside = tmp_path / 'outside.csv'
    shutil.copy(FIXTURE_DIR / 'command.csv', outside)
    manifest_path = copied / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['sources']['command_csv']['path'] = '../outside.csv'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExperimentDataError, match='escapes run directory'):
        analyze_experiment(manifest_path)


def test_invalid_boolean_fails_closed_after_hash_update(tmp_path):
    """Malformed typed values cannot silently become valid observations."""
    copied = tmp_path / 'run'
    shutil.copytree(FIXTURE_DIR, copied)
    pose_path = copied / 'pose.csv'
    pose_text = pose_path.read_text(encoding='utf-8').replace(
        ',NAVIGATING,0,true',
        ',NAVIGATING,0,unknown',
        1,
    )
    pose_path.write_text(pose_text, encoding='utf-8')
    manifest_path = copied / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['sources']['pose_csv']['sha256'] = sha256_file(pose_path)
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExperimentDataError, match='must be true or false'):
        analyze_experiment(manifest_path)
