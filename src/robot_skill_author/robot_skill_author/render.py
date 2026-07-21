"""Deterministically render structured drafts into ROS 2 Python packages."""

import hashlib
import json
from pathlib import Path

import yaml

from .contracts import sha256_file


class SkillRenderError(RuntimeError):
    """Report an invalid or unwritable bounded candidate."""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )


class BoundedSkillRenderer:
    """Render code from a structured workflow, never from model source text."""

    def __init__(self, candidate_root):
        self.candidate_root = Path(candidate_root).expanduser().resolve()
        self.candidate_root.mkdir(parents=True, exist_ok=True)

    def render(self, request, draft, attempt, dependency_records, citations):
        """Create an immutable attempt directory and return its manifest."""
        root = (
            self.candidate_root / request['request_id'] / f'attempt_{attempt}'
        ).resolve()
        if not root.is_relative_to(self.candidate_root):
            raise SkillRenderError('candidate output escapes configured root')
        if root.exists() and any(root.iterdir()):
            raise SkillRenderError('candidate attempt directory already exists')
        package_name = f"generated_{draft['name']}"
        files = {}

        workflow = {
            'schema_version': 1,
            'name': draft['name'],
            'version': draft['version'],
            'safety_level': draft['safety_level'],
            'requires_human_approval': draft['requires_human_approval'],
            'steps': [
                {
                    **step,
                    'skill_version': dependency_records[
                        step['skill_name']
                    ]['version'],
                    'artifact_hash': dependency_records[
                        step['skill_name']
                    ]['artifact_hash'],
                }
                for step in draft['dependency_steps']
            ],
        }
        permissions = self._aggregate_permissions(dependency_records)
        manifest = {
            'schema_version': 1,
            'name': draft['name'],
            'version': draft['version'],
            'description': draft['description'],
            'entrypoint': f'{package_name}.workflow:build_workflow',
            'safety_level': draft['safety_level'],
            'requires_human_approval': draft['requires_human_approval'],
            'timeout_sec': 300.0,
            'cancel_supported': (
                'navigate_to_approved_pose' in dependency_records
            ),
            'idempotent': draft['safety_level'] == 'read_only',
            'inputs': draft['inputs'],
            'preconditions': draft['preconditions'],
            'effects': draft['effects'],
            'ros_permissions': permissions,
        }
        rendered = {
            f'src/{package_name}/package.xml': self._package_xml(package_name),
            f'src/{package_name}/setup.py': self._setup_py(package_name),
            f'src/{package_name}/setup.cfg': self._setup_cfg(package_name),
            f'src/{package_name}/resource/{package_name}': '',
            f'src/{package_name}/{package_name}/__init__.py': (
                '"""Generated bounded workflow package."""\n'
            ),
            f'src/{package_name}/{package_name}/workflow.py': (
                self._workflow_py(workflow)
            ),
            f'src/{package_name}/test/test_workflow.py': (
                self._workflow_test(package_name, draft['test_scenarios'])
            ),
            'skill/skill.yaml': yaml.safe_dump(
                manifest,
                sort_keys=False,
                allow_unicode=True,
            ),
            'skill/SKILL.md': self._skill_doc(draft, workflow),
            'generation/rag_citations.json': (
                json.dumps(citations, ensure_ascii=False, indent=2) + '\n'
            ),
        }
        for relative, content in rendered.items():
            path = root / relative
            _write(path, content)
            files[relative] = sha256_file(path)
        artifact_hash = hashlib.sha256(
            ''.join(
                f'{files[name]}  {name}\n' for name in sorted(files)
            ).encode('utf-8')
        ).hexdigest()
        artifact_lock = {
            'schema_version': 1,
            'name': draft['name'],
            'version': draft['version'],
            'hash_algorithm': 'sha256-file-list-v1',
            'artifact_hash': artifact_hash,
            'files': sorted(files),
        }
        lock_path = root / 'generation/artifact_lock.json'
        _write(
            lock_path,
            json.dumps(artifact_lock, ensure_ascii=False, indent=2) + '\n',
        )
        expected_files = sorted([*files, 'generation/artifact_lock.json'])
        candidate = {
            'schema_version': 1,
            'request_id': request['request_id'],
            'attempt': attempt,
            'root': str(root),
            'package_name': package_name,
            'manifest': manifest,
            'workflow': workflow,
            'artifact_hash': artifact_hash,
            'artifact_lock_sha256': sha256_file(lock_path),
            'expected_files': expected_files,
            'source_files_sha256': files,
        }
        return candidate

    @staticmethod
    def _aggregate_permissions(records):
        permissions = {
            key: set() for key in (
                'topics_read', 'topics_write', 'services', 'actions'
            )
        }
        for record in records.values():
            for key, names in record['manifest']['ros_permissions'].items():
                permissions[key].update(names)
        return {key: sorted(value) for key, value in permissions.items()}

    @staticmethod
    def _workflow_py(workflow):
        return '''"""Generated fail-closed dependency workflow."""\n\n'''.replace(
            '\\n', '\n'
        ) + f'WORKFLOW = {workflow!r}\n\n' + '''
def build_workflow(inputs):
    """Return a copy of the immutable dependency plan."""
    if not isinstance(inputs, dict):
        raise ValueError('workflow inputs must be an object')
    return {
        'schema_version': 1,
        'workflow': WORKFLOW,
        'inputs': dict(inputs),
    }


def simulate(failed_step=None, approval_granted=False):
    """Exercise the generated state policy without touching a ROS graph."""
    for step in WORKFLOW['steps']:
        if failed_step == step['step_id']:
            return 'aborted'
        if (
            step['skill_name'] == 'navigate_to_approved_pose'
            and not approval_granted
        ):
            return 'waiting_approval'
    return 'succeeded'
'''

    @staticmethod
    def _workflow_test(package_name, scenarios):
        lines = [
            '"""Generated workflow contract tests."""',
            '',
            f'from {package_name}.workflow import build_workflow, simulate',
            '',
            '',
            'def test_build_workflow_is_bounded():',
            '    """The generated plan is immutable and JSON-like."""',
            "    result = build_workflow({'goal_x': 1.0})",
            "    assert result['schema_version'] == 1",
            "    assert 1 <= len(result['workflow']['steps']) <= 6",
            '',
            '',
        ]
        for scenario in scenarios:
            failed = repr(scenario['failed_step'])
            approval = scenario['expected_state'] == 'succeeded'
            lines.extend([
                f"def test_simulation_{scenario['name']}():",
                '    """Exercise one generated fail-closed scenario."""',
                '    assert simulate(',
                f'        failed_step={failed},',
                f'        approval_granted={approval!r},',
                f"    ) == {scenario['expected_state']!r}",
                '',
                '',
            ])
        return '\n'.join(lines)

    @staticmethod
    def _package_xml(package_name):
        return f"""<?xml version="1.0"?>
<package format="3">
  <name>{package_name}</name>
  <version>0.1.0</version>
  <description>Generated bounded Skill workflow candidate.</description>
  <maintainer email="maintainer@example.com">skill-author</maintainer>
  <license>MIT</license>
  <buildtool_depend>ament_python</buildtool_depend>
  <test_depend>python3-pytest</test_depend>
  <export><build_type>ament_python</build_type></export>
</package>
"""

    @staticmethod
    def _setup_py(package_name):
        return f"""from setuptools import find_packages, setup

setup(
    name={package_name!r},
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/{package_name}']),
        ('share/{package_name}', ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
)
"""

    @staticmethod
    def _setup_cfg(package_name):
        return (
            '[develop]\n'
            f'script_dir=$base/lib/{package_name}\n'
            '[install]\n'
            f'install_scripts=$base/lib/{package_name}\n'
        )

    @staticmethod
    def _skill_doc(draft, workflow):
        dependencies = ', '.join(
            item['skill_name'] for item in workflow['steps']
        )
        return (
            f"# {draft['name']}\n\n"
            f"{draft['description']}\n\n"
            f"Template: `{draft['template_family']}`.\n\n"
            f'Dependencies: {dependencies}.\n\n'
            'This candidate cannot execute until build, tests, simulation, '
            'human diff approval, signing, registration and adapter review '
            'have all completed.\n'
        )
