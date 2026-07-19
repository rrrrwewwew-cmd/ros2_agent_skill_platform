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


class SemanticTargetQueryAdapter:
    """Query only approved persistent semantic map profiles."""

    entrypoint = 'robot_semantic_skills.query:query_semantic_target'
    safety_level = 'read_only'
    permissions = {
        'topics_read': [],
        'topics_write': [],
        'services': [],
        'actions': [],
    }

    def __init__(self, repository_root, profile_paths=None,
                 runner=subprocess.run):
        self.repository_root = Path(repository_root).resolve()
        defaults = {
            'semantic_landmarks_v1': (
                '~/.ros/semantic_nav_eval/semantic_landmarks_v1.json'
            ),
            'rbot_water_puddle_v2': (
                '~/.ros/semantic_nav_eval/'
                'rbot_water_puddle_landmarks_v2.json'
            ),
        }
        configured = profile_paths or defaults
        self.profile_paths = {
            name: Path(path).expanduser().resolve()
            for name, path in configured.items()
        }
        self.runner = runner

    def invoke(self, inputs, timeout_sec):
        """Run a fixed module with a code-owned store profile mapping."""
        profile = inputs.get('map_profile')
        target_id = inputs.get('target_id')
        store_file = self.profile_paths.get(profile)
        if store_file is None:
            raise SkillAdapterError('semantic map profile is not approved')
        command = [
            sys.executable,
            '-m',
            'robot_semantic_skills.query_cli',
            '--store-file',
            str(store_file),
            '--map-profile',
            profile,
            '--target-id',
            target_id,
        ]
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec),
                check=False,
            )
        except subprocess.TimeoutExpired as exception:
            raise SkillAdapterError('semantic map query timed out') from exception
        except OSError as exception:
            raise SkillAdapterError(
                f'semantic map query could not start: {exception}'
            ) from exception
        if completed.returncode not in {0, 3, 4, 5}:
            raise SkillAdapterError(
                f'semantic map query exited {completed.returncode}'
            )
        try:
            result = json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exception:
            raise SkillAdapterError(
                'semantic map query returned invalid JSON'
            ) from exception
        self.validate_result(result)
        if result['query'] != {
            'map_profile': profile,
            'target_id': target_id,
        }:
            raise SkillAdapterError('semantic query output identity mismatch')
        return result

    def validate_result(self, result):
        """Validate structural and semantic query postconditions."""
        schema_path = (
            self.repository_root /
            'skills/query_semantic_target/schemas/'
            'semantic_target_query_result.schema.json'
        )
        try:
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(result)
        except (OSError, json.JSONDecodeError, ValidationError) as exception:
            raise SkillAdapterError(
                'semantic query result violates its JSON Schema'
            ) from exception
        found = result['state'] == 'found'
        if result['found'] is not found:
            raise SkillAdapterError('semantic query found flag is inconsistent')
        if found:
            if result['landmark'] is None or result['reasons']:
                raise SkillAdapterError(
                    'found semantic query must contain evidence without errors'
                )
            if result['source']['frame_id'] != 'map':
                raise SkillAdapterError(
                    'found semantic target must use the map frame'
                )
            if result['source']['content_sha256'] is None:
                raise SkillAdapterError(
                    'found semantic target requires source content hash'
                )
            if (
                result['landmark']['target_id'] !=
                result['query']['target_id']
            ):
                raise SkillAdapterError(
                    'semantic landmark identity is inconsistent'
                )
            observations = result['landmark']['observations']
            if (
                observations['total'] !=
                observations['accepted'] + observations['rejected']
            ):
                raise SkillAdapterError(
                    'semantic observation counters are inconsistent'
                )
        elif result['landmark'] is not None or not result['reasons']:
            raise SkillAdapterError(
                'non-found semantic query must contain a reason only'
            )
        if (
            result['source']['store_profile'] !=
            result['query']['map_profile']
        ):
            raise SkillAdapterError('semantic source profile is inconsistent')
        if result['state'] == 'not_found' and (
            result['source']['content_sha256'] is None or
            result['source']['frame_id'] != 'map'
        ):
            raise SkillAdapterError(
                'not-found query requires valid map source evidence'
            )
        if result['state'] == 'unavailable' and (
            result['source']['content_sha256'] is not None or
            result['source']['frame_id'] is not None
        ):
            raise SkillAdapterError(
                'unavailable query cannot claim parsed source evidence'
            )


