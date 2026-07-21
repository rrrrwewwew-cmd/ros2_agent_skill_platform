"""MCP client boundaries for the diagnosis Agent."""

import json
import os
from pathlib import Path
import subprocess


class DiagnosisClientError(RuntimeError):
    """Report a bounded MCP transport or structured-result failure."""


class InProcessDiagnosisClient:
    """Call a configured service directly for deterministic CI tests."""

    def __init__(self, service):
        self.service = service

    def call_tool(self, name, arguments, timeout_sec=None):
        """Dispatch only one of the five explicit service methods."""
        method = getattr(self.service, name, None)
        if method is None or name.startswith('_'):
            raise DiagnosisClientError(f'unknown diagnosis tool: {name}')
        try:
            return method(**arguments)
        except Exception as error:
            raise DiagnosisClientError(str(error)) from error


class SubprocessMcpDiagnosisClient:
    """Invoke the official MCP protocol through a pinned Python boundary."""

    def __init__(
        self,
        mcp_python,
        experiment_root,
        artifact_root,
        rag_index,
        schema_dir,
        module_paths,
        rag_python=None,
        rag_module_paths=None,
        embedding_device='cuda',
        hf_home=None,
    ):
        self.mcp_python = Path(mcp_python).expanduser().absolute()
        if not self.mcp_python.is_file():
            raise DiagnosisClientError('MCP Python executable is unavailable')
        self.experiment_root = Path(experiment_root).expanduser().resolve()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.rag_index = Path(rag_index).expanduser().resolve()
        self.schema_dir = Path(schema_dir).expanduser().resolve()
        self.module_paths = [
            Path(item).expanduser().resolve() for item in module_paths
        ]
        self.rag_python = (
            Path(rag_python).expanduser().absolute() if rag_python else None
        )
        self.rag_module_paths = [
            Path(item).expanduser().resolve()
            for item in (rag_module_paths or [])
        ]
        self.embedding_device = embedding_device
        self.hf_home = (
            Path(hf_home).expanduser().resolve() if hf_home else None
        )

    def _command(self, name, arguments, timeout_sec):
        command = [
            str(self.mcp_python),
            '-m',
            'robot_diagnosis_agent.protocol_call',
            '--experiment-root',
            str(self.experiment_root),
            '--artifact-root',
            str(self.artifact_root),
            '--rag-index',
            str(self.rag_index),
            '--schema-dir',
            str(self.schema_dir),
            '--tool-name',
            name,
            '--arguments-json',
            json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(',', ':'),
                sort_keys=True,
            ),
            '--read-timeout-sec',
            str(float(timeout_sec)),
            '--embedding-device',
            self.embedding_device,
        ]
        if self.rag_python:
            command.extend(['--rag-python', str(self.rag_python)])
        for path in self.rag_module_paths:
            command.extend(['--rag-module-path', str(path)])
        if self.hf_home:
            command.extend(['--hf-home', str(self.hf_home)])
        return command

    def call_tool(self, name, arguments, timeout_sec=120.0):
        """Run one exact MCP call without a shell or inherited proxies."""
        environment = {
            'HOME': str(Path.home()),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PYTHONPATH': os.pathsep.join(map(str, self.module_paths)),
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
        }
        try:
            completed = subprocess.run(
                self._command(name, arguments, timeout_sec),
                check=False,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec) + 10.0,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DiagnosisClientError(f'MCP call failed: {error}') from error
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            detail = (completed.stderr or completed.stdout).strip()[-800:]
            raise DiagnosisClientError(
                'MCP call returned non-JSON output '
                f'(exit {completed.returncode}): {detail}'
            ) from error
        if completed.returncode != 0 or payload.get('state') == 'failed':
            message = payload.get('error') or completed.stderr[-500:]
            raise DiagnosisClientError(f'MCP call rejected: {message}')
        result = payload.get('result')
        if not isinstance(result, dict):
            raise DiagnosisClientError('MCP call omitted structured result')
        return result
