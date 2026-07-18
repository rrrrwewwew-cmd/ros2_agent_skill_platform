"""Tests for Registry-gated bounded Skill execution."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from robot_skill_registry import AgentRunStore, SkillRegistry
from robot_skill_runtime import SkillExecutor
from robot_skill_runtime.adapters import HealthSkillAdapter
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'
LOCK_PATH = REPOSITORY_ROOT / 'artifacts/check_robot_health/0.2.0.json'
EVIDENCE_PATH = (
    REPOSITORY_ROOT /
    'evidence/check_robot_health/rbot_live_simulation_v1.json'
)


class IncrementingClock:
    """Deterministic clock shared by Registry, run state, and Trace."""

    def __init__(self, start=5_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


class FixedProcessRunner:
    """Return one typed subprocess result without starting ROS."""

    def __init__(self, output, returncode=0):
        self.output = output
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=json.dumps(self.output),
            stderr='',
        )


class TimeoutProcessRunner:
    """Simulate a subprocess that exceeds the manifest timeout."""

    def __init__(self):
        self.calls = 0

    def __call__(self, command, **options):
        self.calls += 1
        raise subprocess.TimeoutExpired(command, options['timeout'])


def _manifest_and_hash():
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding='utf-8'))
    artifact_hash = json.loads(
        LOCK_PATH.read_text(encoding='utf-8')
    )['artifact_hash']
    return manifest, artifact_hash


def _register(database, clock, active):
    manifest, artifact_hash = _manifest_and_hash()
    with SkillRegistry(database, clock) as registry:
        record = registry.register_manifest(
            manifest, artifact_hash=artifact_hash,
        )
        if not active:
            return record
        current = 'DRAFT'
        for target in (
            'GENERATED',
            'STATIC_VALIDATED',
            'BUILT',
            'UNIT_TESTED',
            'SIMULATION_TESTED',
        ):
            record = registry.advance(
                record['name'], record['version'], target, current,
                'test_pipeline', f'passed {target}',
            )
            current = target
        record = registry.approve(
            record['name'], record['version'], record['artifact_hash'],
            'test_policy', 'fixture approval',
        )
        record = registry.record_verified_signature(
            record['name'], record['version'], record['artifact_hash'],
            'fixture-signature', 'test_verifier', 'fixture verified',
        )
        return registry.advance(
            record['name'], record['version'], 'ACTIVE', 'SIGNED',
            'test_release', 'fixture activated',
        )


def _invocation(run_id, artifact_hash, inputs=None):
    return {
        'schema_version': 1,
        'run_id': run_id,
        'trace_id': f'trace_{run_id}',
        'skill_name': 'check_robot_health',
        'skill_version': '0.2.0',
        'artifact_hash': artifact_hash,
        'inputs': inputs or {'required_sensors': ['/scan']},
    }


def _executor(tmp_path, clock, runner):
    adapter = HealthSkillAdapter(REPOSITORY_ROOT, runner=runner)
    return SkillExecutor(
        tmp_path / 'registry.db',
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
    )


def test_simulation_tested_skill_is_refused_before_adapter_call(tmp_path):
    """A tested but unsigned Skill cannot cross the execution boundary."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=False)
    runner = FixedProcessRunner({})
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_not_active', record['artifact_hash'])
    )
    assert result['status'] == 'failed'
    assert result['agent_state'] == 'FAILED'
    assert 'not ACTIVE' in result['error']
    assert runner.calls == []
    with AgentRunStore(tmp_path / 'registry.db', clock) as store:
        assert store.get_run('run_not_active')['state'] == 'FAILED'


def test_active_hash_bound_skill_executes_and_writes_trace(tmp_path):
    """An exact ACTIVE artifact reaches SUCCEEDED through its adapter."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=True)
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding='utf-8'))
    runner = FixedProcessRunner(evidence)
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_healthy', record['artifact_hash'])
    )
    assert result['status'] == 'succeeded'
    assert result['agent_state'] == 'SUCCEEDED'
    assert result['output']['state'] == 'healthy'
    assert len(runner.calls) == 1
    events = [
        json.loads(line)
        for line in Path(result['trace_file']).read_text(
            encoding='utf-8'
        ).splitlines()
    ]
    trace_schema = json.loads((
        REPOSITORY_ROOT / 'schemas/agent_trace_event.schema.json'
    ).read_text(encoding='utf-8'))
    for event in events:
        Draft202012Validator(trace_schema).validate(event)
    assert {'tool_call', 'tool_result'}.issubset({
        event['kind'] for event in events
    })


def test_active_skill_rejects_input_outside_manifest_enum(tmp_path):
    """ACTIVE status cannot bypass the declared input allowlist."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=True)
    runner = FixedProcessRunner({})
    result = _executor(tmp_path, clock, runner).execute(_invocation(
        'run_bad_input',
        record['artifact_hash'],
        {'required_sensors': ['/private/raw_topic']},
    ))
    assert result['status'] == 'failed'
    assert 'invalid Skill inputs' in result['error']
    assert runner.calls == []


def test_unsafe_health_is_valid_execution_not_agent_failure(tmp_path):
    """A successful check may truthfully report that motion is unsafe."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=True)
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding='utf-8'))
    unsafe = deepcopy(evidence)
    unsafe['state'] = 'unsafe'
    unsafe['safe_to_proceed'] = False
    unsafe['reasons'] = ['Nav2 managed nodes are not active']
    unsafe['checks'][0]['status'] = 'fail'
    unsafe['checks'][0]['reason'] = unsafe['reasons'][0]
    runner = FixedProcessRunner(unsafe, returncode=4)
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_unsafe', record['artifact_hash'])
    )
    assert result['status'] == 'succeeded'
    assert result['output']['state'] == 'unsafe'
    assert result['output']['safe_to_proceed'] is False


def test_invocation_hash_mismatch_is_rejected_before_adapter(tmp_path):
    """Agent input cannot select code different from the ACTIVE artifact."""
    clock = IncrementingClock()
    _register(tmp_path / 'registry.db', clock, active=True)
    runner = FixedProcessRunner({})
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_wrong_hash', '0' * 64)
    )
    assert result['status'] == 'failed'
    assert 'hash does not match Registry' in result['error']
    assert runner.calls == []


def test_manifest_timeout_becomes_durable_agent_failure(tmp_path):
    """A timed-out subprocess terminates the bounded Agent run."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=True)
    runner = TimeoutProcessRunner()
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_timeout', record['artifact_hash'])
    )
    assert result['status'] == 'failed'
    assert result['agent_state'] == 'FAILED'
    assert result['error'] == 'health Skill timed out'
    assert runner.calls == 1


def test_inconsistent_adapter_output_fails_postcondition(tmp_path):
    """A Schema-shaped but contradictory health result is rejected."""
    clock = IncrementingClock()
    record = _register(tmp_path / 'registry.db', clock, active=True)
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding='utf-8'))
    evidence['safe_to_proceed'] = False
    runner = FixedProcessRunner(evidence)
    result = _executor(tmp_path, clock, runner).execute(
        _invocation('run_bad_output', record['artifact_hash'])
    )
    assert result['status'] == 'failed'
    assert 'inconsistent readiness state' in result['error']
