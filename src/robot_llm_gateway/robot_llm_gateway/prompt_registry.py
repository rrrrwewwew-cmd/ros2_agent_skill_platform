"""Immutable filesystem Prompt Registry with exact version and hash pins."""

from dataclasses import dataclass
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from robot_llm_gateway.contracts import (
    ContractError,
    load_json,
    load_schema,
    sha256_json,
    validate_instance,
)


class PromptRegistryError(ContractError):
    """Report a missing, malformed, or hash-mismatched prompt."""


@dataclass(frozen=True)
class PromptRecord:
    """Hold one validated immutable prompt definition."""

    definition: dict
    sha256: str
    path: Path


class PromptRegistry:
    """Resolve prompts by exact identifier, version, and canonical hash."""

    def __init__(self, root, schema_dir):
        """Create a registry over trusted prompt and schema directories."""
        self.root = Path(root).resolve()
        self.schema_dir = Path(schema_dir).resolve()
        self.definition_schema = load_schema(
            self.schema_dir,
            'prompt_definition.schema.json',
        )

    def resolve(self, prompt_id, version, expected_sha256=None):
        """Resolve and validate one prompt, optionally enforcing its hash."""
        if re.fullmatch(r'[a-z][a-z0-9_]{2,63}', prompt_id) is None:
            raise PromptRegistryError('prompt path escapes registry')
        version_pattern = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
        if re.fullmatch(version_pattern, version) is None:
            raise PromptRegistryError('prompt path escapes registry')
        path = self.root / prompt_id / f'{version}.json'
        if not path.is_file():
            raise PromptRegistryError(
                f'prompt not found: {prompt_id}@{version}'
            )
        definition = load_json(path)
        validate_instance(
            definition,
            self.definition_schema,
            'prompt definition',
        )
        self._validate_skill_catalog(definition)
        if definition['prompt_id'] != prompt_id:
            raise PromptRegistryError('prompt id does not match its path')
        if definition['version'] != version:
            raise PromptRegistryError('prompt version does not match its path')
        digest = sha256_json(definition)
        if expected_sha256 is not None and digest != expected_sha256:
            raise PromptRegistryError('prompt hash does not match request pin')
        return PromptRecord(definition=definition, sha256=digest, path=path)

    @staticmethod
    def _validate_skill_catalog(definition):
        """Reject duplicate Skills and malformed embedded input contracts."""
        names = [item['name'] for item in definition['allowed_skills']]
        if len(names) != len(set(names)):
            raise PromptRegistryError('prompt Skill names must be unique')
        for item in definition['allowed_skills']:
            if 'input_schema' not in item:
                continue
            try:
                Draft202012Validator.check_schema(item['input_schema'])
            except SchemaError as exc:
                raise PromptRegistryError(
                    f"invalid input schema for Skill {item['name']}"
                ) from exc
            properties = set(item['input_schema']['properties'])
            required = set(item['input_schema']['required'])
            if not required.issubset(properties):
                raise PromptRegistryError(
                    f"Skill {item['name']} requires an undefined input"
                )
