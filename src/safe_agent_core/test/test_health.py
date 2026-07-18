"""Tests for deterministic read-only robot health policy."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from safe_agent_core.health import (
    check_robot_health,
    evaluate_health_snapshot,
    HealthEvidenceError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NOW_NS = 10_000_000_000


def healthy_snapshot():
    """Return fresh evidence for every safety-critical source."""
    return {
        'observed_at_ns': NOW_NS,
        'nav2': {
            'response_received': True,
            'active': True,
            'message': 'Managed nodes are active',
        },
        'transform': {
            'available': True,
            'stamp_ns': NOW_NS - 100_000_000,
            'target_frame': 'map',
            'source_frame': 'base_footprint',
        },
        'semantic_safety': {
            'topic_received': True,
            'topic_ok': True,
            'diagnostic_received': True,
            'diagnostic_level': 0,
            'diagnostic_message': 'Robot is outside the keepout zone',
            'diagnostic_stamp_ns': NOW_NS - 200_000_000,
        },
        'sensors': {
            '/scan': {
                'publisher_count': 1,
                'message_received': True,
                'stamp_ns': NOW_NS - 50_000_000,
                'types': ['sensor_msgs/msg/LaserScan'],
            },
        },
    }


def test_healthy_snapshot_allows_required_sensor_precondition():
    """Fresh lifecycle, TF, safety, and sensor evidence pass."""
    result = evaluate_health_snapshot(
        healthy_snapshot(), required_sensors=['/scan'],
    )
    assert result['state'] == 'healthy'
    assert result['safe_to_proceed'] is True
    assert all(check['status'] == 'pass' for check in result['checks'])
    schema = json.loads(
        (REPOSITORY_ROOT / 'schemas/robot_health_result.schema.json')
        .read_text(encoding='utf-8')
    )
    Draft202012Validator(schema).validate(result)


def test_stale_transform_fails_closed_as_unsafe():
    """A stale map-to-robot transform blocks downstream movement."""
    snapshot = healthy_snapshot()
    snapshot['transform']['stamp_ns'] = NOW_NS - 2_000_000_000
    result = evaluate_health_snapshot(snapshot, max_tf_age_sec=0.5)
    assert result['state'] == 'unsafe'
    assert result['safe_to_proceed'] is False
    assert 'transform stamp is stale' in result['reasons'][0]


@pytest.mark.parametrize(
    'missing_field', ['topic_received', 'diagnostic_received'],
)
def test_missing_semantic_safety_evidence_is_unsafe(missing_field):
    """Either half of semantic safety evidence is mandatory."""
    snapshot = healthy_snapshot()
    snapshot['semantic_safety'][missing_field] = False
    result = evaluate_health_snapshot(snapshot)
    assert result['state'] == 'unsafe'
    assert any('missing' in reason for reason in result['reasons'])


def test_missing_required_sensor_is_degraded_but_not_hidden():
    """A missing task sensor blocks readiness without claiming danger."""
    snapshot = healthy_snapshot()
    snapshot['sensors']['/camera/image'] = {
        'publisher_count': 0,
        'message_received': False,
    }
    result = evaluate_health_snapshot(
        snapshot, required_sensors=['/camera/image'],
    )
    assert result['state'] == 'degraded'
    assert result['safe_to_proceed'] is False
    assert result['checks'][-1]['name'] == 'sensor:/camera/image'


def test_future_timestamp_is_rejected_as_inconsistent_evidence():
    """Evidence from a different or future clock cannot pass freshness."""
    snapshot = healthy_snapshot()
    snapshot['transform']['stamp_ns'] = NOW_NS + 1
    result = evaluate_health_snapshot(snapshot)
    assert result['state'] == 'unsafe'
    assert 'ahead of the observation clock' in result['reasons'][0]


def test_adapter_entrypoint_uses_typed_snapshot():
    """The manifest entrypoint delegates collection through its adapter."""
    class FakeAdapter:
        def collect(self, required_sensors=None):
            assert required_sensors == ['/scan']
            return healthy_snapshot()

    result = check_robot_health(['/scan'], adapter=FakeAdapter())
    assert result['state'] == 'healthy'


def test_invalid_sensor_name_is_rejected_before_policy_use():
    """Relative names cannot broaden the declared ROS read boundary."""
    with pytest.raises(HealthEvidenceError, match='absolute ROS topic'):
        evaluate_health_snapshot(
            healthy_snapshot(), required_sensors=['scan'],
        )


def test_unapproved_absolute_sensor_topic_is_rejected():
    """Absolute names remain bounded by the manifest permission allowlist."""
    with pytest.raises(HealthEvidenceError, match='unapproved topics'):
        evaluate_health_snapshot(
            healthy_snapshot(), required_sensors=['/private/raw_topic'],
        )
