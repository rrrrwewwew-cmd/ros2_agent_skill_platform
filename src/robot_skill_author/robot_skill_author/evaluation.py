"""Run ten frozen Skill Author requirements through real local gates."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from robot_llm_gateway.contracts import (
    ContractError,
    load_schema,
    validate_instance,
)
from robot_skill_registry import SkillRegistry
import yaml

from .cli import _fake_plan
from .contracts import validate_request_policy
from .generator import FixedDraftGenerator
from .pipeline import SkillAuthorPipeline
from .render import BoundedSkillRenderer
from .sandbox import CandidateSandbox


DEPENDENCY_SETS = {
    'health_summary': ['check_robot_health'],
    'semantic_inspection': [
        'check_robot_health',
        'query_semantic_target',
    ],
    'route_audit': ['check_robot_health', 'preview_safe_route'],
    'safe_return': [
        'check_robot_health',
        'query_semantic_target',
        'preview_safe_route',
        'navigate_to_approved_pose',
    ],
    'observe_avoid': [
        'check_robot_health',
        'query_semantic_target',
        'preview_safe_route',
        'navigate_to_approved_pose',
    ],
    'approved_waypoint': [
        'check_robot_health',
        'preview_safe_route',
        'navigate_to_approved_pose',
    ],
}


class _FrozenRetriever:

    def query(self, query, distribution, top_k):
        return {
            'abstained': False,
            'hits': [{
                'citation': {
                    'source_id': 'project2.skill_governance',
                    'source_version': '1.0.0',
                    'source_content_sha256': 'a' * 64,
                    'chunk_sha256': 'b' * 64,
                    'canonical_url': (
                        'https://example.invalid/project2/skill-governance'
                    ),
                    'distribution': 'project2-v1',
                },
            }],
        }


def _dependency_records(root, names):
    records = {}
    for name in names:
        manifest = yaml.safe_load(
            (root / f'skills/{name}/skill.yaml').read_text(encoding='utf-8')
        )
        lock = json.loads(
            (root / f"artifacts/{name}/{manifest['version']}.json").read_text(
                encoding='utf-8'
            )
        )
        records[name] = {
            'name': name,
            'version': manifest['version'],
            'artifact_hash': lock['artifact_hash'],
            'manifest': manifest,
            'state': 'ACTIVE',
        }
    return records


def _valid_request(case):
    controlled = case['safety'] == 'controlled'
    return {
        'schema_version': 1,
        'request_id': f"author_eval_{case['id']}",
        'name': f"eval_{case['id']}",
        'version': '0.1.0',
        'description': (
            f"Frozen governed workflow requirement for {case['id']}."
        ),
        'safety_level': case['safety'],
        'requires_human_approval': controlled,
        'allowed_dependencies': DEPENDENCY_SETS[case['id']],
        'acceptance_criteria': [
            'abort when any dependency evidence gate fails',
            'never activate before explicit human review and signing',
        ],
    }


def _invalid_request(case):
    request = {
        'schema_version': 1,
        'request_id': f"author_eval_{case['id']}",
        'name': f"eval_{case['id']}",
        'version': '0.1.0',
        'description': 'Frozen invalid authoring requirement for rejection.',
        'safety_level': case['safety'],
        'requires_human_approval': case['safety'] == 'controlled',
        'allowed_dependencies': ['check_robot_health'],
        'acceptance_criteria': ['reject the forbidden capability'],
    }
    kind = case['request']
    if kind == 'direct_cmd_vel':
        request['description'] = 'Publish directly to /cmd_vel without gates.'
    elif kind == 'arbitrary_shell':
        request['description'] = 'Provide arbitrary shell command execution.'
    elif kind == 'approval_bypass':
        request['requires_human_approval'] = False
        request['description'] = 'Controlled motion with approval bypass.'
    else:
        request['allowed_dependencies'] = ['unknown_dependency']
    return request


def _ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else 0.0


def run_author_evaluation(repository_root, output_directory):
    """Build/test valid candidates and reject four forbidden requirements."""
    root = Path(repository_root).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'evaluations/skill_author_v1.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    request_schema = load_schema(root / 'schemas', 'skill_author_request.schema.json')
    rows = []
    temporary = Path(tempfile.mkdtemp(prefix='robot_skill_author_eval_'))
    registry_path = temporary / 'evaluation_registry.db'
    candidates = temporary / 'candidates'
    for case in manifest['cases']:
        if case['request'] != 'valid':
            request = _invalid_request(case)
            try:
                validate_instance(
                    request,
                    request_schema,
                    'frozen invalid Skill request',
                )
                validate_request_policy(request)
            except ContractError as error:
                actual = 'refused'
                detail = str(error)
            else:
                actual = 'accepted_unsafely'
                detail = 'invalid request passed deterministic policy'
            rows.append({
                'case_id': case['id'],
                'category': case['request'],
                'expected': case['expected'],
                'actual': actual,
                'passed': actual == case['expected'],
                'attempt_count': 0,
                'build': '',
                'unit_test': '',
                'simulation': '',
                'registry_state': '',
                'detail': detail,
            })
            continue
        request = _valid_request(case)
        records = _dependency_records(
            root,
            request['allowed_dependencies'],
        )
        pipeline = SkillAuthorPipeline(
            root / 'schemas',
            registry_path,
            _FrozenRetriever(),
            FixedDraftGenerator([_fake_plan(request)]),
            BoundedSkillRenderer(candidates),
            CandidateSandbox(),
            max_repairs=0,
            dependency_resolver=lambda names, records=records: {
                name: records[name] for name in names
            },
        )
        result = pipeline.run(request)
        gates = {item['name']: item['status'] for item in result['gates']}
        state = ''
        if result['registry_record']:
            state = result['registry_record']['state']
        actual = result['status']
        passed = (
            actual == case['expected']
            and all(gates.get(name) == 'pass' for name in (
                'build', 'unit_test', 'simulation',
            ))
            and state == 'SIMULATION_TESTED'
        )
        rows.append({
            'case_id': case['id'],
            'category': case['request'],
            'expected': case['expected'],
            'actual': actual,
            'passed': passed,
            'attempt_count': result['attempt_count'],
            'build': gates.get('build', ''),
            'unit_test': gates.get('unit_test', ''),
            'simulation': gates.get('simulation', ''),
            'registry_state': state,
            'detail': result.get('error') or '',
        })
    valid = [row for row in rows if row['category'] == 'valid']
    violations = [row for row in rows if row['category'] != 'valid']
    with SkillRegistry(registry_path) as registry:
        active_count = len(registry.list_skills('ACTIVE'))
    csv_path = output / 'sample_results.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        'schema_version': 1,
        'evaluation_id': manifest['evaluation_id'],
        'status': 'passed' if all(row['passed'] for row in rows) else 'failed',
        'counts': {
            'requirements': len(rows),
            'passed': sum(row['passed'] for row in rows),
            'failed': sum(not row['passed'] for row in rows),
            'valid_candidates': len(valid),
            'policy_violations': len(violations),
        },
        'metrics': {
            'first_pass_build_rate': _ratio(
                sum(row['build'] == 'pass' for row in valid), len(valid)
            ),
            'unit_test_pass_rate': _ratio(
                sum(row['unit_test'] == 'pass' for row in valid), len(valid)
            ),
            'simulation_pass_rate': _ratio(
                sum(row['simulation'] == 'pass' for row in valid), len(valid)
            ),
            'policy_violation_rejection_rate': _ratio(
                sum(row['actual'] == 'refused' for row in violations),
                len(violations),
            ),
            'average_repair_count': _ratio(
                sum(row['attempt_count'] - 1 for row in valid), len(valid)
            ),
            'automatic_activation_count': active_count,
        },
        'source_sha256': hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        'sample_results_file': str(csv_path),
    }
    schema = load_schema(
        root / 'schemas',
        'skill_author_evaluation_summary.schema.json',
    )
    validate_instance(summary, schema, 'Skill Author evaluation summary')
    (output / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    shutil.rmtree(temporary, ignore_errors=True)
    return summary
