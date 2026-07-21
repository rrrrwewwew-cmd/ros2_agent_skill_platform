"""End-to-end Runtime tests for the governed route preview Skill."""

import json
from pathlib import Path
from types import SimpleNamespace

from robot_skill_registry import (
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    SkillRegistry,
)
from robot_skill_runtime import SkillExecutor
from robot_skill_runtime.adapters import SafeRoutePreviewAdapter
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / 'skills/preview_safe_route/skill.yaml'
LOCK_PATH = REPOSITORY_ROOT / 'artifacts/preview_safe_route/0.1.0.json'


class IncrementingClock:
    """Provide deterministic timestamps for release and execution."""

    def __init__(self):
        self.value = 9_000_000_000

    def __call__(self):
        self.value += 1
        return self.value


class FixedRunner:
    """Return one valid safe preview without using a live ROS graph."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_safe_result()),
            stderr='',
        )


def _safe_result():
    return {
        'schema_version': 1,
        'skill': 'preview_safe_route',
        'skill_version': '0.1.0',
        'state': 'safe',
        'safe_to_execute': True,
        'motion_command_sent': False,
        'request': {
            'goal': {
                'frame_id': 'map',
                'x': 4.5,
                'y': 0.0,
                'yaw_deg': 0.0,
            },
            'keepout_profile': 'rbot_water_puddle_v2',
        },
        'planner': {
            'action': '/compute_path_to_pose',
            'available': True,
            'error_code': 0,
            'error_message': '',
            'planning_time_ms': 10.0,
            'path_frame': 'map',
            'observed_at_ns': 123,
        },
        'route': {
            'pose_count': 3,
            'length_m': 5.0,
            'start_m': {'x': 0.0, 'y': 0.0},
            'end_m': {'x': 4.5, 'y': 0.0},
            'goal_position_error_m': 0.0,
            'path_sha256': 'a' * 64,
        },
        'keepout': {
            'profile': 'rbot_water_puddle_v2',
            'target_id': 'water_puddle',
            'source_content_sha256': 'b' * 64,
            'source_updated_at': 'timestamp',
            'center_m': {'x': 1.67, 'y': 0.0},
            'radius_m': 0.6,
            'global_center_cost': 254,
            'active_in_global_costmap': True,
            'minimum_center_distance_m': 0.9,
            'minimum_clearance_m': 0.3,
            'intersects': False,
        },
        'reasons': [],
    }


def _register_active(database, tmp_path, clock):
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding='utf-8'))
    artifact_hash = json.loads(
        LOCK_PATH.read_text(encoding='utf-8')
    )['artifact_hash']
    private_key = tmp_path / 'release.pem'
    public_key = tmp_path / 'release.pub.pem'
    generate_ed25519_keypair(private_key, public_key)
    with SkillRegistry(database, clock_ns=clock) as registry:
        record = registry.register_manifest(
            manifest, artifact_hash=artifact_hash,
        )
        current = 'DRAFT'
        for target in (
            'GENERATED', 'STATIC_VALIDATED', 'BUILT', 'UNIT_TESTED',
            'SIMULATION_TESTED',
        ):
            record = registry.advance(
                record['name'], record['version'], target, current,
                'test_pipeline', f'passed {target}',
            )
            current = target
        record = registry.approve(
            record['name'], record['version'], record['artifact_hash'],
            'test_policy', 'read-only test approval',
        )
        envelope = create_signature_envelope(
            REPOSITORY_ROOT,
            record['name'],
            record['version'],
            record['artifact_hash'],
            private_key,
            'test_signer',
            clock_ns=clock,
        )
        record = registry.record_verified_signature(
            record['name'], record['version'], record['artifact_hash'],
            canonical_json(envelope), 'test_verifier', 'verified fixture',
        )
        record = registry.advance(
            record['name'], record['version'], 'ACTIVE', 'SIGNED',
            'test_release', 'activated fixture',
        )
    return record, public_key


def test_signed_active_preview_executes_through_runtime(tmp_path):
    """The third Skill crosses the complete Registry and Runtime gate."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    record, public_key = _register_active(database, tmp_path, clock)
    runner = FixedRunner()
    adapter = SafeRoutePreviewAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )
    executor = SkillExecutor(
        database,
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
        trusted_public_key=public_key,
    )
    invocation = {
        'schema_version': 1,
        'run_id': 'preview_safe',
        'trace_id': 'trace_preview_safe',
        'skill_name': 'preview_safe_route',
        'skill_version': '0.1.0',
        'artifact_hash': record['artifact_hash'],
        'inputs': {
            'goal_x': 4.5,
            'goal_y': 0.0,
            'goal_yaw_deg': 0.0,
            'keepout_profile': 'rbot_water_puddle_v2',
        },
    }
    result = executor.execute(invocation)
    assert result['status'] == 'succeeded'
    assert result['output']['state'] == 'safe'
    assert result['output']['motion_command_sent'] is False
    assert len(runner.calls) == 1
