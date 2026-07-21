"""Tests for Skill Author request and Prompt contracts."""

from pathlib import Path

import pytest

from robot_llm_gateway.contracts import ContractError, load_schema
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_skill_author.cli import _fake_plan
from robot_skill_author.contracts import (
    validate_author_plan,
    validate_request_policy,
)

from .test_pipeline import _request


ROOT = Path(__file__).resolve().parents[3]


def test_skill_author_prompt_is_valid_and_pinned():
    prompt = PromptRegistry(
        ROOT / 'prompts',
        ROOT / 'schemas',
    ).resolve('skill_author_planner', '0.1.0')
    assert prompt.definition['task_mode'] == 'skill_author_plan'


def test_controlled_draft_cannot_bypass_approval():
    request = _request('author_test_004')
    request['safety_level'] = 'controlled'
    request['requires_human_approval'] = True
    request['allowed_dependencies'].append('navigate_to_approved_pose')
    plan = _fake_plan(request)
    plan['steps'][0]['inputs']['requires_human_approval'] = False
    with pytest.raises(ContractError, match='differs from request'):
        validate_author_plan(
            plan,
            request,
            load_schema(ROOT / 'schemas', 'skill_author_plan.schema.json'),
        )


def test_request_policy_rejects_direct_velocity():
    request = _request('author_test_005')
    request['description'] = 'Publish directly to /cmd_vel for fast control.'
    with pytest.raises(ContractError):
        validate_request_policy(request)
