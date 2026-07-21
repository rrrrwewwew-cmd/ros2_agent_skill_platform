"""Isolated local RAG query adapter for Skill Author grounding."""

import json
import os
from pathlib import Path
import subprocess


class SkillAuthorRetrievalError(RuntimeError):
    """Report a local retriever failure without falling back to the web."""


class SubprocessRetriever:
    """Query one immutable RAG index through a pinned Python executable."""

    def __init__(
        self,
        python_executable,
        index_path,
        module_paths,
        embedding_device='cuda',
        hf_home=None,
        timeout_sec=120.0,
    ):
        self.python = Path(python_executable).expanduser().absolute()
        self.index = Path(index_path).expanduser().resolve()
        self.module_paths = [Path(item).resolve() for item in module_paths]
        self.embedding_device = embedding_device
        self.hf_home = Path(
            hf_home or '~/.cache/huggingface'
        ).expanduser().resolve()
        self.timeout_sec = float(timeout_sec)

    def query(self, query, distribution, top_k):
        """Return JSON from the fixed robot_rag query module."""
        command = [
            str(self.python),
            '-m',
            'robot_rag.query_cli',
            query,
            '--index',
            str(self.index),
            '--distribution',
            distribution,
            '--top-k',
            str(top_k),
            '--embedding-device',
            self.embedding_device,
        ]
        environment = {
            'HOME': str(Path.home()),
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'PYTHONPATH': os.pathsep.join(map(str, self.module_paths)),
            'HF_HOME': str(self.hf_home),
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
            'TOKENIZERS_PARALLELISM': 'false',
            'LANG': 'C.UTF-8',
            'LC_ALL': 'C.UTF-8',
        }
        if 'CUDA_VISIBLE_DEVICES' in os.environ:
            environment['CUDA_VISIBLE_DEVICES'] = os.environ[
                'CUDA_VISIBLE_DEVICES'
            ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SkillAuthorRetrievalError(str(error)) from error
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise SkillAuthorRetrievalError(
                'retriever returned non-JSON output'
            ) from error
        if completed.returncode != 0 or result.get('status') == 'failed':
            raise SkillAuthorRetrievalError(
                str(result.get('error') or completed.stderr[-500:])
            )
        return result
