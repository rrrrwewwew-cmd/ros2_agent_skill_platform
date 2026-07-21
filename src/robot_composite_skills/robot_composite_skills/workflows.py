"""Fixed composite workflows over already approved primitive adapters."""

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from jsonschema import Draft202012Validator, ValidationError


PROFILE = 'rbot_water_puddle_v2'
RESULT_SCHEMA = 'schemas/composite_skill_result.schema.json'
RETURN_HOME_PERMISSIONS = {
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
OBSERVE_PERMISSIONS = {
    **RETURN_HOME_PERMISSIONS,
    'topics_read': sorted({
        *RETURN_HOME_PERMISSIONS['topics_read'],
        '/camera/camera_info',
        '/camera/depth_image',
        '/camera/image',
    }),
}


class CompositeWorkflowError(RuntimeError):
    """Report an invalid request or primitive adapter failure."""


def observe_and_avoid_water_risk(*args, **kwargs):
    """Prevent direct execution outside the governed Runtime adapter."""
    raise CompositeWorkflowError(
        'observe_and_avoid_water_risk requires the governed Runtime adapter'
    )


def return_home_safely(*args, **kwargs):
    """Prevent direct execution outside the governed Runtime adapter."""
    raise CompositeWorkflowError(
        'return_home_safely requires the governed Runtime adapter'
    )


def _hash(value):
    text = json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _request(inputs):
    required = {'goal_x', 'goal_y', 'goal_yaw_deg', 'keepout_profile'}
    if set(inputs) != required:
        raise CompositeWorkflowError('composite inputs must match exact contract')
    normalized = {
        'goal_x': float(inputs['goal_x']),
        'goal_y': float(inputs['goal_y']),
        'goal_yaw_deg': float(inputs['goal_yaw_deg']),
        'keepout_profile': inputs['keepout_profile'],
    }
    if not all(math.isfinite(normalized[name]) for name in (
        'goal_x', 'goal_y', 'goal_yaw_deg',
    )):
        raise CompositeWorkflowError('goal values must be finite')
    if not -20.0 <= normalized['goal_x'] <= 20.0:
        raise CompositeWorkflowError('goal_x is outside approved bounds')
    if not -20.0 <= normalized['goal_y'] <= 20.0:
        raise CompositeWorkflowError('goal_y is outside approved bounds')
    if not -180.0 <= normalized['goal_yaw_deg'] <= 180.0:
        raise CompositeWorkflowError('goal_yaw_deg is outside approved bounds')
    if normalized['keepout_profile'] != PROFILE:
        raise CompositeWorkflowError('keepout profile is not approved')
    return normalized


class GroundedRiskObservationAdapter:
    """Run only project one's fixed grounded risk observer executable."""

    def __init__(
        self,
        output_root='~/.ros/robot_agent/composite_observations',
        store_file=(
            '~/.ros/semantic_nav_eval/rbot_water_puddle_landmarks_v2.json'
        ),
        use_sim_time=False,
        runner=subprocess.run,
        clock_ns=time.time_ns,
    ):
        self.output_root = Path(output_root).expanduser().resolve()
        self.store_file = Path(store_file).expanduser().resolve()
        self.use_sim_time = bool(use_sim_time)
        self.runner = runner
        self.clock_ns = clock_ns

    def invoke(self, timeout_sec):
        """Capture, reason, project, and persist one risk observation."""
        output = self.output_root / f'observation_{self.clock_ns()}'
        output.mkdir(parents=True, exist_ok=False)
        command = [
            sys.executable,
            '-m',
            'semantic_nav_eval.grounded_risk_observer',
            '--output-dir',
            str(output),
            '--store-file',
            str(self.store_file),
            '--target-id',
            'water_puddle',
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
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CompositeWorkflowError(
                f'grounded risk observer failed: {error}'
            ) from error
        result_path = output / 'observation_result.json'
        if completed.returncode != 0 or not result_path.is_file():
            raise CompositeWorkflowError(
                f'grounded risk observer exited {completed.returncode}'
            )
        try:
            result = json.loads(result_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise CompositeWorkflowError(
                'grounded risk observation result is invalid'
            ) from error
        if not (
            result.get('risk_found') is True
            and result.get('landmark_updated') is True
            and result.get('target_id') == 'water_puddle'
        ):
            raise CompositeWorkflowError(
                'grounded risk evidence did not update the water-puddle map'
            )
        return result


class CompositeWorkflowAdapter:
    """Execute a fixed evidence order under one outer Runtime approval."""

    safety_level = 'controlled'

    def __init__(
        self,
        repository_root,
        mode,
        health_adapter,
        query_adapter,
        preview_adapter,
        navigation_adapter,
        observation_adapter=None,
    ):
        if mode not in {'observe_and_avoid_water_risk', 'return_home_safely'}:
            raise CompositeWorkflowError('unsupported composite mode')
        self.repository_root = Path(repository_root).resolve()
        self.mode = mode
        self.entrypoint = f'robot_composite_skills.workflows:{mode}'
        self.permissions = (
            OBSERVE_PERMISSIONS if mode == 'observe_and_avoid_water_risk'
            else RETURN_HOME_PERMISSIONS
        )
        self.health = health_adapter
        self.query = query_adapter
        self.preview = preview_adapter
        self.navigation = navigation_adapter
        self.observation = observation_adapter

    @staticmethod
    def _step(steps, name, status, output):
        steps.append({
            'step_id': len(steps) + 1,
            'name': name,
            'status': status,
            'evidence_sha256': _hash(output),
            'output': output,
        })

    def invoke(self, inputs, timeout_sec):
        """Stop at the first unsafe primitive result; never improvise."""
        request = _request(inputs)
        steps = []
        reasons = []
        motion_sent = False
        try:
            sensors = ['/scan']
            if self.mode == 'observe_and_avoid_water_risk':
                sensors.extend(['/camera/image', '/camera/depth_image'])
            health = self.health.invoke(
                {'required_sensors': sensors},
                min(float(timeout_sec), 15.0),
            )
            healthy = health.get('safe_to_proceed') is True
            self._step(
                steps,
                'check_robot_health',
                'pass' if healthy else 'block',
                health,
            )
            if not healthy:
                reasons.append('robot health evidence blocked the workflow')
                return self._result(request, steps, reasons, False, False)
            if self.mode == 'observe_and_avoid_water_risk':
                if self.observation is None:
                    raise CompositeWorkflowError('observation adapter is absent')
                observation = self.observation.invoke(
                    min(float(timeout_sec), 180.0)
                )
                self._step(steps, 'observe_water_risk', 'pass', observation)
            semantic = self.query.invoke({
                'map_profile': PROFILE,
                'target_id': 'water_puddle',
            }, min(float(timeout_sec), 8.0))
            found = semantic.get('found') is True
            self._step(
                steps,
                'query_semantic_target',
                'pass' if found else 'block',
                semantic,
            )
            if not found:
                reasons.append('water-puddle semantic evidence is unavailable')
                return self._result(request, steps, reasons, False, False)
            preview = self.preview.invoke(request, min(float(timeout_sec), 12.0))
            safe = preview.get('safe_to_execute') is True
            self._step(
                steps,
                'preview_safe_route',
                'pass' if safe else 'block',
                preview,
            )
            if not safe:
                reasons.append('route preview failed the Keepout evidence gate')
                return self._result(request, steps, reasons, False, False)
            navigation_inputs = {
                **request,
                'approved_path_sha256': preview['route']['path_sha256'],
                'approved_semantic_map_sha256': preview[
                    'keepout'
                ]['source_content_sha256'],
            }
            navigation = self.navigation.invoke(
                navigation_inputs,
                float(timeout_sec),
            )
            motion_sent = navigation.get('motion_command_sent') is True
            reached = navigation.get('goal_reached') is True
            self._step(
                steps,
                'navigate_to_approved_pose',
                'pass' if reached else 'fail',
                navigation,
            )
            if not reached:
                reasons.append('approved navigation did not reach the goal')
            return self._result(
                request,
                steps,
                reasons,
                reached,
                motion_sent,
            )
        except RuntimeError as error:
            reasons.append(str(error))
            return self._result(
                request,
                steps,
                reasons,
                False,
                motion_sent,
                failed=True,
            )

    def _result(
        self, request, steps, reasons, reached, motion_sent, failed=False,
    ):
        state = 'succeeded' if reached else ('failed' if failed else 'aborted')
        return {
            'schema_version': 1,
            'skill': self.mode,
            'skill_version': '0.1.0',
            'state': state,
            'goal_reached': bool(reached),
            'motion_command_sent': bool(motion_sent),
            'request': request,
            'steps': steps,
            'reasons': reasons,
        }

    def validate_result(self, result):
        """Validate schema and success safety postconditions."""
        path = self.repository_root / RESULT_SCHEMA
        try:
            schema = json.loads(path.read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(result)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise CompositeWorkflowError(
                'composite result violates its JSON Schema'
            ) from error
        expected = list(range(1, len(result['steps']) + 1))
        if [item['step_id'] for item in result['steps']] != expected:
            raise CompositeWorkflowError('composite step ids are not ordered')
        if result['state'] == 'succeeded':
            if not result['goal_reached'] or result['reasons']:
                raise CompositeWorkflowError('success postcondition is invalid')
            if not result['steps'] or result['steps'][-1]['name'] != (
                'navigate_to_approved_pose'
            ):
                raise CompositeWorkflowError('success lacks navigation evidence')
        elif result['goal_reached'] or not result['reasons']:
            raise CompositeWorkflowError('blocked result lacks a reason')