class SafeRoutePreviewAdapter:
    """Execute only the approved read-only Nav2 path preview."""

    entrypoint = 'robot_navigation_skills.preview:preview_safe_route'
    safety_level = 'read_only'
    permissions = {
        'topics_read': [],
        'topics_write': [],
        'services': ['/global_costmap/get_costmap'],
        'actions': ['/compute_path_to_pose'],
    }

    def __init__(self, repository_root, use_sim_time=False,
                 runner=subprocess.run):
        self.repository_root = Path(repository_root).resolve()
        self.use_sim_time = bool(use_sim_time)
        self.runner = runner

    def invoke(self, inputs, timeout_sec):
        """Call fixed ROS endpoints through a bounded module process."""
        command = [
            sys.executable,
            '-m',
            'robot_navigation_skills.preview_ros',
            '--goal-x',
            str(inputs.get('goal_x')),
            '--goal-y',
            str(inputs.get('goal_y')),
            '--goal-yaw-deg',
            str(inputs.get('goal_yaw_deg')),
            '--keepout-profile',
            str(inputs.get('keepout_profile')),
            '--ros-args',
            '-p',
            f'use_sim_time:={str(self.use_sim_time).lower()}',
        ]
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec),
                check=False,
            )
        except subprocess.TimeoutExpired as exception:
            raise SkillAdapterError('route preview timed out') from exception
        except OSError as exception:
            raise SkillAdapterError(
                f'route preview could not start: {exception}'
            ) from exception
        if completed.returncode not in {0, 3, 4, 5}:
            raise SkillAdapterError(
                f'route preview exited {completed.returncode}'
            )
        try:
            result = json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exception:
            raise SkillAdapterError(
                'route preview returned invalid JSON'
            ) from exception
        self.validate_result(result)
        expected_request = {
            'goal': {
                'frame_id': 'map',
                'x': float(inputs['goal_x']),
                'y': float(inputs['goal_y']),
                'yaw_deg': float(inputs['goal_yaw_deg']),
            },
            'keepout_profile': inputs['keepout_profile'],
        }
        if result['request'] != expected_request:
            raise SkillAdapterError('route preview output identity mismatch')
        return result

    def validate_result(self, result):
        """Validate structural and safety-decision postconditions."""
        schema_path = (
            self.repository_root /
            'skills/preview_safe_route/schemas/'
            'safe_route_preview_result.schema.json'
        )
        try:
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(result)
        except (OSError, json.JSONDecodeError, ValidationError) as exception:
            raise SkillAdapterError(
                'route preview result violates its JSON Schema'
            ) from exception
        safe = result['state'] == 'safe'
        if result['safe_to_execute'] is not safe:
            raise SkillAdapterError(
                'route preview readiness state is inconsistent'
            )
        if result['motion_command_sent'] is not False:
            raise SkillAdapterError(
                'read-only route preview cannot report motion'
            )
        if safe:
            planner = result['planner']
            keepout = result['keepout']
            route = result['route']
            if result['reasons'] or route is None:
                raise SkillAdapterError(
                    'safe route preview requires route evidence only'
                )
            if not (
                planner['available']
                and planner['error_code'] == 0
                and planner['path_frame'] == 'map'
                and planner['observed_at_ns'] > 0
            ):
                raise SkillAdapterError(
                    'safe route preview has invalid planner evidence'
                )
            if not (
                keepout['active_in_global_costmap'] is True
                and keepout['global_center_cost'] >= 253
                and keepout['intersects'] is False
                and keepout['minimum_clearance_m'] > 0.0
            ):
                raise SkillAdapterError(
                    'safe route preview has invalid keepout evidence'
                )
            if route['goal_position_error_m'] > 0.25:
                raise SkillAdapterError(
                    'safe route preview does not reach requested goal'
                )
        elif not result['reasons']:
            raise SkillAdapterError(
                'non-safe route preview must include reasons'
            )


