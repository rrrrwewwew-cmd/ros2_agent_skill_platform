"""Command-line validator for a robot Skill YAML manifest."""

import argparse
from pathlib import Path
import sys

import yaml

from .skill_contract import SkillContractError, validate_skill_manifest


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Validate a ROS 2 Agent Skill manifest.'
    )
    parser.add_argument('manifest', type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    """Validate one YAML manifest and return a process status."""
    args = parse_args(argv)
    path = args.manifest.expanduser().resolve()
    try:
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        validated = validate_skill_manifest(document)
    except (OSError, yaml.YAMLError, SkillContractError) as error:
        print(f'INVALID: {error}', file=sys.stderr)
        return 2
    print(
        f"VALID: {validated['name']}@{validated['version']} "
        f"safety={validated['safety_level']}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
