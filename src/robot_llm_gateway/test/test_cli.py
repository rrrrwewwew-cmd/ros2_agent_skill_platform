"""Offline CLI smoke test for the plan-only gateway."""

import json
from pathlib import Path

from robot_llm_gateway.cli import main


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_fake_cli_smoke_needs_no_api_key(capsys):
    """The deterministic CLI validates packaging without a network."""
    return_code = main([
        '--provider', 'fake',
        '--task', '检查机器人是否健康',
        '--share-dir', str(REPOSITORY_ROOT),
    ])
    output = json.loads(capsys.readouterr().out)
    assert return_code == 0
    assert output['state'] == 'succeeded'
    assert output['provider'] == 'fake'
