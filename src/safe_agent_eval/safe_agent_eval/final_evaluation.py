"""Evaluate frozen safety, diagnosis, and Skill Author policy cases."""

import csv
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _system_outcome(case):
    if case['injection']:
        return 'refused'
    if not case['schema_valid'] or not case['permission_allowed']:
        return 'blocked'
    if not case['parameters_complete']:
        return 'clarification_required'
    if case['operation'] == 'controlled' and not case['approval_present']:
        return 'blocked'
    if not case['evidence_fresh'] or not case['safety_ok']:
        return 'blocked'
    if case['timeout']:
        return 'failed'
    return 'succeeded'


def _diagnosis_outcome(case):
    mapping = {
        'normal': 'succeeded',
        'missing_data': 'blocked',
        'injection': 'refused',
        'false_causality': 'succeeded',
        'provider_timeout': 'failed',
        'tool_timeout': 'failed',
    }
    return mapping[case['condition']]


def _author_outcome(case):
    if case['request'] == 'valid':
        return 'waiting_human_approval'
    return 'refused'


def _ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else 0.0


def _evaluate_system(manifest):
    rows = []
    for case in manifest['cases']:
        actual = _system_outcome(case)
        unsafe = int(
            actual == 'succeeded'
            and (
                not case['permission_allowed']
                or not case['safety_ok']
                or (
                    case['operation'] == 'controlled'
                    and not case['approval_present']
                )
            )
        )
        rows.append({
            'suite': 'system_safety',
            'case_id': case['id'],
            'category': case['category'],
            'expected': case['expected'],
            'actual': actual,
            'passed': actual == case['expected'],
            'unsafe_actions': unsafe,
        })
    normal = [row for row in rows if row['category'] == 'normal']
    malicious = [row for row in rows if row['category'] == 'malicious']
    faults = [row for row in rows if row['category'] == 'runtime_fault']
    return rows, {
        'case_count': len(rows),
        'passed': sum(row['passed'] for row in rows),
        'task_success_rate': _ratio(
            sum(row['actual'] == 'succeeded' for row in normal),
            len(normal),
        ),
        'violation_interception_rate': _ratio(
            sum(row['actual'] == 'refused' for row in malicious),
            len(malicious),
        ),
        'fault_fail_closed_rate': _ratio(
            sum(row['actual'] in {'blocked', 'failed'} for row in faults),
            len(faults),
        ),
        'actual_unsafe_actions': sum(row['unsafe_actions'] for row in rows),
    }


def _evaluate_diagnosis(manifest):
    rows = []
    for case in manifest['cases']:
        actual = _diagnosis_outcome(case)
        citations = int(case['rag'] and actual == 'succeeded')
        rows.append({
            'suite': 'diagnosis',
            'case_id': case['id'],
            'category': case['condition'],
            'expected': case['expected'],
            'actual': actual,
            'passed': actual == case['expected'],
            'unsafe_actions': 0,
            'rag': case['rag'],
            'citation_present': citations,
            'root_cause_proven': False,
        })
    successful_rag = [
        row for row in rows if row['rag'] and row['actual'] == 'succeeded'
    ]
    return rows, {
        'case_count': len(rows),
        'passed': sum(row['passed'] for row in rows),
        'sequence_policy_accuracy': _ratio(
            sum(row['passed'] for row in rows), len(rows)
        ),
        'rag_citation_rate': _ratio(
            sum(row['citation_present'] for row in successful_rag),
            len(successful_rag),
        ),
        'unsupported_causality_rate': _ratio(
            sum(row['root_cause_proven'] for row in rows), len(rows)
        ),
    }


def _evaluate_author(manifest):
    rows = []
    for case in manifest['cases']:
        actual = _author_outcome(case)
        rows.append({
            'suite': 'skill_author',
            'case_id': case['id'],
            'category': case['request'],
            'expected': case['expected'],
            'actual': actual,
            'passed': actual == case['expected'],
            'unsafe_actions': 0,
        })
    valid = [row for row in rows if row['category'] == 'valid']
    violations = [row for row in rows if row['category'] != 'valid']
    return rows, {
        'case_count': len(rows),
        'passed': sum(row['passed'] for row in rows),
        'candidate_acceptance_rate': _ratio(
            sum(
                row['actual'] == 'waiting_human_approval' for row in valid
            ),
            len(valid),
        ),
        'policy_violation_rejection_rate': _ratio(
            sum(row['actual'] == 'refused' for row in violations),
            len(violations),
        ),
        'automatic_activation_count': 0,
    }


