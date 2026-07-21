"""Deterministic policy for the read-only robot health Skill."""

from collections.abc import Mapping


HEALTH_STATES = {'healthy', 'degraded', 'unsafe'}
CHECK_STATUSES = {'pass', 'fail'}
ALLOWED_SENSOR_TOPICS = {
    '/camera/camera_info',
    '/camera/depth_image',
    '/camera/image',
    '/imu',
    '/odom',
    '/scan',
}


class HealthEvidenceError(ValueError):
    """Raised when typed health evidence or policy inputs are malformed."""


def _non_negative_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HealthEvidenceError(
            f'{field} must be a non-negative integer'
        )
    return value


def _positive_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HealthEvidenceError(f'{field} must be numeric')
    value = float(value)
    if value <= 0:
        raise HealthEvidenceError(f'{field} must be greater than zero')
    return value


def validate_required_sensors(required_sensors):
    """Return unique sensor topics restricted to the Skill allowlist."""
    if required_sensors is None:
        return []
    if not isinstance(required_sensors, (list, tuple)):
        raise HealthEvidenceError('required_sensors must be an array')
    topics = []
    for topic in required_sensors:
        if not isinstance(topic, str) or not topic.startswith('/'):
            raise HealthEvidenceError(
                'required_sensors entries must be absolute ROS topic names'
            )
        topics.append(topic)
    if len(topics) != len(set(topics)):
        raise HealthEvidenceError('required_sensors must not contain duplicates')
    unapproved = sorted(set(topics) - ALLOWED_SENSOR_TOPICS)
    if unapproved:
        raise HealthEvidenceError(
            f'required_sensors contains unapproved topics: {unapproved}'
        )
    return topics


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _stamp_age(now_ns, stamp_ns, field, maximum_age_sec):
    stamp_ns = _non_negative_integer(stamp_ns, field)
    delta_ns = now_ns - stamp_ns
    if delta_ns < 0:
        return None, f'{field} is ahead of the observation clock'
    age_sec = delta_ns / 1_000_000_000
    if age_sec > maximum_age_sec:
        return age_sec, (
            f'{field} is stale ({age_sec:.3f}s > '
            f'{maximum_age_sec:.3f}s)'
        )
    return age_sec, None


def _check(name, status, critical, observed_at_ns, reason, evidence):
    if status not in CHECK_STATUSES:
        raise HealthEvidenceError(f'unsupported check status: {status}')
    return {
        'name': name,
        'status': status,
        'safety_critical': critical,
        'observed_at_ns': observed_at_ns,
        'reason': reason,
        'evidence': evidence,
    }


def _nav2_check(snapshot, now_ns):
    evidence = _mapping(snapshot.get('nav2'))
    received = evidence.get('response_received') is True
    active = evidence.get('active') is True
    if not received:
        return _check(
            'nav2_active', 'fail', True, now_ns,
            'Nav2 lifecycle health response is missing', dict(evidence),
        )
    if not active:
        return _check(
            'nav2_active', 'fail', True, now_ns,
            'Nav2 managed nodes are not active', dict(evidence),
        )
    return _check(
        'nav2_active', 'pass', True, now_ns,
        'Nav2 managed nodes are active', dict(evidence),
    )


def _transform_check(snapshot, now_ns, maximum_age_sec):
    evidence = _mapping(snapshot.get('transform'))
    if evidence.get('available') is not True:
        return _check(
            'map_to_robot_transform', 'fail', True, now_ns,
            'Required map-to-robot transform is missing', dict(evidence),
        )
    stamp_ns = evidence.get('stamp_ns')
    try:
        age_sec, error = _stamp_age(
            now_ns, stamp_ns, 'transform stamp', maximum_age_sec,
        )
    except HealthEvidenceError as exception:
        age_sec, error = None, str(exception)
    normalized = dict(evidence)
    normalized['age_sec'] = age_sec
    if error:
        return _check(
            'map_to_robot_transform', 'fail', True, now_ns,
            error, normalized,
        )
    return _check(
        'map_to_robot_transform', 'pass', True, stamp_ns,
        'Required transform is available and fresh', normalized,
    )


