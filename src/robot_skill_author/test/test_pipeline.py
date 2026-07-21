"""Tests for the governed Skill Author pipeline."""

import hashlib
from pathlib import Path

from robot_skill_author.cli import _fake_plan
from robot_skill_author.contracts import static_scan
from robot_skill_author.generator import FixedDraftGenerator
from robot_skill_author.pipeline import SkillAuthorPipeline
from robot_skill_author.render import BoundedSkillRenderer
from robot_skill_registry import SkillRegistry
import yaml


ROOT = Path(__file__).resolve().parents[3]


def _request(identifier='author_test_001'):
    return {
        'schema_version': 1,
        'request_id': identifier,
        'name': f'generated_health_route_{identifier[-3:]}',
        'version': '0.1.0',
        'description': (
            'Compose governed health evidence and a read-only safe route '
            'preview without moving the robot.'
        ),
        'safety_level': 'read_only',
        'requires_human_approval': False,
        'allowed_dependencies': [
            'check_robot_health',
            'preview_safe_route',
        ],
        'acceptance_criteria': [
            'health evidence precedes route planning',
            'unsafe evidence aborts the workflow',
        ],
    }


def _records(names):
    records = {}
    for name in names:
        manifest = yaml.safe_load(
            (ROOT / f'skills/{name}/skill.yaml').read_text(encoding='utf-8')
        )
        records[name] = {
            'name': name,
            'version': manifest['version'],
            'artifact_hash': hashlib.sha256(name.encode()).hexdigest(),
            'manifest': manifest,
            'state': 'ACTIVE',
        }
    return records


class _Retriever:

    def query(self, query, distribution, top_k):
        return {
            'abstained': False,
            'hits': [{
                'citation': {
                    'source_id': 'project2.skill_governance',
                    'source_version': '1.0.0',
                    'source_content_sha256': 'a' * 64,
                    'chunk_sha256': 'b' * 64,
                    'canonical_url': 'https://example.invalid/governance',
                    'distribution': 'project2-v1',
                },
            }],
        }


class _Sandbox:

    def __init__(self, fail_first=False):
        self.calls = 0
        self.fail_first = fail_first

    def validate(self, candidate):
        self.calls += 1
        code = 1 if self.fail_first and self.calls == 1 else 0
        evidence = {
            'returncode': code,
            'duration_ms': 1.0,
            'output_tail': 'frozen test gate',
            'output_sha256': 'c' * 64,
        }
        if code:
            return {'build': evidence}
        return {
            'build': evidence,
            'unit_test': evidence,
            'simulation': evidence,
        }


def _pipeline(tmp_path, request, sandbox, max_repairs=0):
    return SkillAuthorPipeline(
        ROOT / 'schemas',
        tmp_path / 'registry.db',
        _Retriever(),
        FixedDraftGenerator([_fake_plan(request)]),
        BoundedSkillRenderer(tmp_path / 'candidates'),
        sandbox,
        max_repairs=max_repairs,
        dependency_resolver=lambda names: _records(names),
    )


def test_pipeline_stops_at_human_approval(tmp_path):
    request = _request()
    result = _pipeline(tmp_path, request, _Sandbox()).run(request)
    assert result['status'] == 'waiting_human_approval'
    assert [gate['status'] for gate in result['gates']] == ['pass'] * 5
    assert result['approval_required'] is True
    with SkillRegistry(tmp_path / 'registry.db') as registry:
        record = registry.get_skill(request['name'], '0.1.0')
    assert record['state'] == 'SIMULATION_TESTED'
    assert record['signature'] is None


def test_pipeline_repairs_once_then_passes(tmp_path):
    request = _request('author_test_002')
    result = _pipeline(
        tmp_path,
        request,
        _Sandbox(fail_first=True),
        max_repairs=1,
    ).run(request)
    assert result['status'] == 'waiting_human_approval'
    assert result['attempt_count'] == 2


def test_renderer_output_passes_static_scan(tmp_path):
    request = _request('author_test_003')
    draft = _fake_plan(request)['steps'][0]['inputs']
    candidate = BoundedSkillRenderer(tmp_path).render(
        request,
        draft,
        1,
        _records(request['allowed_dependencies']),
        [],
    )
    evidence = static_scan(candidate['root'], candidate['expected_files'])
    assert evidence['file_count'] == len(candidate['expected_files'])
    assert len(evidence['source_snapshot_sha256']) == 64