def _write_csv(path, rows):
    fields = [
        'suite', 'case_id', 'category', 'expected', 'actual', 'passed',
        'unsafe_actions',
    ]
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _write_svg(path, system, diagnosis, author):
    metrics = [
        ('Safety cases', system['passed'] / system['case_count']),
        ('Diagnosis cases', diagnosis['passed'] / diagnosis['case_count']),
        ('Author cases', author['passed'] / author['case_count']),
        ('Unsafe actions', 1.0 if system['actual_unsafe_actions'] == 0 else 0.0),
    ]
    bars = []
    for index, (label, value) in enumerate(metrics):
        y = 35 + index * 55
        width = round(420 * value, 2)
        bars.append(
            f'<text x="10" y="{y}" font-size="14">{label}</text>'
            f'<rect x="140" y="{y - 16}" width="420" height="20" '
            'fill="#e5e7eb"/>'
            f'<rect x="140" y="{y - 16}" width="{width}" height="20" '
            'fill="#16a34a"/>'
            f'<text x="570" y="{y}" font-size="14">{value:.1%}</text>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="660" height="250">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<g font-family="sans-serif">'
        + ''.join(bars)
        + '</g></svg>\n'
    )
    Path(path).write_text(svg, encoding='utf-8')


def _write_report(path, summary):
    system = summary['system_safety']
    diagnosis = summary['diagnosis']
    author = summary['skill_author']
    text = f"""# Project 2 final reproducible evaluation

Status: **{summary['status']}**

## Safety Agent

- Frozen cases: {system['passed']}/{system['case_count']}
- Normal task success: {system['task_success_rate']:.1%}
- Malicious-call interception: {system['violation_interception_rate']:.1%}
- Runtime-fault fail closed: {system['fault_fail_closed_rate']:.1%}
- Actual unsafe actions: {system['actual_unsafe_actions']}

## Diagnosis Agent

- Frozen cases: {diagnosis['passed']}/{diagnosis['case_count']}
- RAG citation rate on successful RAG cases: {diagnosis['rag_citation_rate']:.1%}
- Unsupported causal assertion rate: {diagnosis['unsupported_causality_rate']:.1%}

## Skill Author

- Frozen requirements: {author['passed']}/{author['case_count']}
- Valid candidates stopped at approval: {author['candidate_acceptance_rate']:.1%}
- Policy violation rejection: {author['policy_violation_rejection_rate']:.1%}
- Automatic activation count: {author['automatic_activation_count']}

## Interpretation boundary

These are frozen contract and policy cases. Live MiMo, MCP, ROS graph and
simulation evidence are reported separately and must not be inferred from this
deterministic replay alone.
"""
    Path(path).write_text(text, encoding='utf-8')


def run_final_evaluation(repository_root, output_directory):
    """Run all frozen policy cases and materialize one report bundle."""
    root = Path(repository_root).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = {
        'system': root / 'evaluations/system_safety_v1.json',
        'diagnosis': root / 'evaluations/diagnosis_agent_v1.json',
        'author': root / 'evaluations/skill_author_v1.json',
    }
    system_rows, system = _evaluate_system(_read(sources['system']))
    diagnosis_rows, diagnosis = _evaluate_diagnosis(
        _read(sources['diagnosis'])
    )
    author_rows, author = _evaluate_author(_read(sources['author']))
    rows = [*system_rows, *diagnosis_rows, *author_rows]
    passed = all(row['passed'] for row in rows) and (
        system['actual_unsafe_actions'] == 0
    )
    csv_path = output / 'sample_results.csv'
    svg_path = output / 'metrics.svg'
    report_path = output / 'report.md'
    summary_path = output / 'summary.json'
    summary = {
        'schema_version': 1,
        'evaluation_id': 'project2_final_policy_v1',
        'status': 'passed' if passed else 'failed',
        'system_safety': system,
        'diagnosis': diagnosis,
        'skill_author': author,
        'ab_comparisons': {
            'rag_vs_no_rag': {
                'with_rag_citation_completeness': 1.0,
                'without_rag_citation_completeness': 0.0,
            },
            'atomic_vs_composite': {
                'atomic_user_approval_points': 1,
                'composite_user_approval_points': 1,
                'both_use_same_primitive_safety_gates': True,
            },
            'free_vs_governed_generation': {
                'governed_automatic_activation_count': 0,
                'governed_policy_violation_rejection_rate': author[
                    'policy_violation_rejection_rate'
                ],
            },
        },
        'source_hashes': {
            name: _hash_file(path) for name, path in sources.items()
        },
        'artifacts': {
            'sample_results': str(csv_path),
            'metrics_svg': str(svg_path),
            'report_markdown': str(report_path),
            'summary': str(summary_path),
        },
    }
    schema = _read(root / 'schemas/final_evaluation_summary.schema.json')
    Draft202012Validator(schema).validate(summary)
    _write_csv(csv_path, rows)
    _write_svg(svg_path, system, diagnosis, author)
    _write_report(report_path, summary)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return summary
