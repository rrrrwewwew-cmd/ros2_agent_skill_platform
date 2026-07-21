"""Tests for the bounded read-only Agent Loop."""

from copy import deepcopy
import fcntl
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest
from robot_agent_orchestrator import AgentLoopError, ReadOnlyAgentLoop
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_skill_registry import (
    AgentRunStore,
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    SkillRegistry,
)
from robot_skill_runtime import SkillExecutor
from robot_skill_runtime.adapters import HealthSkillAdapter
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class IncrementingClock:
    """Return deterministic nanosecond timestamps."""

    def __init__(self, start=8_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


class FixedGateway:
    """Return one prevalidated-looking gateway result."""

    def __init__(self, plan=None, failed=False):
        self.plan_value = plan
        self.failed = failed
        self.calls = []

    def plan(self, request):
        """Record and return the configured plan result."""
        self.calls.append(request)
        return {
            'state': 'failed' if self.failed else 'succeeded',
            'plan': None if self.failed else deepcopy(self.plan_value),
            'request_sha256': '0' * 64,
            'error': (
                {'code': 'provider_unavailable', 'message': 'offline'}
                if self.failed else None
            ),
        }


class FixedExecutor:
    """Return typed child execution envelopes without invoking ROS."""

    def __init__(self, outputs=None, failed_skill=None, identity_override=None):
        self.outputs = outputs or {}
        self.failed_skill = failed_skill
        self.identity_override = identity_override
        self.calls = []

    def execute(self, invocation):
        """Return one deterministic Skill Runtime result."""
        self.calls.append(deepcopy(invocation))
        failed = invocation['skill_name'] == self.failed_skill
        return {
            'schema_version': 1,
            'run_id': invocation['run_id'],
            'trace_id': invocation['trace_id'],
            'skill_name': (
                self.identity_override or invocation['skill_name']
            ),
            'skill_version': invocation['skill_version'],
            'status': 'failed' if failed else 'succeeded',
            'agent_state': 'FAILED' if failed else 'SUCCEEDED',
            'started_at_ns': 9_000_000_001,
            'completed_at_ns': 9_000_000_002,
            'output': (
                None if failed else deepcopy(
                    self.outputs[invocation['skill_name']]
                )
            ),
            'error': 'fixture failure' if failed else None,
            'trace_file': f"/tmp/{invocation['run_id']}.jsonl",
        }


class FixedProcessRunner:
    """Return one typed subprocess response to the real Runtime adapter."""

    def __init__(self, output):
        self.output = output
        self.calls = []

    def __call__(self, command, **options):
        """Record one fixed-command call and return JSON stdout."""
        self.calls.append({'command': command, 'options': options})
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(self.output),
            stderr='',
        )


def _prompt():
    """Resolve the repository's contract-aware Prompt."""
    return PromptRegistry(
        REPOSITORY_ROOT / 'prompts',
        REPOSITORY_ROOT / 'schemas',
    ).resolve('robot_task_planner', '0.2.0')


def _step(prompt, index, name, inputs):
    """Build one exact prompt-catalog step."""
    skill = next(
        item for item in prompt.definition['allowed_skills']
        if item['name'] == name
    )
    return {
        'step_id': index,
        'skill_name': name,
        'skill_version': skill['version'],
        'artifact_hash': skill['artifact_hash'],
        'inputs': inputs,
        'reason': 'Fixture step.',
        'expected_evidence': ['typed evidence'],
    }


def _plan(prompt, steps, decision='plan'):
    """Build one bounded fixture plan."""
    return {
        'schema_version': 1,
        'decision': decision,
        'summary': 'Fixture plan.',
        'steps': steps,
        'clarification': (
            'Which target should be queried?'
            if decision == 'clarify' else None
        ),
    }


def _route_plan(prompt):
    """Build the two-step health and route-preview plan."""
    return _plan(prompt, [
        _step(prompt, 1, 'check_robot_health', {}),
        _step(prompt, 2, 'preview_safe_route', {
            'goal_x': 4.5,
            'goal_y': 0.0,
            'goal_yaw_deg': 0.0,
            'keepout_profile': 'rbot_water_puddle_v2',
        }),
    ])


