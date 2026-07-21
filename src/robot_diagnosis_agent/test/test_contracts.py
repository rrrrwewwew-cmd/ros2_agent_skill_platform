"""Tests for immutable diagnosis tool contracts."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory

from robot_diagnosis_agent.contracts import (
    governed_tool_catalog,
    validate_prompt_catalog,
)
from robot_llm_gateway.gateway import build_plan_request, LlmGateway
from robot_llm_gateway.prompt_registry import PromptRegistry
from robot_llm_gateway.providers import FakeProvider

from .test_loop import _plan, RUN_ID


ROOT = Path(__file__).resolve().parents[3]


def test_prompt_tool_hashes_match_code_contracts():
    registry = PromptRegistry(ROOT / 'prompts', ROOT / 'schemas')
    prompt = registry.resolve('experiment_diagnosis_planner', '0.1.0')
    validate_prompt_catalog(prompt)
    assert len(governed_tool_catalog()) == 5


def test_gateway_uses_prompt_selected_diagnosis_schema():
    registry = PromptRegistry(ROOT / 'prompts', ROOT / 'schemas')
    prompt = registry.resolve('experiment_diagnosis_planner', '0.1.0')
    gateway = LlmGateway(
        FakeProvider(_plan()),
        registry,
        ROOT / 'schemas',
    )
    request = build_plan_request(
        'diagnosis_gateway_test',
        'fake',
        'fake-v1',
        prompt,
        'diagnose the selected run',
        context={'run_id': RUN_ID, 'distribution': 'project2-v1'},
    )
    result = gateway.plan(request)
    assert result['state'] == 'succeeded'
    assert result['plan']['steps'][4]['tool_name'] == (
        'materialize_diagnosis_report'
    )


def test_mcp_package_owns_complete_tool_schema_bundle():
    mcp_schemas = Path(
        get_package_share_directory('robot_diagnosis_mcp')
    ) / 'schemas'
    assert (mcp_schemas / 'mcp_tool_result.schema.json').is_file()
    assert (mcp_schemas / 'diagnosis_report_bundle.schema.json').is_file()
