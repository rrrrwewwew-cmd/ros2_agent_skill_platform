"""Tests for immutable Prompt Registry resolution."""

import json
from pathlib import Path

import pytest

from robot_llm_gateway.prompt_registry import (
    PromptRegistry,
    PromptRegistryError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _registry():
    """Return the repository Prompt Registry under test."""
    return PromptRegistry(
        REPOSITORY_ROOT / 'prompts',
        REPOSITORY_ROOT / 'schemas',
    )


def test_prompt_resolves_with_stable_hash_and_read_only_catalog():
    """The frozen planner prompt exposes only three read-only Skills."""
    prompt = _registry().resolve('robot_task_planner', '0.1.0')
    assert len(prompt.sha256) == 64
    assert prompt.definition['task_mode'] == 'plan_only'
    assert {
        item['permission'] for item in prompt.definition['allowed_skills']
    } == {'read_only'}
    assert {
        item['name'] for item in prompt.definition['allowed_skills']
    } == {
        'check_robot_health',
        'query_semantic_target',
        'preview_safe_route',
    }


def test_prompt_hash_pin_detects_any_definition_change():
    """An incorrect caller pin fails before any model request."""
    with pytest.raises(PromptRegistryError, match='hash'):
        _registry().resolve(
            'robot_task_planner',
            '0.1.0',
            expected_sha256='0' * 64,
        )


def test_prompt_path_escape_is_rejected():
    """Prompt identifiers cannot escape the trusted registry root."""
    with pytest.raises(PromptRegistryError, match='escapes'):
        _registry().resolve('../outside', '0.1.0')


def test_frozen_prompt_evals_pin_current_prompt_hash():
    """Evaluation cases cannot silently drift from the prompt under test."""
    eval_path = (
        REPOSITORY_ROOT /
        'prompts/robot_task_planner/evals/0.1.0.json'
    )
    evaluation = json.loads(eval_path.read_text(encoding='utf-8'))
    prompt = _registry().resolve('robot_task_planner', '0.1.0')
    assert evaluation['prompt_sha256'] == prompt.sha256
    assert len(evaluation['cases']) == 6
    assert {'plan', 'clarify', 'refuse'} == {
        case['expected']['decision'] for case in evaluation['cases']
    }


def test_contract_aware_prompt_pins_exact_skill_input_schemas():
    """Prompt v0.2.0 exposes bounded inputs rather than field-name prose."""
    prompt = _registry().resolve('robot_task_planner', '0.2.0')
    catalog = {
        item['name']: item for item in prompt.definition['allowed_skills']
    }
    assert catalog['query_semantic_target']['input_schema']['required'] == [
        'map_profile',
        'target_id',
    ]
    assert set(
        catalog['preview_safe_route']['input_schema']['required']
    ) == {
        'goal_x',
        'goal_y',
        'goal_yaw_deg',
        'keepout_profile',
    }
    evaluation = json.loads((
        REPOSITORY_ROOT /
        'prompts/robot_task_planner/evals/0.2.0.json'
    ).read_text(encoding='utf-8'))
    assert evaluation['prompt_sha256'] == prompt.sha256
