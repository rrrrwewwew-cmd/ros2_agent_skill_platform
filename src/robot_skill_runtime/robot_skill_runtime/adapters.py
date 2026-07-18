"""Explicit adapters for entrypoints approved by the Skill runtime."""

import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, ValidationError


class SkillAdapterError(RuntimeError):
    """Raised when an approved Skill process fails its runtime contract."""


class HealthSkillAdapter:
    """Execute the health Skill in a cancellable subprocess boundary."""

    entrypoint = 'safe_agent_core.health:check_robot_health'
    safety_level = 'read_only'
    permissions = {
        'topics_read': [
            '/diagnostics',
            '/semantic_keepout/safety_ok',
            '/tf',
            '/tf_static',
            '/camera/camera_info',
            '/camera/depth_image',
            '/camera/image',
            '/imu',
            '/odom',
            '/scan',
        ],
        'topics_write': [],
        'services': ['/lifecycle_manager_navigation/is_active'],
        'actions': [],
    }

    def __init__(self, repository_root, use_sim_time=False,
                 runner=subprocess.run):
        self.repository_root = Path(repository_root).resolve()
        self.use_sim_time = bool(use_sim_time)
        self.runner = runner

    def invoke(self, inputs, timeout_sec):
        """Run the fixed module command without a shell or arbitrary import."""
        command = [
            sys.executable,
            '-m',
            'safe_agent_core.health_ros',
            '--ros-args',
            '-p',
            f'use_sim_time:={str(self.use_sim_time).lower()}',
        ]
        required_sensors = inputs.get('required_sensors', [])
        if required_sensors:
            sensor_value = ','.join(required_sensors)
            command.extend([
                '-p', f'required_sensors:=[{sensor_value}]',
            ])
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec),
                check=False,
            )
        except subprocess.TimeoutExpired as exception:
            raise SkillAdapterError('health Skill timed out') from exception
        except OSError as exception:
            raise SkillAdapterError(
                f'health Skill process could not start: {exception}'
            ) from exception
        if completed.returncode not in {0, 3, 4}:
            raise SkillAdapterError(
                f'health Skill process exited {completed.returncode}'
            )
        try:
            result = json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exception:
            raise SkillAdapterError(
                'health Skill returned invalid JSON'
            ) from exception
        self.validate_result(result)
        return result

    def validate_result(self, result):
        """Validate structural and semantic postconditions."""
        schema_path = (
            self.repository_root /
            'schemas/robot_health_result.schema.json'
        )
        try:
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(result)
        except (OSError, json.JSONDecodeError, ValidationError) as exception:
            raise SkillAdapterError(
                'health Skill result violates its JSON Schema'
            ) from exception
        expected_safe = result['state'] == 'healthy'
        if result['safe_to_proceed'] is not expected_safe:
            raise SkillAdapterError(
                'health Skill result has inconsistent readiness state'
            )
        if result['state'] != 'healthy' and not result['reasons']:
            raise SkillAdapterError(
                'non-healthy result must include actionable reasons'
            )
