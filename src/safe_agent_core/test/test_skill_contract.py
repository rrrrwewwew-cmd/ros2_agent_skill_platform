"""Tests for the frozen Phase 0 Skill contract."""

from copy import deepcopy
from pathlib import Path

import pytest
from safe_agent_core import SkillContractError, validate_skill_manifest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPOSITORY_ROOT / 'skills/check_robot_health/skill.yaml'


def load_example():
    """Load the repository reference Skill."""
    return yaml.safe_load(EXAMPLE.read_text(encoding='utf-8'))


def test_reference_skill_is_valid():
    """The Phase 0 health Skill should satisfy the frozen contract."""
    validated = validate_skill_manifest(load_example())
    assert validated['name'] == 'check_robot_health'
    assert validated['safety_level'] == 'read_only'


@pytest.mark.parametrize('topic', ['/cmd_vel', '/cmd_vel_unstamped'])
def test_direct_velocity_write_is_rejected(topic):
    """No generated Skill may directly publish base velocity."""
    manifest = deepcopy(load_example())
    manifest['safety_level'] = 'controlled'
    manifest['ros_permissions']['topics_write'] = [topic]
    with pytest.raises(SkillContractError, match='direct velocity'):
        validate_skill_manifest(manifest)


def test_high_safety_skill_requires_human_approval():
    """High-impact Skills cannot opt out of approval."""
    manifest = deepcopy(load_example())
    manifest['safety_level'] = 'high'
    manifest['requires_human_approval'] = False
    with pytest.raises(SkillContractError, match='require human approval'):
        validate_skill_manifest(manifest)


def test_relative_ros_name_is_rejected():
    """Permission rules require auditable absolute ROS names."""
    manifest = deepcopy(load_example())
    manifest['ros_permissions']['topics_read'] = ['diagnostics']
    with pytest.raises(SkillContractError, match='absolute ROS names'):
        validate_skill_manifest(manifest)
