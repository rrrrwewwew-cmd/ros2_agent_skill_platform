"""Persistent fail-closed Agent Loop for experiment diagnosis."""

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
from robot_skill_runtime import TraceRecorder

from .client import DiagnosisClientError
from .contracts import (
    governed_tool_catalog,
    validate_cross_step_plan,
    validate_prompt_catalog,
)


class DiagnosisAgentError(RuntimeError):
    """Report a diagnosis orchestration or evidence-gate failure."""


class DiagnosisAgentLoop:
    """Plan once and enforce the five-step diagnosis evidence sequence."""

    def __init__(
        self,
        database_path,
        trace_directory,
        schema_directory,
        gateway,
        prompt,
        tool_client,
        clock_ns=time.time_ns,
        monotonic=time.monotonic,
        max_duration_sec=300.0,
        tool_timeout_sec=120.0,
    ):
        if not 10.0 <= float(max_duration_sec) <= 900.0:
            raise DiagnosisAgentError('max_duration_sec must be in [10, 900]')
        if not 5.0 <= float(tool_timeout_sec) <= 300.0:
            raise DiagnosisAgentError('tool_timeout_sec must be in [5, 300]')
        self.database_path = Path(database_path).expanduser()
        self.lease_path = self.database_path.with_suffix(
            self.database_path.suffix + '.diagnosis_agent.lock'
        )
        self.trace_directory = Path(trace_directory).expanduser()
        self.gateway = gateway
        self.prompt = prompt
        self.tool_client = tool_client
        self.clock_ns = clock_ns
        self.monotonic = monotonic
        self.max_duration_sec = float(max_duration_sec)
        self.tool_timeout_sec = float(tool_timeout_sec)
        self.result_schema = load_schema(
            schema_directory,
            'diagnosis_agent_result.schema.json',
        )
        self.tool_result_schema = load_schema(
            schema_directory,
            'mcp_tool_result.schema.json',
        )
        validate_prompt_catalog(prompt)

    def run(self, run_id, trace_id, plan_request, experiment_run_id):
        """Execute one diagnosis request with durable state and Trace."""
        with self._exclusive_lease():
            return self._run_locked(
                run_id,
                trace_id,
                plan_request,
                experiment_run_id,
            )

    def _run_locked(self, run_id, trace_id, request, experiment_run_id):
        started_at_ns = self.clock_ns()
        started = self.monotonic()
        recovered = self._recover_unfinished_runs()
        trace = TraceRecorder(
            self.trace_directory,
            run_id,
            trace_id,
            clock_ns=self.clock_ns,
        )
        gateway_result = None
        plan = None
        steps = []
        outputs = {}
        current = 'IDLE'
        parent_request = {
            'schema_version': 1,
            'kind': 'experiment_diagnosis_agent',
            'experiment_run_id': experiment_run_id,
            'plan_request_sha256': sha256_json(request),
            'plan_request': request,
        }
        with AgentRunStore(self.database_path, self.clock_ns) as store:
            store.create_run(
                run_id,
                trace_id,
                parent_request,
                actor='diagnosis_agent',
            )
            trace.record(
                'state_transition',
                'diagnosis_agent',
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
                    'resolve pinned diagnosis Prompt and MCP catalog',
                )
                trace.record(
                    'retrieval',
                    'prompt_registry',
                    {
                        'prompt_id': self.prompt.definition['prompt_id'],
                        'prompt_version': self.prompt.definition['version'],
                        'prompt_sha256': self.prompt.sha256,
                        'tool_contract_sha256': {
                            name: item['contract_sha256']
                            for name, item in governed_tool_catalog().items()
                        },
                    },
                    correlation_id=run_id,
                )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'PLANNING',
                    'trusted diagnosis context resolved',
                )
                gateway_result = self.gateway.plan(request)
                plan = gateway_result.get('plan')
                trace.record(
                    'plan',
                    'robot_llm_gateway',
                    {
                        'gateway_state': gateway_result.get('state'),
                        'request_sha256': gateway_result.get('request_sha256'),
                        'plan_sha256': sha256_json(plan) if plan else None,
                        'decision': plan.get('decision') if plan else None,
                    },
                    correlation_id=run_id,
                )
                if gateway_result['state'] != 'succeeded':
                    return self._terminal_failure(
                        store, trace, run_id, trace_id, current,
                        gateway_result, plan, steps, recovered,
                        experiment_run_id, started_at_ns,
                        self._gateway_error(gateway_result),
                    )
                decision = plan['decision']
                if decision in {'clarify', 'refuse'}:
                    reason = (
                        plan['clarification'] if decision == 'clarify'
                        else 'planner refused an unsafe diagnosis request'
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
                        run_id, trace_id,
                        'clarification_required'
                        if decision == 'clarify' else 'refused',
                        current, decision, experiment_run_id,
                        gateway_result, plan, steps, None, recovered,
                        reason, None, started_at_ns, trace,
                    )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'VALIDATING',
                    'validate exact five-step evidence plan',
                    plan=plan,
                )
                validate_cross_step_plan(plan, experiment_run_id)
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'EXECUTING',
                    'plan is bounded to governed MCP tools',
                )
                for step in plan['steps']:
                    self._check_deadline(started)
                    name = step['tool_name']
                    trace.record(
                        'tool_call',
                        'diagnosis_agent',
                        {
                            'step_id': step['step_id'],
                            'tool_name': name,
                            'tool_version': step['tool_version'],
                            'contract_sha256': step['contract_sha256'],
                            'input_sha256': sha256_json(step['inputs']),
                        },
                        correlation_id=run_id,
                    )
                    output = self.tool_client.call_tool(
                        name,
                        step['inputs'],
                        timeout_sec=self.tool_timeout_sec,
                    )
                    gate_passed, gate_reason = self._evidence_gate(
                        step,
                        output,
                        experiment_run_id,
                        outputs,
                    )
                    normalized = self._normalize_step(
                        step,
                        output,
                        gate_passed,
                        gate_reason,
                    )
                    steps.append(normalized)
                    outputs[name] = output
                    trace.record(
                        'tool_result',
                        'diagnosis_agent',
                        {
                            'step_id': step['step_id'],
                            'tool_name': name,
                            'input_sha256': output['input_sha256'],
                            'evidence_sha256': output['evidence_sha256'],
                            'citation_count': len(output['citations']),
                            'evidence_gate_passed': gate_passed,
                            'evidence_gate_reason': gate_reason,
                        },
                        correlation_id=run_id,
                    )
                    if not gate_passed:
                        current = self._transition(
                            store, trace, run_id, current, 'ABORTED', gate_reason,
                        )
                        return self._result(
                            run_id, trace_id, 'blocked_by_evidence', current,
                            decision, experiment_run_id, gateway_result, plan,
                            steps, None, recovered, gate_reason, None,
                            started_at_ns, trace,
                        )
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'VERIFYING',
                    'all hash-bound evidence stages completed',
                )
                conclusion = self._conclusion(experiment_run_id, outputs)
                current = self._transition(
                    store,
                    trace,
                    run_id,
                    current,
                    'SUCCEEDED',
                    'diagnosis report is reproducible and non-causal',
                )
                return self._result(
                    run_id, trace_id, 'succeeded', current, decision,
                    experiment_run_id, gateway_result, plan, steps,
                    conclusion, recovered, None, None, started_at_ns, trace,
                )
            except (
                ContractError,
                DiagnosisAgentError,
                DiagnosisClientError,
                RegistryConflictError,
                RegistryContractError,
                OSError,
            ) as error:
                return self._terminal_failure(
                    store, trace, run_id, trace_id, current,
                    gateway_result, plan, steps, recovered,
                    experiment_run_id, started_at_ns,
                    str(error) or error.__class__.__name__,
                )

    def _evidence_gate(self, step, output, run_id, previous):
        validate_instance(
            output,
            self.tool_result_schema,
            f"MCP result for {step['tool_name']}",
        )
        name = step['tool_name']
        if output['tool_name'] != name or output['tool_version'] != '0.1.0':
            return False, 'MCP tool identity or version changed'
        if output['input_sha256'] != sha256_json(step['inputs']):
            return False, 'MCP result is not bound to planned inputs'
        if output['safety_class'] != governed_tool_catalog()[name][
            'safety_class'
        ]:
            return False, 'MCP safety class changed'
        evidence = output['evidence']
        if name == 'list_experiment_runs':
            available = {
                item.get('run_id') for item in evidence.get('runs', [])
            }
            return (
                (True, 'selected run exists in verified catalog')
                if run_id in available else
                (False, 'selected run is absent from verified catalog')
            )
        if (
            name in {
                'inspect_experiment_run',
                'analyze_experiment_run',
                'materialize_diagnosis_report',
            }
            and evidence.get('run_id') != run_id
        ):
            return False, 'MCP evidence run_id changed'
        if name == 'inspect_experiment_run':
            sources = evidence.get('sources', [])
            passed = bool(sources) and all(
                item.get('sha256') for item in sources
            )
            return (
                (True, 'manifest and source hashes are verified')
                if passed else
                (False, 'inspection lacks verified source hashes')
            )
        if name == 'analyze_experiment_run':
            inspected = previous['inspect_experiment_run']['evidence']
            inspected_hashes = {
                item['name']: item['sha256'] for item in inspected['sources']
            }
            passed = (
                evidence.get('source_hashes') == inspected_hashes
                and bool(evidence.get('analysis_sha256'))
                and isinstance(evidence.get('anomaly_windows'), list)
                and isinstance(evidence.get('candidate_mechanisms'), list)
            )
            return (
                (True, 'analysis is bound to inspected source hashes')
                if passed else
                (False, 'analysis evidence is not bound to inspected sources')
            )
        if name == 'retrieve_robotics_knowledge':
            passed = bool(evidence.get('index_content_sha256')) and (
                evidence.get('abstained') is True or bool(output['citations'])
            )
            return (
                (True, 'retrieval is cited or explicitly abstained')
                if passed else
                (False, 'retrieval has neither citations nor abstention')
            )
        analyzed = previous['analyze_experiment_run']['evidence']
        passed = (
            evidence.get('analysis_sha256') == analyzed['analysis_sha256']
            and bool(evidence.get('bundle_sha256'))
            and bool(evidence.get('artifact_hashes'))
        )
        return (
            (True, 'report artifacts are bound to deterministic analysis')
            if passed else
            (False, 'report is not bound to deterministic analysis')
        )

    @staticmethod
    def _normalize_step(step, output, passed, reason):
        return {
            'step_id': step['step_id'],
            'tool_name': step['tool_name'],
            'tool_version': step['tool_version'],
            'contract_sha256': step['contract_sha256'],
            'input_sha256': output['input_sha256'],
            'evidence_sha256': output['evidence_sha256'],
            'safety_class': output['safety_class'],
            'citation_count': len(output['citations']),
            'status': 'succeeded',
            'evidence_gate_passed': passed,
            'evidence_gate_reason': reason,
        }

    @staticmethod
    def _conclusion(run_id, outputs):
        analysis = outputs['analyze_experiment_run']['evidence']
        retrieval = outputs['retrieve_robotics_knowledge']
        report = outputs['materialize_diagnosis_report']['evidence']
        return {
            'run_id': run_id,
            'analysis_sha256': analysis['analysis_sha256'],
            'anomaly_window_count': len(analysis['anomaly_windows']),
            'candidate_mechanisms': analysis['candidate_mechanisms'],
            'retrieval_abstained': retrieval['evidence']['abstained'],
            'citation_count': len(retrieval['citations']),
            'report_bundle_sha256': report['bundle_sha256'],
            'artifact_directory': report['artifact_directory'],
            'artifact_hashes': report['artifact_hashes'],
            'root_cause_proven': False,
            'causality_boundary': (
                'Mechanisms are evidence-backed hypotheses; controlled '
                'intervention is required before claiming root cause.'
            ),
        }

    def _check_deadline(self, started):
        if self.monotonic() - started > self.max_duration_sec:
            raise DiagnosisAgentError('diagnosis Agent wall-clock limit exceeded')

    @contextmanager
    def _exclusive_lease(self):
        self.lease_path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.lease_path.open('a+', encoding='utf-8')
        try:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DiagnosisAgentError(
                    'another diagnosis Agent is already active'
                ) from error
            yield
        finally:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()

    def _recover_unfinished_runs(self):
        with AgentRunStore(self.database_path, self.clock_ns) as store:
            return store.fail_closed_recover(actor='diagnosis_agent_startup')

    def _transition(
        self, store, trace, run_id, current, target, reason, plan=None,
    ):
        store.transition(
            run_id,
            target,
            current,
            'diagnosis_agent',
            reason,
            plan=plan,
        )
        trace.record(
            'state_transition',
            'diagnosis_agent',
            {'from_state': current, 'to_state': target, 'reason': reason},
            correlation_id=run_id,
        )
        return target

    def _terminal_failure(
        self, store, trace, run_id, trace_id, current, gateway_result, plan,
        steps, recovered, experiment_run_id, started_at_ns, message,
    ):
        trace.record(
            'error',
            'diagnosis_agent',
            {'state': current, 'error': message[:1000]},
            correlation_id=run_id,
        )
        current = self._transition(
            store, trace, run_id, current, 'FAILED', message[:1000],
        )
        return self._result(
            run_id, trace_id, 'failed', current,
            plan.get('decision') if plan else None,
            experiment_run_id, gateway_result, plan, steps, None,
            recovered, None, message[:1000], started_at_ns, trace,
        )

    @staticmethod
    def _gateway_error(result):
        error = result.get('error') or {}
        return (
            f"{error.get('code', 'gateway_failed')}: "
            f"{error.get('message', 'planner gateway failed')}"
        )

    def _result(
        self, run_id, trace_id, status, state, decision, experiment_run_id,
        gateway_result, plan, steps, conclusion, recovered, halt_reason,
        error, started_at_ns, trace,
    ):
        result = {
            'schema_version': 1,
            'run_id': run_id,
            'trace_id': trace_id,
            'status': status,
            'agent_state': state,
            'planner_decision': decision,
            'experiment_run_id': experiment_run_id,
            'gateway_result': gateway_result,
            'plan': plan,
            'steps': steps,
            'conclusion': conclusion,
            'recovered_runs': sorted(recovered),
            'halt_reason': halt_reason,
            'error': error,
            'started_at_ns': started_at_ns,
            'completed_at_ns': self.clock_ns(),
            'trace_file': str(trace.path),
        }
        validate_instance(result, self.result_schema, 'diagnosis Agent result')
        return result
