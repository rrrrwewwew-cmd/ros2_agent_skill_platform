"""Append-only JSONL Trace recording for governed Skill execution."""

import json
from pathlib import Path
import time


class TraceRecorder:
    """Write bounded machine-readable events for one Agent run."""

    def __init__(self, trace_directory, run_id, trace_id,
                 clock_ns=time.time_ns):
        directory = Path(trace_directory).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'{run_id}.jsonl'
        if self.path.exists():
            raise FileExistsError(f'trace already exists: {self.path}')
        self.trace_id = trace_id
        self.clock_ns = clock_ns
        self.sequence = 0

    def record(self, kind, source, payload, correlation_id=None):
        """Append one event and return its public mapping."""
        self.sequence += 1
        event = {
            'schema_version': 1,
            'timestamp_ns': self.clock_ns(),
            'trace_id': self.trace_id,
            'event_id': f'{self.trace_id}-{self.sequence:04d}',
            'kind': kind,
            'source': source,
            'correlation_id': correlation_id,
            'payload': payload,
        }
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(
                event,
                ensure_ascii=False,
                separators=(',', ':'),
                sort_keys=True,
            ))
            stream.write('\n')
        return event
