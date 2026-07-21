"""Tests for plan-only gateway validation and safety boundaries."""

import json
from pathlib import Path

from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import FakeProvider, ProviderResponse


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _registry():
    """Return the repository Prompt Registry."""
    return PromptRegistry(
        REPOSITORY_ROOT / 'prompts',
        REPOSITORY_ROOT / 'schemas',
    )


def _valid_plan(prompt):
    """Build one catalog-pinned health-check plan."""
    skill = prompt.definition['allowed_skills'][0]
    return {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Inspect the current robot health.',
        'steps': [{
            'step_id': 1,
            'skill_name': skill['name'],
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': {},
            'reason': 'Use typed read-only evidence.',
            'expected_evidence': ['robot health result'],
        }],
        'clarification': None,
    }


def _request(prompt, provider='fake'):
    """Build one pinned test request."""
    return build_plan_request(
        request_id='gateway_test_001',
        provider=provider,
        model='fake-planner-v1',
        prompt=prompt,
        user_request='检查机器人健康状态',
    )


def test_fake_provider_produces_valid_plan_without_execution():
    """Offline planning returns metadata but invokes no Skill Runtime."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.1.0')
    provider = FakeProvider(_valid_plan(prompt))
    gateway = LlmGateway(
        provider,
        registry,
        REPOSITORY_ROOT / 'schemas',
    )
    result = gateway.plan(_request(prompt))
    assert result['state'] == 'succeeded'
    assert result['plan']['steps'][0]['skill_name'] == 'check_robot_health'
    assert provider.call_count == 1
    assert 'approval' not in json.dumps(result)


def test_prompt_hash_mismatch_stops_before_provider_call():
    """A changed prompt pin is rejected before model inference."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.1.0')
    provider = FakeProvider(_valid_plan(prompt))
    request = _request(prompt)
    request['prompt_sha256'] = '0' * 64
    result = LlmGateway(
        provider,
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(request)
    assert result['state'] == 'failed'
    assert result['error']['code'] == 'prompt_mismatch'
    assert provider.call_count == 0


def test_hallucinated_skill_hash_fails_local_catalog_binding():
    """Valid-looking JSON cannot replace a signed Skill artifact hash."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.1.0')
    plan = _valid_plan(prompt)
    plan['steps'][0]['artifact_hash'] = 'f' * 64
    result = LlmGateway(
        FakeProvider(plan),
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt))
    assert result['state'] == 'failed'
    assert result['error']['code'] == 'plan_schema_invalid'
    assert 'not pinned' in result['error']['message']


def test_provider_mismatch_fails_before_provider_call():
    """A request cannot silently select an unconfigured provider."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.1.0')
    provider = FakeProvider(_valid_plan(prompt))
    result = LlmGateway(
        provider,
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt, provider='xiaomi_mimo'))
    assert result['state'] == 'failed'
    assert result['error']['code'] == 'provider_configuration'
    assert provider.call_count == 0


def test_non_json_assistant_content_fails_closed():
    """Markdown or prose cannot pass the structured plan boundary."""

    class ProseProvider:
        """Return deliberately invalid assistant prose."""

        name = 'fake'

        def complete(self, **kwargs):
            """Return a non-JSON response."""
            del kwargs
            return ProviderResponse('looks safe', None, None, None, None)

    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.1.0')
    result = LlmGateway(
        ProseProvider(),
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt))
    assert result['state'] == 'failed'
    assert result['error']['code'] == 'provider_response_invalid'


def test_contract_aware_prompt_rejects_invented_skill_inputs():
    """Generic Plan JSON cannot smuggle invalid fields into a Skill call."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.2.0')
    skill = next(
        item for item in prompt.definition['allowed_skills']
        if item['name'] == 'query_semantic_target'
    )
    plan = {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Invalid coordinate-based semantic query.',
        'steps': [{
            'step_id': 1,
            'skill_name': skill['name'],
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': {'target_x': 4.5, 'target_y': 0.0},
            'reason': 'Deliberately invalid test input.',
            'expected_evidence': ['semantic target'],
        }],
        'clarification': None,
    }
    result = LlmGateway(
        FakeProvider(plan),
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt))
    assert result['state'] == 'failed'
    assert result['error']['code'] == 'plan_schema_invalid'
    assert 'query_semantic_target' in result['error']['message']
    assert 'Additional properties' in result['error']['message']


def test_contract_aware_prompt_accepts_exact_semantic_inputs():
    """A catalog-pinned Skill call succeeds with its exact input contract."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.2.0')
    skill = next(
        item for item in prompt.definition['allowed_skills']
        if item['name'] == 'query_semantic_target'
    )
    plan = {
        'schema_version': 1,
        'decision': 'plan',
        'summary': 'Query the named semantic target.',
        'steps': [{
            'step_id': 1,
            'skill_name': skill['name'],
            'skill_version': skill['version'],
            'artifact_hash': skill['artifact_hash'],
            'inputs': {
                'map_profile': 'semantic_landmarks_v1',
                'target_id': 'green_box',
            },
            'reason': 'The named target is present in the approved profile.',
            'expected_evidence': ['typed semantic target result'],
        }],
        'clarification': None,
    }
    result = LlmGateway(
        FakeProvider(plan),
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt))
    assert result['state'] == 'succeeded'


def test_plan_step_ids_must_be_consecutive():
    """Execution order cannot contain duplicates or hidden gaps."""
    registry = _registry()
    prompt = registry.resolve('robot_task_planner', '0.2.0')
    plan = _valid_plan(prompt)
    plan['steps'][0]['step_id'] = 2
    result = LlmGateway(
        FakeProvider(plan),
        registry,
        REPOSITORY_ROOT / 'schemas',
    ).plan(_request(prompt))
    assert result['state'] == 'failed'
    assert 'consecutive' in result['error']['message']
