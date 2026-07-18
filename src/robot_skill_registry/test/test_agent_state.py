"""Tests for persistent bounded Agent run state and restart recovery."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from robot_skill_registry import (
    AgentRunStore,
    RegistryConflictError,
    RegistryContractError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class IncrementingClock:
    """Deterministic nanosecond clock for Agent state tests."""

    def __init__(self, start=2_000_000_000):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


def create_run(store, suffix='001'):
    """Create a standard bounded test run."""
    return store.create_run(
        f'run_{suffix}',
        f'trace_{suffix}',
        {'task': 'check robot health'},
    )


def transition_to_executing(store, run_id):
    """Advance through planning while storing one structured plan."""
    store.transition(
        run_id, 'RETRIEVING', 'IDLE', 'runtime', 'begin retrieval',
    )
    store.transition(
        run_id, 'PLANNING', 'RETRIEVING', 'runtime', 'context retrieved',
    )
    store.transition(
        run_id,
        'VALIDATING',
        'PLANNING',
        'runtime',
        'plan generated',
        plan={'steps': [{'skill': 'check_robot_health', 'version': '0.1.0'}]},
    )
    return store.transition(
        run_id, 'EXECUTING', 'VALIDATING', 'validator', 'read-only plan valid',
    )


def test_agent_happy_path_persists_plan_and_audit_events(tmp_path):
    """A valid bounded run reaches SUCCEEDED without losing its plan."""
    database = tmp_path / 'registry.db'
    with AgentRunStore(database, IncrementingClock()) as store:
        run = create_run(store)
        run = transition_to_executing(store, run['run_id'])
        run = store.transition(
            run['run_id'], 'VERIFYING', 'EXECUTING',
            'runtime', 'Skill returned typed result',
        )
        run = store.transition(
            run['run_id'], 'SUCCEEDED', 'VERIFYING',
            'verifier', 'postconditions satisfied',
        )
        assert run['state'] == 'SUCCEEDED'
        assert run['plan']['steps'][0]['skill'] == 'check_robot_health'
        assert len(store.list_events(run['run_id'])) == 7
    with AgentRunStore(database, IncrementingClock()) as reopened:
        assert reopened.get_run('run_001')['state'] == 'SUCCEEDED'


def test_plan_is_required_and_state_cannot_skip(tmp_path):
    """Execution cannot start without planning, validation, and stored plan."""
    with AgentRunStore(tmp_path / 'registry.db', IncrementingClock()) as store:
        run = create_run(store)
        with pytest.raises(RegistryContractError, match='illegal Agent transition'):
            store.transition(
                run['run_id'], 'EXECUTING', 'IDLE',
                'runtime', 'attempted bypass',
            )
        store.transition(
            run['run_id'], 'RETRIEVING', 'IDLE', 'runtime', 'start',
        )
        store.transition(
            run['run_id'], 'PLANNING', 'RETRIEVING', 'runtime', 'retrieved',
        )
        with pytest.raises(RegistryContractError, match='structured plan'):
            store.transition(
                run['run_id'], 'VALIDATING', 'PLANNING',
                'runtime', 'missing plan',
            )


def test_stale_agent_writer_and_duplicate_ids_are_rejected(tmp_path):
    """Optimistic state and unique ids prevent duplicate execution records."""
    database = tmp_path / 'registry.db'
    clock = IncrementingClock()
    first = AgentRunStore(database, clock)
    second = AgentRunStore(database, clock)
    try:
        run = create_run(first)
        second.transition(
            run['run_id'], 'RETRIEVING', 'IDLE', 'runtime_b', 'started',
        )
        with pytest.raises(RegistryConflictError, match='stale Agent state'):
            first.transition(
                run['run_id'], 'RETRIEVING', 'IDLE',
                'runtime_a', 'duplicate start',
            )
        with pytest.raises(RegistryConflictError, match='must be unique'):
            create_run(first)
    finally:
        first.close()
        second.close()


def test_restart_aborts_active_runs_but_preserves_terminal_and_idle(tmp_path):
    """Crash recovery fails closed without rewriting safe terminal evidence."""
    database = tmp_path / 'registry.db'
    clock = IncrementingClock()
    with AgentRunStore(database, clock) as store:
        active = create_run(store, 'active')
        transition_to_executing(store, active['run_id'])
        idle = create_run(store, 'idle')
        stopped = create_run(store, 'stopped')
        store.transition(
            stopped['run_id'], 'EMERGENCY_STOP', 'IDLE',
            'safety_monitor', 'external stop asserted',
        )
    with AgentRunStore(database, clock) as restarted:
        assert restarted.fail_closed_recover() == ['run_active']
        assert restarted.get_run('run_active')['state'] == 'ABORTED'
        assert restarted.get_run('run_active')['terminal_reason'] == (
            'process_restart_fail_closed'
        )
        assert restarted.get_run(idle['run_id'])['state'] == 'IDLE'
        assert restarted.get_run(stopped['run_id'])['state'] == (
            'EMERGENCY_STOP'
        )


def test_agent_record_matches_machine_contract(tmp_path):
    """Public Agent run records satisfy the repository JSON Schema."""
    schema = json.loads(
        (REPOSITORY_ROOT / 'schemas/agent_run_state.schema.json')
        .read_text(encoding='utf-8')
    )
    with AgentRunStore(tmp_path / 'registry.db', IncrementingClock()) as store:
        run = create_run(store)
    Draft202012Validator(schema).validate(run)
