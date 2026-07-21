"""Persistent fail-closed read-only Agent Loop."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
import time

from robot_llm_gateway.contracts import (
    ContractError,
    load_schema,
    sha256_json,
    validate_instance,
)
from robot_skill_registry import (
    AgentRunStore,
    RegistryConflictError,
    RegistryContractError,
)
from robot_skill_runtime import (
    ExecutionPolicyError,
    SkillRuntimeError,
    TraceRecorder,
)


class AgentLoopError(RuntimeError):
    """Report an orchestration contract or evidence-gate failure."""


class ReadOnlyAgentLoop:
    """Plan once, execute bounded read-only Skills, and retain evidence."""

    def __init__(
        self,
        database_path,
        trace_directory,
        schema_directory,
        gateway,
        prompt,
        skill_executor,
        clock_ns=time.time_ns,
        max_steps=6,
    ):
        """Bind trusted planning and execution boundaries to one loop."""
        if not isinstance(max_steps, int) or not 1 <= max_steps <= 6:
            raise AgentLoopError('max_steps must be an integer from 1 to 6')
        self.database_path = Path(database_path).expanduser()
        self.lease_path = self.database_path.with_suffix(
            self.database_path.suffix + '.agent_loop.lock'
        )
        self.trace_directory = Path(trace_directory).expanduser()
        self.gateway = gateway
        self.prompt = prompt
        self.skill_executor = skill_executor
        self.clock_ns = clock_ns
        self.max_steps = max_steps
        self.result_schema = load_schema(
            schema_directory,
            'agent_loop_result.schema.json',
        )
        self.execution_result_schema = load_schema(
            schema_directory,
            'skill_execution_result.schema.json',
        )

    def run(self, run_id, trace_id, plan_request):
        """Execute one plan-only request through a sequential evidence loop."""
        with self._exclusive_lease():
            return self._run_locked(run_id, trace_id, plan_request)

    def _run_locked(self, run_id, trace_id, plan_request):
        """Run after obtaining the process-wide single-Agent lease."""
        started_at_ns = self.clock_ns()
        recovered_runs = self._recover_unfinished_runs()
        trace = TraceRecorder(
            self.trace_directory,
            run_id,
            trace_id,
            clock_ns=self.clock_ns,
        )
        gateway_result = None
        plan = None
        steps = []
        safe_to_continue = False
        current = 'IDLE'
        parent_request = {
            'schema_version': 1,
            'kind': 'read_only_agent_loop',
            'plan_request_sha256': sha256_json(plan_request),
            'plan_request': plan_request,
        }
        with AgentRunStore(
            self.database_path,
            self.clock_ns,
        ) as store:
            store.create_run(
                run_id,
                trace_id,
                parent_request,
                actor='agent_orchestrator',
            )
            trace.record(
                'state_transition',
                'agent_orchestrator',
                {'from_state': None, 'to_state': 'IDLE'},
                correlation_id=run_id,
            )
            try:
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'RETRIEVING',
                    'resolve pinned Prompt and read-only Skill catalog',
                )
                trace.record(
                    'retrieval',
                    'prompt_registry',
                    {
                        'prompt_id': self.prompt.definition['prompt_id'],
                        'prompt_version': self.prompt.definition['version'],
                        'prompt_sha256': self.prompt.sha256,
                        'allowed_skills': [
                            item['name']
                            for item in self.prompt.definition['allowed_skills']
                        ],
                    },
                    correlation_id=run_id,
                )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'PLANNING',
                    'trusted planning context resolved',
                )
                gateway_result = self.gateway.plan(plan_request)
                plan = gateway_result.get('plan')
                trace.record(
                    'plan',
                    'robot_llm_gateway',
                    {
                        'gateway_state': gateway_result.get('state'),
                        'request_sha256': gateway_result.get(
                            'request_sha256'
                        ),
                        'plan': plan,
                    },
                    correlation_id=run_id,
                )
                if gateway_result['state'] != 'succeeded':
                    message = self._gateway_error(gateway_result)
                    current = self._transition(
                        store,
                        trace,
                        run_id,
                        current,
                        'FAILED',
                        message,
                    )
                    return self._result(
                        run_id,
                        trace_id,
                        'failed',
                        current,
                        None,
                        False,
                        gateway_result,
                        None,
                        steps,
                        recovered_runs,
                        None,
                        message,
                        started_at_ns,
                        trace,
                    )
                decision = plan['decision']
                if decision in {'clarify', 'refuse'}:
                    status = (
                        'clarification_required'
                        if decision == 'clarify' else 'refused'
                    )
                    reason = (
                        plan['clarification']
                        if decision == 'clarify'
                        else 'planner refused a request outside read-only policy'
                    )
                    current = self._transition(
                        store,
                        trace,
                        run_id,
                        current,
                        'ABORTED',
                        reason,
                    )
                    return self._result(
                        run_id,
                        trace_id,
                        status,
                        current,
                        decision,
                        False,
                        gateway_result,
                        plan,
                        steps,
                        recovered_runs,
                        reason,
                        None,
                        started_at_ns,
                        trace,
                    )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'VALIDATING',
                    'validate read-only plan before Tool Calling',
                    plan=plan,
                )
                self._validate_read_only_plan(plan)
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'EXECUTING',
                    'plan is bounded to contract-valid read-only Skills',
                )
                safe_to_continue = True
                for index, step in enumerate(plan['steps']):
                    invocation = self._invocation(run_id, trace_id, step)
                    trace.record(
                        'tool_call',
                        'agent_orchestrator',
                        {
                            'step_id': step['step_id'],
                            'skill_name': step['skill_name'],
                            'skill_version': step['skill_version'],
                            'artifact_hash': step['artifact_hash'],
                            'inputs_sha256': sha256_json(step['inputs']),
                            'child_run_id': invocation['run_id'],
                        },
                        correlation_id=run_id,
                    )
                    execution = self.skill_executor.execute(invocation)
                    normalized = self._normalize_step(step, execution)
                    steps.append(normalized)
                    trace.record(
                        'tool_result',
                        'agent_orchestrator',
                        {
                            'step_id': step['step_id'],
                            'skill_name': step['skill_name'],
                            'status': normalized['status'],
                            'evidence_gate_passed': normalized[
                                'evidence_gate_passed'
                            ],
                            'evidence_gate_reason': normalized[
                                'evidence_gate_reason'
                            ],
                            'child_run_id': normalized['run_id'],
                        },
                        correlation_id=run_id,
                    )
                    if normalized['status'] != 'succeeded':
                        message = normalized['error'] or (
                            f"Skill {step['skill_name']} failed"
                        )
                        current = self._transition(
                            store,
                            trace,
                            run_id,
                            current,
                            'FAILED',
                            message,
                        )
                        return self._result(
                            run_id,
                            trace_id,
                            'failed',
                            current,
                            decision,
                            False,
                            gateway_result,
                            plan,
                            steps,
                            recovered_runs,
                            None,
                            message,
                            started_at_ns,
                            trace,
                        )
                    safe_to_continue = normalized['evidence_gate_passed']
                    has_later_step = index + 1 < len(plan['steps'])
                    if not safe_to_continue and has_later_step:
                        reason = normalized['evidence_gate_reason']
                        current = self._transition(
                            store,
                            trace,
                            run_id,
                            current,
                            'ABORTED',
                            reason,
                        )
                        return self._result(
                            run_id,
                            trace_id,
                            'blocked_by_evidence',
                            current,
                            decision,
                            False,
                            gateway_result,
                            plan,
                            steps,
                            recovered_runs,
                            reason,
                            None,
                            started_at_ns,
                            trace,
                        )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'VERIFYING',
                    'all planned Skill results returned typed evidence',
                )
                if len(steps) != len(plan['steps']):
                    raise AgentLoopError('not all planned steps were executed')
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'SUCCEEDED',
                    'bounded read-only Agent Loop completed',
                )
                return self._result(
                    run_id,
                    trace_id,
                    'succeeded',
                    current,
                    decision,
                    safe_to_continue,
                    gateway_result,
                    plan,
                    steps,
                    recovered_runs,
                    None,
                    None,
                    started_at_ns,
                    trace,
                )
            except (
                AgentLoopError,
                ContractError,
                ExecutionPolicyError,
                SkillRuntimeError,
                RegistryConflictError,
                RegistryContractError,
                OSError,
            ) as exc:
                message = str(exc) or exc.__class__.__name__
                trace.record(
                    'error',
                    'agent_orchestrator',
                    {'state': current, 'error': message},
                    correlation_id=run_id,
                )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'FAILED',
                    message,
                )
                return self._result(
                    run_id,
                    trace_id,
                    'failed',
                    current,
                    plan['decision'] if plan else None,
                    False,
                    gateway_result,
                    plan,
                    steps,
                    recovered_runs,
                    None,
                    message,
                    started_at_ns,
                    trace,
                )

    @contextmanager
    def _exclusive_lease(self):
        """Reject concurrent loops before recovering stale persistent runs."""
        self.lease_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream = self.lease_path.open('a+', encoding='utf-8')
        except OSError as exc:
            raise AgentLoopError('cannot open Agent Loop lease') from exc
        try:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AgentLoopError(
                    'another Agent Loop process is already active'
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()

    def _recover_unfinished_runs(self):
        """Abort old nonterminal runs before accepting a fresh request."""
        with AgentRunStore(
            self.database_path,
            self.clock_ns,
        ) as store:
            return store.fail_closed_recover(actor='agent_loop_startup')

    def _validate_read_only_plan(self, plan):
        """Apply a second local permission gate before any Tool Calling."""
        if plan['decision'] != 'plan':
            raise AgentLoopError('only decision=plan may enter execution')
        if not 1 <= len(plan['steps']) <= self.max_steps:
            raise AgentLoopError('plan exceeds the Agent Loop step bound')
        catalog = {
            item['name']: item
            for item in self.prompt.definition['allowed_skills']
        }
        for step in plan['steps']:
            skill = catalog.get(step['skill_name'])
            if skill is None or skill['permission'] != 'read_only':
                raise AgentLoopError(
                    'Agent Loop accepts read-only catalog Skills only'
                )
            if (
                step['skill_version'] != skill['version'] or
                step['artifact_hash'] != skill['artifact_hash']
            ):
                raise AgentLoopError('planned Skill pin changed after gateway')

    @staticmethod
    def _invocation(parent_run_id, parent_trace_id, step):
        """Build one child invocation with no approval capability."""
        suffix = f"step{step['step_id']}"
        return {
            'schema_version': 1,
            'run_id': f'{parent_run_id}.{suffix}',
            'trace_id': f'{parent_trace_id}.{suffix}',
            'skill_name': step['skill_name'],
            'skill_version': step['skill_version'],
            'artifact_hash': step['artifact_hash'],
            'inputs': step['inputs'],
        }

    def _normalize_step(self, step, execution):
        """Validate a child result and attach its deterministic evidence gate."""
        validate_instance(
            execution,
            self.execution_result_schema,
            f"execution result for step {step['step_id']}",
        )
        if execution['skill_name'] != step['skill_name']:
            raise AgentLoopError('execution result Skill identity changed')
        if execution['skill_version'] != step['skill_version']:
            raise AgentLoopError('execution result Skill version changed')
        gate_passed, gate_reason = self._evidence_gate(
            step['skill_name'],
            execution['output'],
            execution['status'],
        )
        return {
            'step_id': step['step_id'],
            'skill_name': step['skill_name'],
            'skill_version': step['skill_version'],
            'artifact_hash': step['artifact_hash'],
            'run_id': execution['run_id'],
            'trace_id': execution['trace_id'],
            'inputs_sha256': sha256_json(step['inputs']),
            'status': execution['status'],
            'evidence_gate_passed': gate_passed,
            'evidence_gate_reason': gate_reason,
            'output': execution['output'],
            'error': execution['error'],
            'trace_file': execution['trace_file'],
        }

    @staticmethod
    def _evidence_gate(skill_name, output, execution_status):
        """Interpret typed evidence without asking the LLM to self-judge."""
        if execution_status != 'succeeded' or output is None:
            return False, 'Skill execution did not produce usable evidence'
        if skill_name == 'check_robot_health':
            passed = output.get('safe_to_proceed') is True
            reason = (
                'robot health evidence permits subsequent read-only steps'
                if passed else
                'robot health evidence blocks subsequent steps'
            )
            return passed, reason
        if skill_name == 'query_semantic_target':
            passed = output.get('found') is True
            reason = (
                'semantic target evidence is available'
                if passed else
                'semantic target evidence is unavailable'
            )
            return passed, reason
        if skill_name == 'preview_safe_route':
            passed = output.get('safe_to_execute') is True
            reason = (
                'route evidence satisfies Keepout safety constraints'
                if passed else
                'route evidence does not permit later motion planning'
            )
            return passed, reason
        return False, 'Skill has no approved Agent Loop evidence policy'

    @staticmethod
    def _gateway_error(gateway_result):
        error = gateway_result.get('error') or {}
        code = error.get('code', 'gateway_failed')
        message = error.get('message', 'planner gateway failed')
        return f'{code}: {message}'

    def _transition(
        self,
        store,
        trace,
        run_id,
        current,
        target,
        reason,
        plan=None,
    ):
        """Persist and trace one optimistic parent state transition."""
        store.transition(
            run_id,
            target,
            current,
            'agent_orchestrator',
            reason,
            plan=plan,
        )
        trace.record(
            'state_transition',
            'agent_orchestrator',
            {
                'from_state': current,
                'to_state': target,
                'reason': reason,
            },
            correlation_id=run_id,
        )
        return target

    def _result(
        self,
        run_id,
        trace_id,
        status,
        agent_state,
        planner_decision,
        safe_to_continue,
        gateway_result,
        plan,
        steps,
        recovered_runs,
        halt_reason,
        error,
        started_at_ns,
        trace,
    ):
        """Build and validate one terminal parent result."""
        result = {
            'schema_version': 1,
            'run_id': run_id,
            'trace_id': trace_id,
            'status': status,
            'agent_state': agent_state,
            'planner_decision': planner_decision,
            'safe_to_continue': bool(safe_to_continue),
            'gateway_result': gateway_result,
            'plan': plan,
            'steps': steps,
            'recovered_runs': sorted(recovered_runs),
            'halt_reason': halt_reason,
            'error': error,
            'started_at_ns': started_at_ns,
            'completed_at_ns': self.clock_ns(),
            'trace_file': str(trace.path),
        }
        validate_instance(result, self.result_schema, 'Agent Loop result')
        return result
