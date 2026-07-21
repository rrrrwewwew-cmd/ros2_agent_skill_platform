"""Contracts for bounded LLM-assisted Skill generation."""

import ast
import hashlib
import json
from pathlib import Path

from robot_llm_gateway.contracts import ContractError, validate_instance


RENDERER_VERSION = '0.1.0'
RENDERER_HASH = (
    '9d47d8188c1ce718673eb0a22edda8510e33084948e7183fa19f27faaf6b701b'
)
DEPENDENCIES = {
    'check_robot_health',
    'query_semantic_target',
    'preview_safe_route',
    'navigate_to_approved_pose',
}
FORBIDDEN_TEXT = (
    '/cmd_vel',
    '/cmd_vel_unstamped',
    'subprocess',
    'os.system',
    'eval(',
    'exec(',
    '__import__',
    'socket',
)
FORBIDDEN_REQUEST_TEXT = (
    '/cmd_vel',
    '/cmd_vel_unstamped',
    'arbitrary shell',
    'os.system',
    'bypass approval',
    'approval bypass',
    'without approval',
    'ignore approval',
)


def sha256_file(path):
    """Return one file SHA-256 digest."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_request_policy(request):
    """Reject capabilities that deterministic templates must never expose."""
    text = ' '.join([
        request['description'],
        *request['acceptance_criteria'],
    ]).casefold()
    for token in FORBIDDEN_REQUEST_TEXT:
        if token.casefold() in text:
            raise ContractError(
                f'Skill author request contains forbidden capability: {token}'
            )


def validate_author_plan(plan, request, plan_schema):
    """Bind the model draft to the trusted author request."""
    validate_instance(plan, plan_schema, 'Skill author plan')
    if plan['decision'] != 'plan':
        return None
    step = plan['steps'][0]
    if step['artifact_hash'] != RENDERER_HASH:
        raise ContractError('Skill renderer hash changed')
    draft = step['inputs']
    exact_fields = (
        'name',
        'version',
        'description',
        'safety_level',
        'requires_human_approval',
    )
    for field in exact_fields:
        if draft[field] != request[field]:
            raise ContractError(f'generated {field} differs from request')
    names = [item['skill_name'] for item in draft['dependency_steps']]
    if any(name not in request['allowed_dependencies'] for name in names):
        raise ContractError('draft references a dependency outside request')
    if len(names) != len(set(names)):
        raise ContractError('draft dependency Skills must be unique')
    scenario_names = [item['name'] for item in draft['test_scenarios']]
    if len(scenario_names) != len(set(scenario_names)):
        raise ContractError('acceptance scenario names must be unique')
    expected_ids = list(range(1, len(names) + 1))
    if [item['step_id'] for item in draft['dependency_steps']] != expected_ids:
        raise ContractError('draft dependency step ids must be consecutive')
    if draft['safety_level'] == 'controlled':
        if 'navigate_to_approved_pose' not in names:
            raise ContractError('controlled workflow requires approved navigation')
        if names[-1] != 'navigate_to_approved_pose':
            raise ContractError('approved navigation must be the final step')
        if not draft['requires_human_approval']:
            raise ContractError('controlled workflow must require approval')
    if 'preview_safe_route' in names and 'check_robot_health' in names:
        if names.index('check_robot_health') > names.index('preview_safe_route'):
            raise ContractError('health evidence must precede route preview')
    if 'navigate_to_approved_pose' in names:
        if 'preview_safe_route' not in names:
            raise ContractError('navigation requires an approved route preview')
        if names.index('preview_safe_route') > names.index(
            'navigate_to_approved_pose'
        ):
            raise ContractError('route preview must precede navigation')
    return draft


def static_scan(candidate_root, expected_files):
    """Reject path escape, symlinks, forbidden APIs, and dynamic imports."""
    root = Path(candidate_root).resolve()
    actual = sorted(
        str(path.relative_to(root))
        for path in root.rglob('*')
        if path.is_file()
    )
    if sorted(expected_files) != actual:
        raise ContractError('candidate file set differs from renderer manifest')
    for relative in actual:
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ContractError('candidate contains a symlink or path escape')
        if path.stat().st_size > 256_000:
            raise ContractError('candidate file exceeds bounded size')
        if path.suffix not in {'.py', '.xml', '.cfg', '.md', '.yaml'}:
            continue
        text = path.read_text(encoding='utf-8')
        lowered = text.lower()
        forbidden_tokens = (
            FORBIDDEN_TEXT if path.suffix == '.py' else ('/cmd_vel',)
        )
        for forbidden in forbidden_tokens:
            if forbidden.lower() in lowered:
                raise ContractError(
                    f'candidate contains forbidden token: {forbidden}'
                )
        if path.suffix == '.py':
            tree = ast.parse(text, filename=relative)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [item.name for item in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or '']
                    )
                    allowed = {'copy', 'setuptools', 'pytest'}
                    if any(
                        name.split('.')[0] not in allowed
                        and not name.split('.')[0].startswith('generated_')
                        for name in names
                    ):
                        raise ContractError(
                            f'candidate imports unapproved module in {relative}'
                        )
    return {
        'file_count': len(actual),
        'source_snapshot_sha256': hashlib.sha256(
            json.dumps(
                {name: sha256_file(root / name) for name in actual},
                separators=(',', ':'),
                sort_keys=True,
            ).encode('utf-8')
        ).hexdigest(),
    }
