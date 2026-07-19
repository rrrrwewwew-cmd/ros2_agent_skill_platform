"""Plan-only LLM Gateway with prompt pins and fail-closed validation."""

import json
from time import monotonic

from robot_llm_gateway.contracts import (
    canonical_json,
    ContractError,
    load_schema,
    sha256_json,
    validate_instance,
)
from robot_llm_gateway.prompt_registry import PromptRegistryError
from robot_llm_gateway.providers import ProviderError


class LlmGateway:
    """Generate a read-only plan without executing any Skill."""

    def __init__(self, provider, prompt_registry, schema_dir):
        """Bind one provider to trusted prompt and schema registries."""
        self.provider = provider
        self.prompt_registry = prompt_registry
        self.schema_dir = schema_dir
        self.request_schema = load_schema(
            schema_dir,
            'llm_plan_request.schema.json',
        )
        self.plan_schema = load_schema(schema_dir, 'agent_plan.schema.json')
        self.result_schema = load_schema(
            schema_dir,
            'llm_gateway_result.schema.json',
        )

    def plan(self, request):
        """Call the configured model and return a normalized bounded result."""
        validate_instance(request, self.request_schema, 'LLM plan request')
        request_hash = sha256_json(request)
        started = monotonic()
        empty_runtime = _runtime((monotonic() - started) * 1000.0)
        if request['provider'] != self.provider.name:
            return self._failure(
                request,
                request_hash,
                'provider_configuration',
                'request provider does not match configured provider',
                empty_runtime,
            )
        try:
            prompt = self.prompt_registry.resolve(
                request['prompt_id'],
                request['prompt_version'],
                request['prompt_sha256'],
            )
        except (PromptRegistryError, ContractError) as exc:
            return self._failure(
                request,
                request_hash,
                'prompt_mismatch',
                str(exc),
                _runtime((monotonic() - started) * 1000.0),
            )
        messages = self._messages(prompt.definition, request['task'])
        try:
            response = self.provider.complete(
                model=request['model'],
                messages=messages,
                max_output_tokens=request['max_output_tokens'],
                temperature=request['temperature'],
                timeout_sec=request['timeout_sec'],
            )
        except ProviderError as exc:
            return self._failure(
                request,
                request_hash,
                'provider_unavailable',
                str(exc),
                _runtime((monotonic() - started) * 1000.0),
            )
        runtime = _runtime(
            (monotonic() - started) * 1000.0,
            response,
        )
        try:
            plan = json.loads(response.content)
        except json.JSONDecodeError:
            return self._failure(
                request,
                request_hash,
                'provider_response_invalid',
                'assistant content is not a JSON object',
                runtime,
            )
        if not isinstance(plan, dict):
            return self._failure(
                request,
                request_hash,
                'provider_response_invalid',
                'assistant content must be a JSON object',
                runtime,
            )
        try:
            validate_instance(plan, self.plan_schema, 'agent plan')
            self._validate_catalog_bindings(plan, prompt.definition)
        except ContractError as exc:
            return self._failure(
                request,
                request_hash,
                'plan_schema_invalid',
                str(exc),
                runtime,
            )
        result = self._base_result(request, request_hash, runtime)
        result.update({'state': 'succeeded', 'plan': plan, 'error': None})
        validate_instance(result, self.result_schema, 'gateway result')
        return result

    def _messages(self, definition, task):
        """Build trusted system content and an untrusted JSON user payload."""
        schema_text = canonical_json(self.plan_schema)
        skills_text = canonical_json(definition['allowed_skills'])
        system = (
            f"{definition['system_message']}\n\n"
            f'Allowed Skill catalog:\n{skills_text}\n\n'
            f'Required output JSON Schema:\n{schema_text}'
        )
        return [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': canonical_json(task)},
        ]

    def _validate_catalog_bindings(self, plan, definition):
        """Require exact Skill pins, ordered steps, and valid Skill inputs."""
        catalog = {
            item['name']: item for item in definition['allowed_skills']
        }
        expected_step_ids = list(range(1, len(plan['steps']) + 1))
        actual_step_ids = [step['step_id'] for step in plan['steps']]
        if actual_step_ids != expected_step_ids:
            raise ContractError(
                'plan step ids must be consecutive and start at one'
            )
        for step in plan['steps']:
            skill = catalog.get(step['skill_name'])
            if skill is None:
                raise ContractError('plan references a Skill outside catalog')
            if step['skill_version'] != skill['version']:
                raise ContractError('plan Skill version is not pinned')
            if step['artifact_hash'] != skill['artifact_hash']:
                raise ContractError('plan Skill artifact hash is not pinned')
            if 'input_schema' in skill:
                validate_instance(
                    step['inputs'],
                    skill['input_schema'],
                    (
                        f"Skill inputs for step {step['step_id']} "
                        f"({step['skill_name']})"
                    ),
                )

    def _failure(self, request, request_hash, code, message, runtime):
        """Build and validate a fail-closed result without provider payloads."""
        result = self._base_result(request, request_hash, runtime)
        result.update({
            'state': 'failed',
            'plan': None,
            'error': {'code': code, 'message': message[:1000]},
        })
        validate_instance(result, self.result_schema, 'gateway result')
        return result

    @staticmethod
    def _base_result(request, request_hash, runtime):
        """Return fields shared by successful and failed gateway results."""
        return {
            'schema_version': 1,
            'request_id': request['request_id'],
            'provider': request['provider'],
            'model': request['model'],
            'prompt_id': request['prompt_id'],
            'prompt_version': request['prompt_version'],
            'prompt_sha256': request['prompt_sha256'],
            'request_sha256': request_hash,
            'runtime': runtime,
        }


def build_plan_request(
    request_id,
    provider,
    model,
    prompt,
    user_request,
    context=None,
    max_output_tokens=1024,
    timeout_sec=60.0,
    temperature=0.0,
):
    """Build a versioned plan request pinned to a resolved prompt record."""
    task = {'user_request': user_request}
    if context:
        task['context'] = context
    return {
        'schema_version': 1,
        'request_id': request_id,
        'provider': provider,
        'model': model,
        'prompt_id': prompt.definition['prompt_id'],
        'prompt_version': prompt.definition['version'],
        'prompt_sha256': prompt.sha256,
        'task': task,
        'max_output_tokens': max_output_tokens,
        'timeout_sec': timeout_sec,
        'temperature': temperature,
    }


def _runtime(latency_ms, response=None):
    """Normalize latency, request id, and token usage."""
    return {
        'latency_ms': round(max(0.0, latency_ms), 3),
        'provider_request_id': (
            response.request_id if response is not None else None
        ),
        'usage': {
            'input_tokens': (
                response.input_tokens if response is not None else None
            ),
            'output_tokens': (
                response.output_tokens if response is not None else None
            ),
            'total_tokens': (
                response.total_tokens if response is not None else None
            ),
        },
    }
