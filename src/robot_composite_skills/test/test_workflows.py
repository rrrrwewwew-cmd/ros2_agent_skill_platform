"""Tests for fixed project-one composite Skill evidence order."""

from pathlib import Path

from robot_composite_skills.workflows import CompositeWorkflowAdapter


ROOT = Path(__file__).resolve().parents[3]


class _Adapter:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def invoke(self, inputs, timeout_sec):
        self.calls.append(inputs)
        return self.output


class _Observation:
    def __init__(self):
        self.calls = 0

    def invoke(self, timeout_sec):
        self.calls += 1
        return {
            'risk_found': True,
            'landmark_updated': True,
            'target_id': 'water_puddle',
        }


def _primitive_adapters(healthy=True, route_safe=True, reached=True):
    health = _Adapter({'safe_to_proceed': healthy})
    query = _Adapter({'found': True})
    preview = _Adapter({
        'safe_to_execute': route_safe,
        'route': {'path_sha256': 'a' * 64},
        'keepout': {'source_content_sha256': 'b' * 64},
    })
    navigation = _Adapter({
        'goal_reached': reached,
        'motion_command_sent': reached,
    })
    return health, query, preview, navigation


def _request():
    return {
        'goal_x': 0.0,
        'goal_y': 0.0,
        'goal_yaw_deg': 180.0,
        'keepout_profile': 'rbot_water_puddle_v2',
    }


def test_return_home_executes_exact_evidence_order():
    adapters = _primitive_adapters()
    workflow = CompositeWorkflowAdapter(
        ROOT,
        'return_home_safely',
        *adapters,
    )
    result = workflow.invoke(_request(), 120.0)
    workflow.validate_result(result)
    assert result['state'] == 'succeeded'
    assert [step['name'] for step in result['steps']] == [
        'check_robot_health',
        'query_semantic_target',
        'preview_safe_route',
        'navigate_to_approved_pose',
    ]


def test_unhealthy_robot_blocks_before_semantic_query():
    adapters = _primitive_adapters(healthy=False)
    workflow = CompositeWorkflowAdapter(
        ROOT,
        'return_home_safely',
        *adapters,
    )
    result = workflow.invoke(_request(), 120.0)
    workflow.validate_result(result)
    assert result['state'] == 'aborted'
    assert len(result['steps']) == 1
    assert adapters[1].calls == []


def test_observe_workflow_refreshes_risk_before_query():
    adapters = _primitive_adapters()
    observation = _Observation()
    workflow = CompositeWorkflowAdapter(
        ROOT,
        'observe_and_avoid_water_risk',
        *adapters,
        observation_adapter=observation,
    )
    result = workflow.invoke(_request(), 300.0)
    workflow.validate_result(result)
    assert observation.calls == 1
    assert [step['name'] for step in result['steps']][1] == (
        'observe_water_risk'
    )


def test_unsafe_route_never_calls_navigation():
    adapters = _primitive_adapters(route_safe=False)
    workflow = CompositeWorkflowAdapter(
        ROOT,
        'return_home_safely',
        *adapters,
    )
    result = workflow.invoke(_request(), 120.0)
    assert result['state'] == 'aborted'
    assert adapters[3].calls == []
    assert result['motion_command_sent'] is False