def _loop(tmp_path, gateway, executor, prompt, clock):
    """Build one loop over temporary persistence and traces."""
    return ReadOnlyAgentLoop(
        database_path=tmp_path / 'registry.db',
        trace_directory=tmp_path / 'traces',
        schema_directory=REPOSITORY_ROOT / 'schemas',
        gateway=gateway,
        prompt=prompt,
        skill_executor=executor,
        clock_ns=clock,
    )


def _request():
    """Return a stable fixture planning request."""
    return {
        'schema_version': 1,
        'request_id': 'fixture.plan',
        'task': {'user_request': 'preview route'},
    }


def _outputs(health=True, route=True):
    """Return minimal typed evidence used by the fake Executor."""
    return {
        'check_robot_health': {'safe_to_proceed': health},
        'preview_safe_route': {'safe_to_execute': route},
        'query_semantic_target': {'found': True},
    }


def _active_health_runtime(tmp_path, clock):
    """Create one signed ACTIVE health Skill and its real Runtime adapter."""
    manifest_path = (
        REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'
    )
    lock_path = (
        REPOSITORY_ROOT / 'artifacts/check_robot_health/0.2.0.json'
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    artifact_hash = json.loads(
        lock_path.read_text(encoding='utf-8')
    )['artifact_hash']
    database = tmp_path / 'registry.db'
    private_key = tmp_path / 'release_ed25519.pem'
    public_key = tmp_path / 'release_ed25519.pub.pem'
    with SkillRegistry(database, clock) as registry:
        record = registry.register_manifest(
            manifest,
            artifact_hash=artifact_hash,
        )
        current = 'DRAFT'
        for target in (
            'GENERATED',
            'STATIC_VALIDATED',
            'BUILT',
            'UNIT_TESTED',
            'SIMULATION_TESTED',
        ):
            record = registry.advance(
                record['name'],
                record['version'],
                target,
                current,
                'integration_pipeline',
                f'passed {target}',
            )
            current = target
        record = registry.approve(
            record['name'],
            record['version'],
            record['artifact_hash'],
            'integration_policy',
            'fixture approval',
        )
        generate_ed25519_keypair(private_key, public_key)
        envelope = create_signature_envelope(
            REPOSITORY_ROOT,
            record['name'],
            record['version'],
            record['artifact_hash'],
            private_key,
            'integration_signer',
            clock_ns=clock,
        )
        record = registry.record_verified_signature(
            record['name'],
            record['version'],
            record['artifact_hash'],
            canonical_json(envelope),
            'integration_verifier',
            'fixture signature verified',
        )
        registry.advance(
            record['name'],
            record['version'],
            'ACTIVE',
            'SIGNED',
            'integration_release',
            'fixture activated',
        )
    evidence = json.loads((
        REPOSITORY_ROOT /
        'evidence/check_robot_health/rbot_live_simulation_v1.json'
    ).read_text(encoding='utf-8'))
    runner = FixedProcessRunner(evidence)
    adapter = HealthSkillAdapter(REPOSITORY_ROOT, runner=runner)
    executor = SkillExecutor(
        database,
        REPOSITORY_ROOT,
        tmp_path / 'traces',
        adapters={adapter.entrypoint: adapter},
        clock_ns=clock,
        trusted_public_key=public_key,
    )
    return executor, runner


def test_two_step_plan_executes_in_order_with_parent_trace(tmp_path):
    """A valid plan creates child runs and one terminal parent audit trail."""
    prompt = _prompt()
    plan = _route_plan(prompt)
    executor = FixedExecutor(_outputs())
    clock = IncrementingClock()
    result = _loop(
        tmp_path,
        FixedGateway(plan),
        executor,
        prompt,
        clock,
    ).run('agent_success', 'trace_success', _request())
    assert result['status'] == 'succeeded'
    assert result['agent_state'] == 'SUCCEEDED'
    assert result['safe_to_continue'] is True
    assert [
        call['skill_name'] for call in executor.calls
    ] == ['check_robot_health', 'preview_safe_route']
    assert all('approval_id' not in call for call in executor.calls)
    assert executor.calls[1]['inputs']['keepout_profile'] == (
        'rbot_water_puddle_v2'
    )
    with AgentRunStore(tmp_path / 'registry.db', clock) as store:
        assert store.get_run('agent_success')['state'] == 'SUCCEEDED'
        transitions = [
            event['to_state']
            for event in store.list_events('agent_success')
        ]
    assert transitions == [
        'IDLE',
        'RETRIEVING',
        'PLANNING',
        'VALIDATING',
        'EXECUTING',
        'VERIFYING',
        'SUCCEEDED',
    ]
    trace_schema = json.loads((
        REPOSITORY_ROOT / 'schemas/agent_trace_event.schema.json'
    ).read_text(encoding='utf-8'))
    events = [
        json.loads(line)
        for line in Path(result['trace_file']).read_text(
            encoding='utf-8'
        ).splitlines()
    ]
    for event in events:
        Draft202012Validator(trace_schema).validate(event)
    assert [event['kind'] for event in events].count('tool_call') == 2


def test_unsafe_health_blocks_later_route_step(tmp_path):
    """Typed unsafe health evidence halts before the next Tool call."""
    prompt = _prompt()
    executor = FixedExecutor(_outputs(health=False))
    clock = IncrementingClock()
    result = _loop(
        tmp_path,
        FixedGateway(_route_plan(prompt)),
        executor,
        prompt,
        clock,
    ).run('agent_blocked', 'trace_blocked', _request())
    assert result['status'] == 'blocked_by_evidence'
    assert result['agent_state'] == 'ABORTED'
    assert result['safe_to_continue'] is False
    assert len(executor.calls) == 1
    assert result['steps'][0]['evidence_gate_passed'] is False
    assert 'health' in result['halt_reason']


def test_unsafe_final_preview_is_truthful_success_with_false_readiness(
    tmp_path,
):
    """A completed preview may report unsafe without becoming a tool error."""
    prompt = _prompt()
    executor = FixedExecutor(_outputs(route=False))
    result = _loop(
        tmp_path,
        FixedGateway(_route_plan(prompt)),
        executor,
        prompt,
        IncrementingClock(),
    ).run('agent_unsafe_route', 'trace_unsafe_route', _request())
    assert result['status'] == 'succeeded'
    assert result['safe_to_continue'] is False
    assert result['steps'][-1]['evidence_gate_passed'] is False


def test_failed_child_stops_remaining_steps_and_fails_parent(tmp_path):
    """A Runtime failure is fail-fast and no later Skill is invoked."""
    prompt = _prompt()
    executor = FixedExecutor(
        _outputs(),
        failed_skill='check_robot_health',
    )
    result = _loop(
        tmp_path,
        FixedGateway(_route_plan(prompt)),
        executor,
        prompt,
        IncrementingClock(),
    ).run('agent_child_fail', 'trace_child_fail', _request())
    assert result['status'] == 'failed'
    assert result['agent_state'] == 'FAILED'
    assert len(executor.calls) == 1
    assert result['error'] == 'fixture failure'


def test_clarification_and_refusal_execute_no_skills(tmp_path):
    """Non-plan decisions halt without crossing the Tool boundary."""
    prompt = _prompt()
    for decision, expected_status in (
        ('clarify', 'clarification_required'),
        ('refuse', 'refused'),
    ):
        executor = FixedExecutor(_outputs())
        plan = _plan(prompt, [], decision=decision)
        suffix = decision
        result = _loop(
            tmp_path,
            FixedGateway(plan),
            executor,
            prompt,
            IncrementingClock(),
        ).run(
            f'agent_{suffix}',
            f'trace_{suffix}',
            _request(),
        )
        assert result['status'] == expected_status
        assert result['agent_state'] == 'ABORTED'
        assert executor.calls == []


def test_gateway_failure_creates_durable_failed_parent(tmp_path):
    """Provider failure is recorded without attempting any Skill."""
    prompt = _prompt()
    executor = FixedExecutor(_outputs())
    clock = IncrementingClock()
    result = _loop(
        tmp_path,
        FixedGateway(failed=True),
        executor,
        prompt,
        clock,
    ).run('agent_gateway_fail', 'trace_gateway_fail', _request())
    assert result['status'] == 'failed'
    assert result['planner_decision'] is None
    assert result['error'] == 'provider_unavailable: offline'
    assert executor.calls == []
    with AgentRunStore(tmp_path / 'registry.db', clock) as store:
        assert store.get_run('agent_gateway_fail')['state'] == 'FAILED'


def test_unknown_skill_is_rejected_by_second_permission_gate(tmp_path):
    """A compromised gateway result cannot dispatch an unknown Tool."""
    prompt = _prompt()
    plan = _route_plan(prompt)
    plan['steps'][0]['skill_name'] = 'navigate_to_approved_pose'
    executor = FixedExecutor(_outputs())
    result = _loop(
        tmp_path,
        FixedGateway(plan),
        executor,
        prompt,
        IncrementingClock(),
    ).run('agent_unknown', 'trace_unknown', _request())
    assert result['status'] == 'failed'
    assert 'read-only catalog' in result['error']
    assert executor.calls == []


def test_child_identity_mismatch_fails_closed(tmp_path):
    """A child result cannot claim evidence from another Skill."""
    prompt = _prompt()
    executor = FixedExecutor(
        _outputs(),
        identity_override='query_semantic_target',
    )
    result = _loop(
        tmp_path,
        FixedGateway(_route_plan(prompt)),
        executor,
        prompt,
        IncrementingClock(),
    ).run('agent_identity', 'trace_identity', _request())
    assert result['status'] == 'failed'
    assert 'identity changed' in result['error']


def test_startup_recovery_aborts_previous_nonterminal_run(tmp_path):
    """A new loop cannot silently resume an interrupted Tool sequence."""
    clock = IncrementingClock()
    database = tmp_path / 'registry.db'
    with AgentRunStore(database, clock) as store:
        store.create_run(
            'agent_interrupted',
            'trace_interrupted',
            {'fixture': True},
        )
        store.transition(
            'agent_interrupted',
            'RETRIEVING',
            'IDLE',
            'fixture',
            'simulate interrupted run',
        )
    prompt = _prompt()
    health_plan = _plan(prompt, [
        _step(prompt, 1, 'check_robot_health', {}),
    ])
    result = _loop(
        tmp_path,
        FixedGateway(health_plan),
        FixedExecutor(_outputs()),
        prompt,
        clock,
    ).run('agent_recovered', 'trace_recovered', _request())
    assert result['recovered_runs'] == ['agent_interrupted']
    with AgentRunStore(database, clock) as store:
        interrupted = store.get_run('agent_interrupted')
    assert interrupted['state'] == 'ABORTED'
    assert interrupted['terminal_reason'] == 'process_restart_fail_closed'


def test_fake_plan_crosses_real_registry_signature_and_runtime(tmp_path):
    """Parent orchestration integrates with the actual governed Runtime."""
    clock = IncrementingClock()
    prompt = _prompt()
    executor, runner = _active_health_runtime(tmp_path, clock)
    health_plan = _plan(prompt, [
        _step(prompt, 1, 'check_robot_health', {}),
    ])
    result = _loop(
        tmp_path,
        FixedGateway(health_plan),
        executor,
        prompt,
        clock,
    ).run('agent_integrated', 'trace_integrated', _request())
    assert result['status'] == 'succeeded'
    assert result['safe_to_continue'] is True
    assert result['steps'][0]['output']['state'] == 'healthy'
    assert len(runner.calls) == 1
    with AgentRunStore(tmp_path / 'registry.db', clock) as store:
        assert store.get_run('agent_integrated')['state'] == 'SUCCEEDED'
        assert store.get_run('agent_integrated.step1')['state'] == 'SUCCEEDED'


def test_concurrent_agent_loop_is_rejected_before_recovery(tmp_path):
    """A live process lease prevents false crash recovery and double tools."""
    prompt = _prompt()
    health_plan = _plan(prompt, [
        _step(prompt, 1, 'check_robot_health', {}),
    ])
    executor = FixedExecutor(_outputs())
    loop = _loop(
        tmp_path,
        FixedGateway(health_plan),
        executor,
        prompt,
        IncrementingClock(),
    )
    loop.lease_path.parent.mkdir(parents=True, exist_ok=True)
    with loop.lease_path.open('a+', encoding='utf-8') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(AgentLoopError, match='already active'):
            loop.run('agent_concurrent', 'trace_concurrent', _request())
    assert executor.calls == []
    assert not (tmp_path / 'registry.db').exists()
