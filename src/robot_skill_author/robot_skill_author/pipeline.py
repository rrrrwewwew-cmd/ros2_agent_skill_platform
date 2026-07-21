"""Bounded RAG-to-generation-to-governance Skill Author pipeline."""

import json
from pathlib import Path

from robot_llm_gateway.contracts import (
    ContractError,
    load_schema,
    validate_instance,
)
from robot_skill_registry import SkillRegistry
from safe_agent_core import validate_skill_manifest

from .contracts import (
    static_scan,
    validate_author_plan,
    validate_request_policy,
)


class SkillAuthorError(RuntimeError):
    """Report a failed authoring gate without activating a candidate."""


class SkillAuthorPipeline:
    """Generate, repair, validate, and stop at human approval."""

    def __init__(
        self,
        schema_directory,
        registry_database,
        retriever,
        generator,
        renderer,
        sandbox,
        max_repairs=2,
        dependency_resolver=None,
    ):
        if not isinstance(max_repairs, int) or not 0 <= max_repairs <= 2:
            raise SkillAuthorError('max_repairs must be an integer in [0, 2]')
        self.request_schema = load_schema(
            schema_directory,
            'skill_author_request.schema.json',
        )
        self.plan_schema = load_schema(
            schema_directory,
            'skill_author_plan.schema.json',
        )
        self.result_schema = load_schema(
            schema_directory,
            'skill_author_result.schema.json',
        )
        self.registry_database = Path(registry_database).expanduser()
        self.retriever = retriever
        self.generator = generator
        self.renderer = renderer
        self.sandbox = sandbox
        self.max_repairs = max_repairs
        self.dependency_resolver = dependency_resolver

    def run(self, request):
        """Run bounded repairs and register only a tested unapproved draft."""
        validate_instance(request, self.request_schema, 'Skill author request')
        validate_request_policy(request)
        citations = self._retrieve(request)
        dependency_records = self._dependencies(request)
        diagnostics = None
        latest_candidate = None
        latest_gates = []
        for attempt in range(1, self.max_repairs + 2):
            try:
                gateway_result = self.generator.generate(
                    request,
                    citations,
                    diagnostics,
                    attempt,
                )
                plan = gateway_result['plan']
                if plan['decision'] in {'clarify', 'refuse'}:
                    result = self._result(
                        request,
                        'clarification_required'
                        if plan['decision'] == 'clarify' else 'refused',
                        attempt,
                        None,
                        [],
                        citations,
                        None,
                        False,
                        plan.get('clarification') or plan['summary'],
                    )
                    return result
                draft = validate_author_plan(
                    plan,
                    request,
                    self.plan_schema,
                )
                latest_gates = [{
                    'name': 'schema',
                    'status': 'pass',
                    'evidence': {
                        'plan_schema': 'skill_author_plan.schema.json',
                        'gateway_request_sha256': gateway_result.get(
                            'request_sha256'
                        ),
                    },
                }]
                latest_candidate = self.renderer.render(
                    request,
                    draft,
                    attempt,
                    dependency_records,
                    citations,
                )
                validate_skill_manifest(latest_candidate['manifest'])
                static_evidence = static_scan(
                    latest_candidate['root'],
                    latest_candidate['expected_files'],
                )
                latest_gates.append({
                    'name': 'static',
                    'status': 'pass',
                    'evidence': static_evidence,
                })
                sandbox = self.sandbox.validate(latest_candidate)
                failed = self._append_sandbox_gates(latest_gates, sandbox)
                if failed:
                    diagnostics = (
                        f'{failed} gate failed: '
                        f'{json.dumps(sandbox.get(failed), sort_keys=True)}'
                    )[-1000:]
                    if attempt <= self.max_repairs:
                        continue
                    return self._result(
                        request,
                        'failed',
                        attempt,
                        latest_candidate,
                        latest_gates,
                        citations,
                        None,
                        False,
                        diagnostics,
                    )
                record = self._register_tested_candidate(
                    latest_candidate,
                    request['request_id'],
                )
                return self._result(
                    request,
                    'waiting_human_approval',
                    attempt,
                    latest_candidate,
                    latest_gates,
                    citations,
                    record,
                    True,
                    None,
                )
            except (ContractError, RuntimeError, OSError, ValueError) as error:
                diagnostics = str(error)[:1000]
                if attempt <= self.max_repairs:
                    continue
                return self._result(
                    request,
                    'failed',
                    attempt,
                    latest_candidate,
                    latest_gates,
                    citations,
                    None,
                    False,
                    diagnostics,
                )
        raise SkillAuthorError('unreachable authoring state')

    def _retrieve(self, request):
        query = (
            'ROS 2 Jazzy governed Skill composition, Registry lifecycle, '
            'approval, timeout, cancellation and fail-closed evidence for: '
            f"{request['description']}"
        )
        result = self.retriever.query(query, 'project2-v1', 3)
        if result.get('abstained') is True or not result.get('hits'):
            raise SkillAuthorError('RAG abstained; generation is not grounded')
        citations = [item['citation'] for item in result['hits']]
        if any(not item.get('chunk_sha256') for item in citations):
            raise SkillAuthorError('RAG citation lacks a chunk hash')
        return citations

    def _dependencies(self, request):
        if self.dependency_resolver is not None:
            records = self.dependency_resolver(
                request['allowed_dependencies']
            )
            missing = set(request['allowed_dependencies']) - set(records)
            if missing:
                raise SkillAuthorError(
                    f'dependency resolver omitted: {sorted(missing)}'
                )
            return records
        records = {}
        with SkillRegistry(self.registry_database) as registry:
            active = {item['name']: item for item in registry.list_skills('ACTIVE')}
        for name in request['allowed_dependencies']:
            record = active.get(name)
            if record is None:
                raise SkillAuthorError(
                    f'allowed dependency is not ACTIVE: {name}'
                )
            records[name] = record
        return records

    @staticmethod
    def _append_sandbox_gates(gates, result):
        for name in ('build', 'unit_test', 'simulation'):
            evidence = result.get(name)
            if evidence is None:
                gates.append({
                    'name': name,
                    'status': 'fail',
                    'evidence': {'reason': 'prior gate stopped execution'},
                })
                return name
            status = 'pass' if evidence.get('returncode') == 0 else 'fail'
            gates.append({
                'name': name,
                'status': status,
                'evidence': evidence,
            })
            if status == 'fail':
                return name
        return None

    def _register_tested_candidate(self, candidate, actor):
        manifest = candidate['manifest']
        name = manifest['name']
        version = manifest['version']
        with SkillRegistry(self.registry_database) as registry:
            record = registry.register_manifest(
                manifest,
                artifact_hash=candidate['artifact_hash'],
                actor=actor,
            )
            transitions = (
                ('GENERATED', 'DRAFT', 'bounded renderer emitted candidate'),
                (
                    'STATIC_VALIDATED',
                    'GENERATED',
                    'schema and static policy gates passed',
                ),
                ('BUILT', 'STATIC_VALIDATED', 'isolated colcon build passed'),
                ('UNIT_TESTED', 'BUILT', 'generated unit tests passed'),
                (
                    'SIMULATION_TESTED',
                    'UNIT_TESTED',
                    'bounded simulation fixtures passed',
                ),
            )
            for target, current, reason in transitions:
                record = registry.advance(
                    name,
                    version,
                    target,
                    current,
                    actor,
                    reason,
                )
        return record

    def _result(
        self, request, status, attempts, candidate, gates, citations,
        registry_record, approval_required, error,
    ):
        result = {
            'schema_version': 1,
            'request_id': request['request_id'],
            'status': status,
            'attempt_count': attempts,
            'candidate': candidate,
            'gates': gates,
            'rag_citations': citations,
            'registry_record': registry_record,
            'approval_required': approval_required,
            'error': error,
        }
        validate_instance(result, self.result_schema, 'Skill author result')
        return result
