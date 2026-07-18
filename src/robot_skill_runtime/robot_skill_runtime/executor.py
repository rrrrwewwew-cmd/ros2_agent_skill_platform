"""Registry-gated bounded executor for approved robot Skills."""

import json
from pathlib import Path
import time

from jsonschema import Draft202012Validator, ValidationError
from robot_skill_registry import (
    AgentRunStore,
    RegistryConflictError,
    RegistryContractError,
    RegistryNotFoundError,
    ReleaseSignatureError,
    SkillRegistry,
    verify_signature_envelope,
)

from .adapters import (
    HealthSkillAdapter,
    SemanticTargetQueryAdapter,
    SkillAdapterError,
)
from .artifacts import ArtifactVerificationError, verify_artifact_lock
from .trace import TraceRecorder


class ExecutionPolicyError(ValueError):
    """Raised when an invocation violates Registry or permission policy."""


class SkillRuntimeError(RuntimeError):
    """Raised when execution cannot create a durable bounded run."""


class SkillExecutor:
    """Resolve, validate, execute, and verify one exact Skill version."""

    def __init__(self, database_path, repository_root, trace_directory,
                 use_sim_time=False, adapters=None, clock_ns=time.time_ns,
                 trusted_public_key=None):
        self.database_path = Path(database_path).expanduser()
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.trace_directory = Path(trace_directory).expanduser().resolve()
        self.trusted_public_key = Path(
            trusted_public_key or
            '~/.ros/robot_agent/keys/release_ed25519.pub.pem'
        ).expanduser().resolve()
        self.clock_ns = clock_ns
        default_adapter = HealthSkillAdapter(
            self.repository_root, use_sim_time=use_sim_time,
        )
        semantic_adapter = SemanticTargetQueryAdapter(self.repository_root)
        self.adapters = adapters or {
            default_adapter.entrypoint: default_adapter,
            semantic_adapter.entrypoint: semantic_adapter,
        }
        self._invocation_schema = self._load_schema('skill_invocation')
        self._result_schema = self._load_schema('skill_execution_result')

    def _load_schema(self, name):
        path = self.repository_root / f'schemas/{name}.schema.json'
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exception:
            raise SkillRuntimeError(f'cannot load runtime Schema: {path}') from exception

    def _validate_invocation(self, invocation):
        try:
            Draft202012Validator(self._invocation_schema).validate(invocation)
        except ValidationError as exception:
            raise ExecutionPolicyError(
                f'invalid invocation: {exception.message}'
            ) from exception

    @staticmethod
    def _input_schema(manifest):
        return {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            'type': 'object',
            'additionalProperties': False,
            'properties': manifest['inputs'],
        }

    def _resolve_active_skill(self, registry, invocation):
        try:
            record = registry.get_skill(
                invocation['skill_name'], invocation['skill_version'],
            )
        except RegistryNotFoundError as exception:
            raise ExecutionPolicyError('requested Skill version is not registered') from exception
        if record['state'] != 'ACTIVE':
            raise ExecutionPolicyError(
                f"Skill is not ACTIVE: current state is {record['state']}"
            )
        if record['artifact_hash'] != invocation['artifact_hash']:
            raise ExecutionPolicyError(
                'invocation artifact hash does not match Registry'
            )
        return record

    def _validate_execution_policy(self, record, inputs):
        manifest = record['manifest']
        entrypoint = manifest.get('entrypoint')
        adapter = self.adapters.get(entrypoint)
        if adapter is None:
            raise ExecutionPolicyError('Skill entrypoint has no approved adapter')
        if manifest['safety_level'] != adapter.safety_level:
            raise ExecutionPolicyError('adapter safety level mismatch')
        for permission_type, expected in adapter.permissions.items():
            actual = manifest['ros_permissions'][permission_type]
            if actual != expected:
                raise ExecutionPolicyError(
                    f'adapter permission mismatch: {permission_type}'
                )
        try:
            Draft202012Validator(
                self._input_schema(manifest)
            ).validate(inputs)
        except ValidationError as exception:
            raise ExecutionPolicyError(
                f'invalid Skill inputs: {exception.message}'
            ) from exception
        try:
            verify_artifact_lock(
                self.repository_root,
                record['name'],
                record['version'],
                record['artifact_hash'],
            )
        except ArtifactVerificationError as exception:
            raise ExecutionPolicyError(str(exception)) from exception
        try:
            verify_signature_envelope(
                record['signature'],
                self.trusted_public_key,
                expected_name=record['name'],
                expected_version=record['version'],
                expected_hash=record['artifact_hash'],
            )
        except ReleaseSignatureError as exception:
            raise ExecutionPolicyError(
                f'ACTIVE Skill release signature is invalid: {exception}'
            ) from exception
        return adapter

    @staticmethod
    def _transition(store, trace, run_id, current, target, actor,
                    reason, plan=None):
        run = store.transition(
            run_id,
            target,
            current,
            actor,
            reason,
            plan=plan,
        )
        trace.record(
            'state_transition',
            actor,
            {
                'from_state': current,
                'to_state': target,
                'reason': reason,
            },
            correlation_id=run_id,
        )
        return run

    def _result(self, invocation, status, agent_state, started_at_ns,
                output, error, trace):
        result = {
            'schema_version': 1,
            'run_id': invocation['run_id'],
            'trace_id': invocation['trace_id'],
            'skill_name': invocation['skill_name'],
            'skill_version': invocation['skill_version'],
            'status': status,
            'agent_state': agent_state,
            'started_at_ns': started_at_ns,
            'completed_at_ns': self.clock_ns(),
            'output': output,
            'error': error,
            'trace_file': str(trace.path),
        }
        Draft202012Validator(self._result_schema).validate(result)
        return result

    def execute(self, invocation):
        """Execute one invocation or return a durable failed result."""
        self._validate_invocation(invocation)
        started_at_ns = self.clock_ns()
        try:
            trace = TraceRecorder(
                self.trace_directory,
                invocation['run_id'],
                invocation['trace_id'],
                clock_ns=self.clock_ns,
            )
        except OSError as exception:
            raise SkillRuntimeError('cannot create Agent Trace') from exception
        with SkillRegistry(
                self.database_path, self.clock_ns) as registry, AgentRunStore(
                    self.database_path, self.clock_ns) as store:
            try:
                store.create_run(
                    invocation['run_id'],
                    invocation['trace_id'],
                    invocation,
                    actor='skill_runtime',
                )
            except (RegistryConflictError, RegistryContractError) as exception:
                raise SkillRuntimeError(str(exception)) from exception
            trace.record(
                'state_transition',
                'skill_runtime',
                {'from_state': None, 'to_state': 'IDLE'},
                correlation_id=invocation['run_id'],
            )
            current = 'IDLE'
            output = None
            try:
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'RETRIEVING', 'skill_runtime',
                    'resolve exact Skill version',
                )
                current = 'RETRIEVING'
                record = self._resolve_active_skill(registry, invocation)
                trace.record(
                    'retrieval',
                    'skill_registry',
                    {
                        'name': record['name'],
                        'version': record['version'],
                        'state': record['state'],
                        'artifact_hash': record['artifact_hash'],
                    },
                    correlation_id=invocation['run_id'],
                )
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'PLANNING', 'skill_runtime',
                    'active Skill resolved',
                )
                current = 'PLANNING'
                plan = {
                    'steps': [{
                        'skill': record['name'],
                        'version': record['version'],
                        'artifact_hash': record['artifact_hash'],
                        'inputs': invocation['inputs'],
                    }],
                }
                trace.record(
                    'plan', 'skill_runtime', plan,
                    correlation_id=invocation['run_id'],
                )
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'VALIDATING', 'skill_runtime',
                    'validate artifact inputs and permissions',
                    plan=plan,
                )
                current = 'VALIDATING'
                adapter = self._validate_execution_policy(
                    record, invocation['inputs'],
                )
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'EXECUTING', 'policy_validator',
                    'Registry artifact and permissions validated',
                )
                current = 'EXECUTING'
                trace.record(
                    'tool_call',
                    'skill_runtime',
                    {
                        'entrypoint': record['manifest']['entrypoint'],
                        'inputs': invocation['inputs'],
                        'timeout_sec': record['manifest']['timeout_sec'],
                    },
                    correlation_id=invocation['run_id'],
                )
                output = adapter.invoke(
                    invocation['inputs'], record['manifest']['timeout_sec'],
                )
                trace.record(
                    'tool_result',
                    'skill_runtime',
                    {'output': output},
                    correlation_id=invocation['run_id'],
                )
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'VERIFYING', 'skill_runtime',
                    'typed Skill result received',
                )
                current = 'VERIFYING'
                adapter.validate_result(output)
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'SUCCEEDED', 'postcondition_verifier',
                    'Skill result contract satisfied',
                )
                return self._result(
                    invocation, 'succeeded', 'SUCCEEDED', started_at_ns,
                    output, None, trace,
                )
            except (
                ExecutionPolicyError,
                SkillAdapterError,
                RegistryConflictError,
                RegistryContractError,
            ) as exception:
                error = str(exception)
                trace.record(
                    'error',
                    'skill_runtime',
                    {'state': current, 'error': error},
                    correlation_id=invocation['run_id'],
                )
                self._transition(
                    store, trace, invocation['run_id'], current,
                    'FAILED', 'skill_runtime', error,
                )
                return self._result(
                    invocation, 'failed', 'FAILED', started_at_ns,
                    output, error, trace,
                )