class ApprovedNavigationAdapter:
    """Execute one exact controlled Nav2 goal through a fixed module."""

    entrypoint = (
        'robot_controlled_navigation_skills.navigation:'
        'navigate_to_approved_pose'
    )
    safety_level = 'controlled'
    permissions = {
        'topics_read': [
            '/diagnostics',
            '/semantic_keepout/safety_ok',
            '/tf',
            '/tf_static',
            '/odom',
            '/scan',
        ],
        'topics_write': [],
        'services': [
            '/lifecycle_manager_navigation/is_active',
            '/global_costmap/get_costmap',
            '/navigate_to_pose/_action/cancel_goal',
        ],
        'actions': ['/compute_path_to_pose', '/navigate_to_pose'],
    }

    def __init__(self, repository_root, use_sim_time=False,
                 runner=subprocess.run, cancel_runner=subprocess.run):
        self.repository_root = Path(repository_root).resolve()
        self.use_sim_time = bool(use_sim_time)
        self.runner = runner
        self.cancel_runner = cancel_runner

    @staticmethod
    def _required_inputs(inputs):
        required = {
            'goal_x', 'goal_y', 'goal_yaw_deg', 'keepout_profile',
            'approved_path_sha256', 'approved_semantic_map_sha256',
        }
        missing = sorted(required - inputs.keys())
        if missing:
            raise SkillAdapterError(
                f'navigation inputs are missing: {missing}'
            )

    def _cancel_all_navigation_goals(self):
        command = [
            sys.executable,
            '-m',
            'robot_controlled_navigation_skills.cancel_ros',
            '--ros-args',
            '-p',
            f'use_sim_time:={str(self.use_sim_time).lower()}',
        ]
        try:
            completed = self.cancel_runner(
                command,
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exception:
            raise SkillAdapterError(
                'navigation timed out and emergency cancellation failed'
            ) from exception
        if completed.returncode != 0:
            raise SkillAdapterError(
                'navigation timed out and emergency cancellation was rejected'
            )

    def invoke(self, inputs, timeout_sec):
        """Run the fixed controlled adapter with an emergency cancel margin."""
        self._required_inputs(inputs)
        command = [
            sys.executable,
            '-m',
            'robot_controlled_navigation_skills.navigation_ros',
            '--goal-x',
            str(inputs['goal_x']),
            '--goal-y',
            str(inputs['goal_y']),
            '--goal-yaw-deg',
            str(inputs['goal_yaw_deg']),
            '--keepout-profile',
            str(inputs['keepout_profile']),
            '--approved-path-sha256',
            str(inputs['approved_path_sha256']),
            '--approved-semantic-map-sha256',
            str(inputs['approved_semantic_map_sha256']),
            '--ros-args',
            '-p',
            f'use_sim_time:={str(self.use_sim_time).lower()}',
        ]
        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec),
                check=False,
            )
        except subprocess.TimeoutExpired as exception:
            self._cancel_all_navigation_goals()
            raise SkillAdapterError(
                'approved navigation timed out; cancellation requested'
            ) from exception
        except OSError as exception:
            raise SkillAdapterError(
                f'approved navigation could not start: {exception}'
            ) from exception
        if completed.returncode not in {0, 3, 4, 5, 6, 7}:
            raise SkillAdapterError(
                f'approved navigation exited {completed.returncode}'
            )
        try:
            result = json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exception:
            raise SkillAdapterError(
                'approved navigation returned invalid JSON'
            ) from exception
        self.validate_result(result)
        expected_request = {
            'goal': {
                'frame_id': 'map',
                'x': float(inputs['goal_x']),
                'y': float(inputs['goal_y']),
                'yaw_deg': float(inputs['goal_yaw_deg']),
            },
            'keepout_profile': inputs['keepout_profile'],
            'approved_preview': {
                'path_sha256': inputs['approved_path_sha256'],
                'semantic_map_sha256': inputs[
                    'approved_semantic_map_sha256'
                ],
            },
        }
        if result['request'] != expected_request:
            raise SkillAdapterError(
                'approved navigation output identity mismatch'
            )
        return result

    def validate_result(self, result):
        """Validate typed result and physical postconditions."""
        schema_path = (
            self.repository_root /
            'skills/navigate_to_approved_pose/schemas/'
            'navigation_result.schema.json'
        )
        try:
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(result)
        except (OSError, json.JSONDecodeError, ValidationError) as exception:
            raise SkillAdapterError(
                'approved navigation result violates its JSON Schema'
            ) from exception
        succeeded = result['state'] == 'succeeded'
        if result['goal_reached'] is not succeeded:
            raise SkillAdapterError(
                'approved navigation goal state is inconsistent'
            )
        if succeeded:
            preflight = result['preflight']
            navigation = result['navigation']
            postcondition = result['postcondition']
            if result['reasons']:
                raise SkillAdapterError(
                    'successful navigation cannot include failure reasons'
                )
            if not (
                preflight['allowed'] is True
                and preflight['health_state'] == 'healthy'
                and preflight['preview_state'] == 'safe'
                and preflight['path_identity_matches'] is True
                and preflight['semantic_identity_matches'] is True
                and preflight['global_center_cost'] >= 253
                and preflight['minimum_clearance_m'] > 0.0
            ):
                raise SkillAdapterError(
                    'successful navigation has invalid preflight evidence'
                )
            if not (
                result['motion_command_sent'] is True
                and navigation['goal_accepted'] is True
                and navigation['result_status'] == 4
                and navigation['nav2_error_code'] == 0
            ):
                raise SkillAdapterError(
                    'successful navigation has invalid Nav2 evidence'
                )
            if not (
                postcondition['goal_position_error_m'] <= 0.25
                and postcondition['goal_yaw_error_deg'] <= 15.0
                and postcondition['entered_keepout'] is False
                and postcondition['safety_remained_ok'] is True
                and postcondition['robot_stopped'] is True
            ):
                raise SkillAdapterError(
                    'successful navigation has invalid physical postconditions'
                )
        elif not result['reasons']:
            raise SkillAdapterError(
                'non-success navigation must include reasons'
            )
