"""End-to-end Runtime tests for one-time approved navigation."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from robot_controlled_navigation_skills.navigation import (
    navigate_to_approved_pose,
    normalize_navigation_request,
)
from robot_skill_registry import (
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    SkillRegistry,
)
from robot_skill_runtime import SkillExecutor
from robot_skill_runtime.adapters import ApprovedNavigationAdapter
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPOSITORY_ROOT / 'skills/navigate_to_approved_pose/skill.yaml'
)
LOCK_PATH = (
    REPOSITORY_ROOT / 'artifacts/navigate_to_approved_pose/0.1.0.json'
)


class IncrementingClock:
    """Provide deterministic timestamps for approval and execution."""

    def __init__(self):
        self.value = 20_000_000_000

    def __call__(self):
        self.value += 1
        return self.value


class FixedRunner:
    """Return a valid successful navigation without a live ROS graph."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_success_result()),
            stderr='',
        )


def _inputs():
    return {
        'goal_x': 4.5,
        'goal_y': 0.0,
        'goal_yaw_deg': 0.0,
        'keepout_profile': 'rbot_water_puddle_v2',
        'approved_path_sha256': 'a' * 64,
        'approved_semantic_map_sha256': 'b' * 64,
    }


def _success_result():
    request = normalize_navigation_request(
        4.5, 0.0, 0.0, 'rbot_water_puddle_v2', 'a' * 64, 'b' * 64,
    )
    health = {
        'state': 'healthy',
        'safe_to_proceed': True,
        'observation_timestamp_ns': 100,
    }
    preview = {
        'state': 'safe',
        'safe_to_execute': True,
        'motion_command_sent': False,
        'request': {
            'goal': request['goal'],
            'keepout_profile': request['keepout_profile'],
        },
        'planner': {'observed_at_ns': 101},
        'route': {'path_sha256': 'a' * 64},
        'keepout': {
            'source_content_sha256': 'b' * 64,
            'center_m': {'x': 1.67, 'y': 0.0},
            'radius_m': 0.6,
            'active_in_global_costmap': True,
            'global_center_cost': 254,
            'minimum_clearance_m': 0.3,
        },
    }
    navigation = {
        'action': '/navigate_to_pose',
        'goal_accepted': True,
        'result_status': 4,
        'nav2_error_code': 0,
        'nav2_error_message': '',
        'started_at_ns': 110,
        'completed_at_ns': 200,
        'cancel_requested': False,
    }
    postcondition = {
        'final_pose': {
            'frame_id': 'map',
            'x': 4.5,
            'y': 0.0,
            'yaw_deg': 0.0,
            'observed_at_ns': 201,
        },
        'goal_position_error_m': 0.0,
        'goal_yaw_error_deg': 0.0,
        'minimum_center_distance_m': 0.9,
        'entered_keepout': False,
        'safety_remained_ok': True,
        'robot_stopped': True,
        'final_linear_speed_mps': 0.0,
        'final_angular_speed_rps': 0.0,
    }
    return navigate_to_approved_pose(
        request, health, preview, navigation, postcondition,
    )


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
            'human_test_reviewer', 'controlled test release approval',
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


def _invocation(artifact_hash, approval=True):
    invocation = {
        'schema_version': 1,
        'run_id': 'run_nav_approved_001',
        'trace_id': 'trace_nav_approved_001',
        'skill_name': 'navigate_to_approved_pose',
        'skill_version': '0.1.0',
        'artifact_hash': artifact_hash,
        'inputs': _inputs(),
    }
    if approval:
        invocation['approval_id'] = 'approval_nav_approved_001'
    return invocation


def _executor(database, tmp_path, clock, public_key, runner):
    adapter = ApprovedNavigationAdapter(
        REPOSITORY_ROOT, use_sim_time=True, runner=runner,
    )
    return SkillExecutor(
        database,
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
        trusted_public_key=public_key,
    )


def test_exact_approval_crosses_waiting_state_and_is_consumed(tmp_path):
    """The controlled Skill cannot skip the durable approval state."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    record, public_key = _register_active(database, tmp_path, clock)
    invocation = _invocation(record['artifact_hash'])
    with SkillRegistry(database, clock) as registry:
        registry.issue_execution_approval(
            invocation,
            'human_li',
            'approved exact simulated pose goal',
            ttl_sec=60.0,
        )
    runner = FixedRunner()
    result = _executor(
        database, tmp_path, clock, public_key, runner,
    ).execute(invocation)
    assert result['status'] == 'succeeded'
    assert result['output']['state'] == 'succeeded'
    assert len(runner.calls) == 1
    events = [
        json.loads(line)
        for line in Path(result['trace_file']).read_text(
            encoding='utf-8'
        ).splitlines()
    ]
    assert any(event['kind'] == 'approval' for event in events)
    transitions = [
        event['payload'].get('to_state')
        for event in events if event['kind'] == 'state_transition'
    ]
    assert 'WAITING_APPROVAL' in transitions
    with SkillRegistry(database, clock) as registry:
        approval = registry.get_execution_approval(
            invocation['approval_id']
        )
    assert approval['consumed_by_run_id'] == invocation['run_id']


def test_missing_or_tampered_approval_never_calls_adapter(tmp_path):
    """No approval and post-approval input edits both stop before ROS."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    record, public_key = _register_active(database, tmp_path, clock)
    runner = FixedRunner()
    missing = _invocation(record['artifact_hash'], approval=False)
    result = _executor(
        database, tmp_path, clock, public_key, runner,
    ).execute(missing)
    assert result['status'] == 'failed'
    assert 'requires one-time' in result['error']
    assert runner.calls == []

    invocation = _invocation(record['artifact_hash'])
    invocation['run_id'] = 'run_nav_tampered_001'
    invocation['trace_id'] = 'trace_nav_tampered_001'
    invocation['approval_id'] = 'approval_nav_tampered_001'
    with SkillRegistry(database, clock) as registry:
        registry.issue_execution_approval(
            invocation, 'human_li', 'approved original goal', 60.0,
        )
    tampered = deepcopy(invocation)
    tampered['inputs']['goal_x'] = 3.0
    result = _executor(
        database, tmp_path, clock, public_key, runner,
    ).execute(tampered)
    assert result['status'] == 'failed'
    assert 'not bound to this invocation' in result['error']
    assert runner.calls == []
