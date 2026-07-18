"""Deterministic evidence extraction for robot experiment runs."""

import bisect
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


ANALYZER_VERSION = '0.1.0'
DEFAULT_PARAMETERS = {
    'command_match_tolerance_ns': 60_000_000,
    'commanded_speed_threshold_mps': 0.15,
    'low_progress_threshold_mps': 0.05,
    'angular_oscillation_threshold_rps': 0.5,
    'pose_jump_threshold_m': 0.5,
    'window_gap_ns': 150_000_000,
    'distance_matrix_max_points': 200,
}


class ExperimentDataError(ValueError):
    """Raised when experiment evidence is missing, unsafe, or inconsistent."""


@dataclass(frozen=True)
class PoseSample:
    """One normalized robot pose observation."""

    timestamp_ns: int
    x_m: float
    y_m: float
    yaw_rad: float
    linear_x_mps: float
    angular_z_rps: float
    nav_state: str
    recovery_count: int
    tf_ok: bool


@dataclass(frozen=True)
class CommandSample:
    """One normalized robot velocity command."""

    timestamp_ns: int
    linear_x_mps: float
    angular_z_rps: float


def sha256_file(path):
    """Return the SHA-256 digest of a file without loading it all at once."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _require_fields(mapping, fields, label):
    missing = sorted(set(fields) - set(mapping))
    if missing:
        raise ExperimentDataError(f'{label} missing fields: {missing}')


def _strictly_increasing(samples, label):
    timestamps = [sample.timestamp_ns for sample in samples]
    if any(current <= previous for previous, current in zip(
            timestamps, timestamps[1:])):
        raise ExperimentDataError(f'{label} timestamps must strictly increase')


def _parse_bool(value, field):
    normalized = str(value).strip().lower()
    if normalized not in {'true', 'false'}:
        raise ExperimentDataError(f'{field} must be true or false')
    return normalized == 'true'


def _require_finite(values, label):
    if not all(math.isfinite(value) for value in values):
        raise ExperimentDataError(f'{label} numeric values must be finite')


def load_experiment_manifest(manifest_path):
    """Load a manifest, confine its sources, and verify every source hash."""
    path = Path(manifest_path).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentDataError(f'cannot read manifest: {error}') from error
    _require_fields(
        manifest,
        {
            'schema_version', 'run_id', 'scenario', 'started_at',
            'time_base', 'frame_id', 'sources',
        },
        'manifest',
    )
    if manifest['schema_version'] != 1:
        raise ExperimentDataError('manifest schema_version must equal 1')
    if manifest['time_base'] != 'nanoseconds':
        raise ExperimentDataError('manifest time_base must be nanoseconds')
    sources = manifest['sources']
    if not isinstance(sources, dict):
        raise ExperimentDataError('manifest sources must be an object')
    _require_fields(sources, {'pose_csv', 'command_csv'}, 'sources')

    root = path.parent
    resolved = {}
    for source_name, source in sources.items():
        if not isinstance(source, dict):
            raise ExperimentDataError(f'{source_name} source must be an object')
        _require_fields(source, {'path', 'sha256'}, source_name)
        relative = Path(source['path'])
        if relative.is_absolute():
            raise ExperimentDataError(f'{source_name} path must be relative')
        source_path = (root / relative).resolve()
        if not source_path.is_relative_to(root):
            raise ExperimentDataError(f'{source_name} path escapes run directory')
        if not source_path.is_file():
            raise ExperimentDataError(f'{source_name} file does not exist')
        actual_hash = sha256_file(source_path)
        if actual_hash != source['sha256']:
            raise ExperimentDataError(f'{source_name} sha256 mismatch')
        resolved[source_name] = source_path
    return manifest, resolved


def query_experiment_runs(root_dir):
    """Return verified experiment summaries beneath an allowlisted root."""
    root = Path(root_dir).expanduser().resolve()
    if not root.is_dir():
        raise ExperimentDataError('experiment root is not a directory')
    runs = []
    for manifest_path in sorted(root.rglob('manifest.json')):
        if not manifest_path.resolve().is_relative_to(root):
            continue
        manifest, _ = load_experiment_manifest(manifest_path)
        runs.append({
            'run_id': manifest['run_id'],
            'scenario': manifest['scenario'],
            'started_at': manifest['started_at'],
            'manifest': str(manifest_path.relative_to(root)),
        })
    return runs


def _read_csv(path, required_fields):
    try:
        with Path(path).open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ExperimentDataError(f'{path} has no CSV header')
            _require_fields(reader.fieldnames, required_fields, str(path))
            return list(reader)
    except OSError as error:
        raise ExperimentDataError(f'cannot read CSV {path}: {error}') from error


def load_pose_samples(path):
    """Load normalized pose samples from a frozen CSV artifact."""
    fields = {
        'timestamp_ns', 'x_m', 'y_m', 'yaw_rad', 'linear_x_mps',
        'angular_z_rps', 'nav_state', 'recovery_count', 'tf_ok',
    }
    rows = _read_csv(path, fields)
    try:
        samples = [PoseSample(
            timestamp_ns=int(row['timestamp_ns']),
            x_m=float(row['x_m']),
            y_m=float(row['y_m']),
            yaw_rad=float(row['yaw_rad']),
            linear_x_mps=float(row['linear_x_mps']),
            angular_z_rps=float(row['angular_z_rps']),
            nav_state=row['nav_state'],
            recovery_count=int(row['recovery_count']),
            tf_ok=_parse_bool(row['tf_ok'], 'tf_ok'),
        ) for row in rows]
    except (TypeError, ValueError) as error:
        raise ExperimentDataError(f'invalid pose CSV value: {error}') from error
    if len(samples) < 2:
        raise ExperimentDataError('pose CSV requires at least two samples')
    if any(sample.timestamp_ns < 0 or sample.recovery_count < 0
           for sample in samples):
        raise ExperimentDataError(
            'pose timestamps and recovery counts must be non-negative'
        )
    for sample in samples:
        _require_finite(
            {
                sample.x_m, sample.y_m, sample.yaw_rad,
                sample.linear_x_mps, sample.angular_z_rps,
            },
            'pose',
        )
    _strictly_increasing(samples, 'pose')
    return samples


def load_command_samples(path):
    """Load normalized command samples from a frozen CSV artifact."""
    fields = {'timestamp_ns', 'linear_x_mps', 'angular_z_rps'}
    rows = _read_csv(path, fields)
    try:
        samples = [CommandSample(
            timestamp_ns=int(row['timestamp_ns']),
            linear_x_mps=float(row['linear_x_mps']),
            angular_z_rps=float(row['angular_z_rps']),
        ) for row in rows]
    except (TypeError, ValueError) as error:
        raise ExperimentDataError(f'invalid command CSV value: {error}') from error
    if not samples:
        raise ExperimentDataError('command CSV requires at least one sample')
    if any(sample.timestamp_ns < 0 for sample in samples):
        raise ExperimentDataError('command timestamps must be non-negative')
    for sample in samples:
        _require_finite(
            {sample.linear_x_mps, sample.angular_z_rps},
            'command',
        )
    _strictly_increasing(samples, 'command')
    return samples


def _distance(first, second):
    return math.hypot(first.x_m - second.x_m, first.y_m - second.y_m)


def _bounded_pose_samples(pose_samples, max_points):
    if max_points < 2:
        raise ExperimentDataError('distance matrix max_points must be >= 2')
    if len(pose_samples) > max_points:
        last = len(pose_samples) - 1
        indices = sorted({round(index * last / (max_points - 1))
                          for index in range(max_points)})
        return [pose_samples[index] for index in indices]
    return list(pose_samples)


def compute_distance_matrix(pose_samples, max_points=200):
    """Compute a bounded pairwise Euclidean position distance matrix."""
    selected = _bounded_pose_samples(pose_samples, max_points)
    return [
        [round(_distance(first, second), 6) for second in selected]
        for first in selected
    ]


def correlate_control_commands(pose_samples, command_samples,
                               tolerance_ns=60_000_000):
    """Join each pose with the nearest command and retain match latency."""
    command_times = [sample.timestamp_ns for sample in command_samples]
    correlated = []
    previous_pose = None
    for pose in pose_samples:
        insertion = bisect.bisect_left(command_times, pose.timestamp_ns)
        candidates = []
        if insertion < len(command_samples):
            candidates.append(command_samples[insertion])
        if insertion:
            candidates.append(command_samples[insertion - 1])
        command = min(
            candidates,
            key=lambda sample: abs(sample.timestamp_ns - pose.timestamp_ns),
        )
        delta_ns = abs(command.timestamp_ns - pose.timestamp_ns)
        if delta_ns > tolerance_ns:
            raise ExperimentDataError(
                f'no command within tolerance for pose {pose.timestamp_ns}'
            )
        if previous_pose is None:
            step_distance = 0.0
            observed_speed = 0.0
        else:
            step_distance = _distance(previous_pose, pose)
            elapsed_sec = (pose.timestamp_ns - previous_pose.timestamp_ns) / 1e9
            observed_speed = step_distance / elapsed_sec
        correlated.append({
            'timestamp_ns': pose.timestamp_ns,
            'x_m': pose.x_m,
            'y_m': pose.y_m,
            'step_distance_m': round(step_distance, 6),
            'observed_speed_mps': round(observed_speed, 6),
            'cmd_linear_x_mps': command.linear_x_mps,
            'cmd_angular_z_rps': command.angular_z_rps,
            'command_delta_ns': delta_ns,
            'nav_state': pose.nav_state,
            'recovery_count': pose.recovery_count,
            'tf_ok': pose.tf_ok,
        })
        previous_pose = pose
    return correlated


def _flags_for_sample(samples, index, parameters):
    if index == 0:
        return []
    current = samples[index]
    previous = samples[index - 1]
    flags = []
    if (
        abs(current['cmd_linear_x_mps']) >=
        parameters['commanded_speed_threshold_mps'] and
        current['observed_speed_mps'] <=
        parameters['low_progress_threshold_mps']
    ):
        flags.append('commanded_motion_without_progress')
    current_angular = current['cmd_angular_z_rps']
    previous_angular = previous['cmd_angular_z_rps']
    if (
        abs(current_angular) >= parameters['angular_oscillation_threshold_rps'] and
        abs(previous_angular) >= parameters['angular_oscillation_threshold_rps'] and
        current_angular * previous_angular < 0
    ):
        flags.append('angular_command_oscillation')
    if current['step_distance_m'] >= parameters['pose_jump_threshold_m']:
        flags.append('pose_discontinuity')
    if current['recovery_count'] > previous['recovery_count']:
        flags.append('nav_recovery_activity')
    if not current['tf_ok']:
        flags.append('localization_or_tf_evidence')
    return flags


def detect_anomaly_windows(correlated_samples, parameters=None):
    """Group deterministic anomaly flags into timestamp windows."""
    effective = dict(DEFAULT_PARAMETERS)
    if parameters:
        effective.update(parameters)
    flagged = []
    for index, sample in enumerate(correlated_samples):
        flags = _flags_for_sample(correlated_samples, index, effective)
        if flags:
            flagged.append((sample['timestamp_ns'], flags))
    windows = []
    for timestamp_ns, flags in flagged:
        if (
            not windows or
            timestamp_ns - windows[-1]['end_ns'] > effective['window_gap_ns']
        ):
            windows.append({
                'start_ns': timestamp_ns,
                'end_ns': timestamp_ns,
                'types': sorted(set(flags)),
                'flagged_samples': 1,
                'severity': 'medium',
            })
            continue
        window = windows[-1]
        window['end_ns'] = timestamp_ns
        window['types'] = sorted(set(window['types']).union(flags))
        window['flagged_samples'] += 1
    for window in windows:
        if {'pose_discontinuity', 'localization_or_tf_evidence'}.intersection(
                window['types']):
            window['severity'] = 'high'
    return windows


def infer_candidate_mechanisms(anomaly_windows):
    """Map deterministic flags to explicitly non-causal mechanism candidates."""
    mapping = {
        'angular_command_oscillation': 'controller_oscillation',
        'commanded_motion_without_progress': 'obstruction_or_controller_stall',
        'localization_or_tf_evidence': 'localization_or_tf_instability',
        'nav_recovery_activity': 'nav2_recovery_activity',
        'pose_discontinuity': 'localization_discontinuity',
    }
    evidence = {}
    for window_index, window in enumerate(anomaly_windows):
        for flag in window['types']:
            mechanism = mapping[flag]
            evidence.setdefault(mechanism, []).append({
                'window_index': window_index,
                'evidence_type': flag,
            })
    return [{
        'mechanism': mechanism,
        'status': 'hypothesis_candidate_not_causal_proof',
        'evidence': evidence[mechanism],
    } for mechanism in sorted(evidence)]


def analyze_experiment(manifest_path, parameters=None):
    """Run the frozen deterministic analysis over one verified experiment."""
    effective = dict(DEFAULT_PARAMETERS)
    if parameters:
        effective.update(parameters)
    manifest, sources = load_experiment_manifest(manifest_path)
    poses = load_pose_samples(sources['pose_csv'])
    commands = load_command_samples(sources['command_csv'])
    correlated = correlate_control_commands(
        poses,
        commands,
        effective['command_match_tolerance_ns'],
    )
    windows = detect_anomaly_windows(correlated, effective)
    total_distance = sum(sample['step_distance_m'] for sample in correlated)
    matrix_samples = _bounded_pose_samples(
        poses,
        effective['distance_matrix_max_points'],
    )
    return {
        'schema_version': 1,
        'analyzer_version': ANALYZER_VERSION,
        'run_id': manifest['run_id'],
        'parameters': effective,
        'source_hashes': {
            name: source['sha256']
            for name, source in sorted(manifest['sources'].items())
        },
        'summary': {
            'pose_samples': len(poses),
            'command_samples': len(commands),
            'total_distance_m': round(total_distance, 6),
            'anomaly_window_count': len(windows),
        },
        'distance_matrix_sample_timestamps_ns': [
            sample.timestamp_ns for sample in matrix_samples
        ],
        'distance_matrix_m': compute_distance_matrix(matrix_samples),
        'correlated_samples': correlated,
        'anomaly_windows': windows,
        'candidate_mechanisms': infer_candidate_mechanisms(windows),
    }


def _scale(value, minimum, maximum, output_minimum, output_maximum):
    if maximum == minimum:
        return (output_minimum + output_maximum) / 2
    ratio = (value - minimum) / (maximum - minimum)
    return output_minimum + ratio * (output_maximum - output_minimum)


def _anomaly_timestamps(analysis):
    return {
        sample['timestamp_ns']
        for sample in analysis['correlated_samples']
        if any(
            window['start_ns'] <= sample['timestamp_ns'] <= window['end_ns']
            for window in analysis['anomaly_windows']
        )
    }


def render_trajectory_svg(analysis):
    """Render a deterministic trajectory chart with anomaly samples marked."""
    samples = analysis['correlated_samples']
    xs = [sample['x_m'] for sample in samples]
    ys = [sample['y_m'] for sample in samples]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if y_max - y_min < 0.1:
        middle = (y_min + y_max) / 2
        y_min, y_max = middle - 0.05, middle + 0.05
    points = []
    for sample in samples:
        x = _scale(sample['x_m'], x_min, x_max, 60, 660)
        y = _scale(sample['y_m'], y_min, y_max, 250, 50)
        points.append(f'{x:.2f},{y:.2f}')
    anomaly_times = _anomaly_timestamps(analysis)
    markers = []
    for sample in samples:
        if sample['timestamp_ns'] not in anomaly_times:
            continue
        x = _scale(sample['x_m'], x_min, x_max, 60, 660)
        y = _scale(sample['y_m'], y_min, y_max, 250, 50)
        markers.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#dc2626"/>'
        )
    return '\n'.join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300" '
        'viewBox="0 0 720 300">',
        '<rect width="720" height="300" fill="white"/>',
        '<text x="360" y="24" text-anchor="middle" font-family="sans-serif" '
        'font-size="16">Robot trajectory and anomaly samples</text>',
        '<polyline fill="none" stroke="#2563eb" stroke-width="3" points="'
        + ' '.join(points) + '"/>',
        *markers,
        '<text x="60" y="280" font-family="sans-serif" font-size="12">'
        'Blue: trajectory; red: deterministic anomaly evidence</text>',
        '</svg>',
        '',
    ])


def render_motion_svg(analysis):
    """Render commanded and observed speed with anomaly window shading."""
    samples = analysis['correlated_samples']
    times = [sample['timestamp_ns'] for sample in samples]
    maximum_speed = max(
        max(abs(sample['cmd_linear_x_mps']), sample['observed_speed_mps'])
        for sample in samples
    )
    maximum_speed = max(maximum_speed, 0.1)

    def point(sample, field):
        x = _scale(sample['timestamp_ns'], min(times), max(times), 60, 660)
        y = _scale(abs(sample[field]), 0, maximum_speed, 250, 50)
        return f'{x:.2f},{y:.2f}'

    shading = []
    for window in analysis['anomaly_windows']:
        start = _scale(window['start_ns'], min(times), max(times), 60, 660)
        end = _scale(window['end_ns'], min(times), max(times), 60, 660)
        shading.append(
            f'<rect x="{start:.2f}" y="45" width="{max(end - start, 3):.2f}" '
            'height="210" fill="#fecaca" opacity="0.65"/>'
        )
    command_points = ' '.join(point(sample, 'cmd_linear_x_mps')
                              for sample in samples)
    observed_points = ' '.join(point(sample, 'observed_speed_mps')
                               for sample in samples)
    return '\n'.join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300" '
        'viewBox="0 0 720 300">',
        '<rect width="720" height="300" fill="white"/>',
        '<text x="360" y="24" text-anchor="middle" font-family="sans-serif" '
        'font-size="16">Commanded versus observed linear speed</text>',
        *shading,
        '<polyline fill="none" stroke="#7c3aed" stroke-width="3" points="'
        + command_points + '"/>',
        '<polyline fill="none" stroke="#059669" stroke-width="3" points="'
        + observed_points + '"/>',
        '<text x="60" y="280" font-family="sans-serif" font-size="12">'
        'Purple: command; green: observed; red shading: anomaly window</text>',
        '</svg>',
        '',
    ])


def render_markdown_report(analysis):
    """Render a concise evidence-first Markdown report."""
    summary = analysis['summary']
    lines = [
        f'# Experiment diagnosis: {analysis["run_id"]}',
        '',
        '## Deterministic summary',
        '',
        f'- Analyzer: `{analysis["analyzer_version"]}`',
        f'- Pose samples: {summary["pose_samples"]}',
        f'- Command samples: {summary["command_samples"]}',
        f'- Total trajectory distance: {summary["total_distance_m"]:.3f} m',
        f'- Anomaly windows: {summary["anomaly_window_count"]}',
        '',
        '## Anomaly windows',
        '',
        '| Start ns | End ns | Severity | Evidence types |',
        '| ---: | ---: | --- | --- |',
    ]
    for window in analysis['anomaly_windows']:
        lines.append(
            f'| {window["start_ns"]} | {window["end_ns"]} | '
            f'{window["severity"]} | {", ".join(window["types"])} |'
        )
    lines.extend([
        '',
        '## Candidate mechanisms',
        '',
        'These are evidence-linked hypotheses, not proven root causes.',
        '',
    ])
    for candidate in analysis['candidate_mechanisms']:
        lines.append(f'- `{candidate["mechanism"]}`')
    lines.extend([
        '',
        '## Charts',
        '',
        '- [Trajectory](trajectory.svg)',
        '- [Commanded versus observed speed](motion_timeseries.svg)',
        '',
    ])
    return '\n'.join(lines)


def write_analysis_artifacts(analysis, output_dir):
    """Write deterministic JSON, Markdown, and SVG evidence artifacts."""
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        'analysis_json': output / 'analysis.json',
        'report_markdown': output / 'report.md',
        'trajectory_svg': output / 'trajectory.svg',
        'motion_svg': output / 'motion_timeseries.svg',
    }
    artifacts['analysis_json'].write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    artifacts['report_markdown'].write_text(
        render_markdown_report(analysis),
        encoding='utf-8',
    )
    artifacts['trajectory_svg'].write_text(
        render_trajectory_svg(analysis),
        encoding='utf-8',
    )
    artifacts['motion_svg'].write_text(
        render_motion_svg(analysis),
        encoding='utf-8',
    )
    return artifacts
