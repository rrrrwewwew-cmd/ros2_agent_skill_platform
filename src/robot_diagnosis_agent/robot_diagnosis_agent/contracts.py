"""Trusted MCP tool catalog and cross-step diagnosis plan contracts."""

from robot_llm_gateway.contracts import ContractError, sha256_json


TOOL_VERSION = '0.1.0'
TOOL_ORDER = (
    'list_experiment_runs',
    'inspect_experiment_run',
    'analyze_experiment_run',
    'retrieve_robotics_knowledge',
    'materialize_diagnosis_report',
)
RUN_ID_SCHEMA = {
    'type': 'string',
    'pattern': '^[a-z0-9][a-z0-9_-]{2,63}$',
}
DISTRIBUTION_SCHEMA = {
    'enum': ['jazzy', 'project1-v1', 'project2-v1'],
}


def _object_schema(properties, required):
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': properties,
        'required': required,
    }


def _spec(name, safety_class, input_schema):
    contract = {
        'name': name,
        'version': TOOL_VERSION,
        'safety_class': safety_class,
        'input_schema': input_schema,
    }
    return {
        **contract,
        'contract_sha256': sha256_json(contract),
    }


def governed_tool_catalog():
    """Return the immutable local contract for the five diagnosis tools."""
    query_schema = {
        'type': 'string',
        'minLength': 3,
        'maxLength': 300,
    }
    knowledge_query = _object_schema(
        {
            'query': query_schema,
            'distribution': DISTRIBUTION_SCHEMA,
        },
        ['query', 'distribution'],
    )
    specifications = (
        _spec(
            'list_experiment_runs',
            'read_only',
            _object_schema({}, []),
        ),
        _spec(
            'inspect_experiment_run',
            'read_only',
            _object_schema({'run_id': RUN_ID_SCHEMA}, ['run_id']),
        ),
        _spec(
            'analyze_experiment_run',
            'read_only',
            _object_schema({'run_id': RUN_ID_SCHEMA}, ['run_id']),
        ),
        _spec(
            'retrieve_robotics_knowledge',
            'read_only',
            _object_schema(
                {
                    'query': query_schema,
                    'distribution': DISTRIBUTION_SCHEMA,
                    'top_k': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 3,
                    },
                },
                ['query', 'distribution', 'top_k'],
            ),
        ),
        _spec(
            'materialize_diagnosis_report',
            'artifact_write',
            _object_schema(
                {
                    'run_id': RUN_ID_SCHEMA,
                    'knowledge_queries': {
                        'type': 'array',
                        'minItems': 1,
                        'maxItems': 3,
                        'items': knowledge_query,
                    },
                },
                ['run_id', 'knowledge_queries'],
            ),
        ),
    )
    return {item['name']: item for item in specifications}


def validate_prompt_catalog(prompt):
    """Require the Prompt catalog to equal the code-owned MCP catalog."""
    expected = governed_tool_catalog()
    actual_items = prompt.definition.get('allowed_tools')
    if actual_items is None:
        raise ContractError('diagnosis Prompt has no allowed_tools catalog')
    actual = {item['name']: item for item in actual_items}
    if tuple(actual) != TOOL_ORDER:
        raise ContractError('diagnosis Prompt tool order is not pinned')
    for name, trusted in expected.items():
        item = actual[name]
        if item['version'] != trusted['version']:
            raise ContractError(f'{name} version differs from trusted catalog')
        if item['contract_sha256'] != trusted['contract_sha256']:
            raise ContractError(f'{name} contract hash differs from code')
        if item['permission'] != trusted['safety_class']:
            raise ContractError(f'{name} safety class differs from code')
        if item['input_schema'] != trusted['input_schema']:
            raise ContractError(f'{name} input schema differs from code')


def validate_cross_step_plan(plan, trusted_run_id):
    """Enforce exact evidence order and immutable cross-step identities."""
    if plan['decision'] != 'plan':
        raise ContractError('only decision=plan has diagnosis steps')
    if plan['run_id'] != trusted_run_id:
        raise ContractError('plan run_id differs from trusted context')
    if tuple(step['tool_name'] for step in plan['steps']) != TOOL_ORDER:
        raise ContractError('diagnosis tools are not in the required order')
    for step in plan['steps']:
        if step['tool_name'] in {
            'inspect_experiment_run',
            'analyze_experiment_run',
            'materialize_diagnosis_report',
        } and step['inputs']['run_id'] != trusted_run_id:
            raise ContractError('tool run_id differs from trusted context')
    retrieval = plan['steps'][3]['inputs']
    report_queries = plan['steps'][4]['inputs']['knowledge_queries']
    expected_query = {
        'query': retrieval['query'],
        'distribution': retrieval['distribution'],
    }
    if report_queries != [expected_query]:
        raise ContractError(
            'report knowledge query must exactly repeat retrieval input'
        )