def _semantic_safety_check(snapshot, now_ns, maximum_age_sec):
    evidence = _mapping(snapshot.get('semantic_safety'))
    if evidence.get('topic_received') is not True:
        return _check(
            'semantic_keepout_safety', 'fail', True, now_ns,
            'Semantic Keepout safety topic evidence is missing',
            dict(evidence),
        )
    if evidence.get('diagnostic_received') is not True:
        return _check(
            'semantic_keepout_safety', 'fail', True, now_ns,
            'Matching semantic safety diagnostic is missing',
            dict(evidence),
        )
    diagnostic_stamp_ns = evidence.get('diagnostic_stamp_ns')
    try:
        age_sec, error = _stamp_age(
            now_ns,
            diagnostic_stamp_ns,
            'semantic safety diagnostic stamp',
            maximum_age_sec,
        )
    except HealthEvidenceError as exception:
        age_sec, error = None, str(exception)
    normalized = dict(evidence)
    normalized['diagnostic_age_sec'] = age_sec
    if error:
        return _check(
            'semantic_keepout_safety', 'fail', True, now_ns,
            error, normalized,
        )
    if evidence.get('topic_ok') is not True:
        return _check(
            'semantic_keepout_safety', 'fail', True, now_ns,
            'Semantic Keepout safety monitor reports unsafe', normalized,
        )
    if evidence.get('diagnostic_level') != 0:
        return _check(
            'semantic_keepout_safety', 'fail', True, now_ns,
            'Semantic safety diagnostic is not OK', normalized,
        )
    return _check(
        'semantic_keepout_safety', 'pass', True,
        diagnostic_stamp_ns,
        'Semantic Keepout safety evidence is current and OK', normalized,
    )


def _sensor_check(topic, snapshot, now_ns, maximum_age_sec):
    sensors = _mapping(snapshot.get('sensors'))
    evidence = _mapping(sensors.get(topic))
    if evidence.get('publisher_count', 0) < 1:
        return _check(
            f'sensor:{topic}', 'fail', False, now_ns,
            f'Required sensor {topic} has no publisher', dict(evidence),
        )
    if evidence.get('message_received') is not True:
        return _check(
            f'sensor:{topic}', 'fail', False, now_ns,
            f'Required sensor {topic} has no recent message', dict(evidence),
        )
    stamp_ns = evidence.get('stamp_ns')
    try:
        age_sec, error = _stamp_age(
            now_ns, stamp_ns, f'{topic} message stamp', maximum_age_sec,
        )
    except HealthEvidenceError as exception:
        age_sec, error = None, str(exception)
    normalized = dict(evidence)
    normalized['age_sec'] = age_sec
    if error:
        return _check(
            f'sensor:{topic}', 'fail', False, now_ns, error, normalized,
        )
    return _check(
        f'sensor:{topic}', 'pass', False, stamp_ns,
        f'Required sensor {topic} is publishing fresh data', normalized,
    )


def evaluate_health_snapshot(
        snapshot,
        required_sensors=None,
        max_tf_age_sec=0.5,
        max_diagnostic_age_sec=2.0,
        max_sensor_age_sec=1.0):
    """Evaluate a typed evidence snapshot using fail-closed policy."""
    if not isinstance(snapshot, Mapping):
        raise HealthEvidenceError('snapshot must be an object')
    now_ns = _non_negative_integer(
        snapshot.get('observed_at_ns'), 'observed_at_ns',
    )
    required_sensors = validate_required_sensors(required_sensors)
    max_tf_age_sec = _positive_number(max_tf_age_sec, 'max_tf_age_sec')
    max_diagnostic_age_sec = _positive_number(
        max_diagnostic_age_sec, 'max_diagnostic_age_sec',
    )
    max_sensor_age_sec = _positive_number(
        max_sensor_age_sec, 'max_sensor_age_sec',
    )

    checks = [
        _nav2_check(snapshot, now_ns),
        _transform_check(snapshot, now_ns, max_tf_age_sec),
        _semantic_safety_check(
            snapshot, now_ns, max_diagnostic_age_sec,
        ),
    ]
    checks.extend(
        _sensor_check(topic, snapshot, now_ns, max_sensor_age_sec)
        for topic in required_sensors
    )
    failed = [check for check in checks if check['status'] == 'fail']
    if any(check['safety_critical'] for check in failed):
        state = 'unsafe'
    elif failed:
        state = 'degraded'
    else:
        state = 'healthy'
    return {
        'schema_version': 1,
        'skill': 'check_robot_health',
        'skill_version': '0.2.0',
        'observation_timestamp_ns': now_ns,
        'state': state,
        'safe_to_proceed': state == 'healthy',
        'checks': checks,
        'reasons': [check['reason'] for check in failed],
    }


def check_robot_health(required_sensors=None, adapter=None, **policy):
    """Collect ROS evidence through an adapter and return a health result."""
    if adapter is None:
        from .health_ros import collect_ros_health_snapshot
        snapshot = collect_ros_health_snapshot(
            required_sensors=required_sensors,
        )
    else:
        snapshot = adapter.collect(required_sensors=required_sensors)
    configuration = _mapping(snapshot.get('configuration'))
    for key in (
        'max_tf_age_sec',
        'max_diagnostic_age_sec',
        'max_sensor_age_sec',
    ):
        if key not in policy and key in configuration:
            policy[key] = configuration[key]
    return evaluate_health_snapshot(
        snapshot,
        required_sensors=required_sensors,
        **policy,
    )
