"""Validate the safety-critical subset of a robot Skill manifest."""

import re


NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
VERSION_PATTERN = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
SAFETY_LEVELS = {'read_only', 'controlled', 'high', 'emergency'}
PERMISSION_KEYS = {'topics_read', 'topics_write', 'services', 'actions'}
FORBIDDEN_TOPIC_WRITES = {'/cmd_vel', '/cmd_vel_unstamped'}
REQUIRED_FIELDS = {
    'schema_version',
    'name',
    'version',
    'description',
    'safety_level',
    'requires_human_approval',
    'timeout_sec',
    'cancel_supported',
    'inputs',
    'preconditions',
    'effects',
    'ros_permissions',
}


class SkillContractError(ValueError):
    """Raised when a Skill manifest violates the frozen contract."""


def _string_list(value, field):
    if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value):
        raise SkillContractError(f'{field} must be a list of strings')
    if len(value) != len(set(value)):
        raise SkillContractError(f'{field} must not contain duplicates')


def validate_skill_manifest(manifest):
    """Return a normalized manifest or raise ``SkillContractError``."""
    if not isinstance(manifest, dict):
        raise SkillContractError('manifest must be a mapping')
    missing = sorted(REQUIRED_FIELDS - manifest.keys())
    if missing:
        raise SkillContractError(f'missing required fields: {missing}')
    if manifest['schema_version'] != 1:
        raise SkillContractError('schema_version must equal 1')
    if not NAME_PATTERN.fullmatch(str(manifest['name'])):
        raise SkillContractError('name must be lower snake_case')
    if not VERSION_PATTERN.fullmatch(str(manifest['version'])):
        raise SkillContractError('version must be semantic x.y.z')
    if not isinstance(manifest['description'], str) or len(
            manifest['description'].strip()) < 10:
        raise SkillContractError('description must contain at least 10 chars')
    safety_level = manifest['safety_level']
    if safety_level not in SAFETY_LEVELS:
        raise SkillContractError(f'unsupported safety_level: {safety_level}')
    approval = manifest['requires_human_approval']
    if not isinstance(approval, bool):
        raise SkillContractError('requires_human_approval must be boolean')
    if safety_level in {'controlled', 'high'} and not approval:
        raise SkillContractError(
            'controlled and high safety Skills require human approval'
        )
    timeout = manifest['timeout_sec']
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise SkillContractError('timeout_sec must be numeric')
    if not 0 < float(timeout) <= 600:
        raise SkillContractError('timeout_sec must be in (0, 600]')
    if not isinstance(manifest['cancel_supported'], bool):
        raise SkillContractError('cancel_supported must be boolean')
    if not isinstance(manifest['inputs'], dict):
        raise SkillContractError('inputs must be a mapping')
    _string_list(manifest['preconditions'], 'preconditions')
    _string_list(manifest['effects'], 'effects')

    permissions = manifest['ros_permissions']
    if not isinstance(permissions, dict):
        raise SkillContractError('ros_permissions must be a mapping')
    if set(permissions) != PERMISSION_KEYS:
        raise SkillContractError(
            f'ros_permissions must contain exactly {sorted(PERMISSION_KEYS)}'
        )
    for key in sorted(PERMISSION_KEYS):
        _string_list(permissions[key], f'ros_permissions.{key}')
        for name in permissions[key]:
            if not name.startswith('/'):
                raise SkillContractError(
                    f'ros_permissions.{key} entries must be absolute ROS names'
                )
    forbidden = FORBIDDEN_TOPIC_WRITES.intersection(
        permissions['topics_write']
    )
    if forbidden:
        raise SkillContractError(
            f'direct velocity topics are forbidden: {sorted(forbidden)}'
        )
    if safety_level == 'read_only' and permissions['topics_write']:
        raise SkillContractError('read_only Skills cannot write ROS topics')
    return dict(manifest)
