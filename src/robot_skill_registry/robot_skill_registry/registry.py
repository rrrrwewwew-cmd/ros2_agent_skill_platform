"""Transactional Skill governance and persistent bounded Agent state."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from safe_agent_core import validate_skill_manifest


DATABASE_SCHEMA_VERSION = 2
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,96}$')
SKILL_STATES = (
    'DRAFT',
    'GENERATED',
    'STATIC_VALIDATED',
    'BUILT',
    'UNIT_TESTED',
    'SIMULATION_TESTED',
    'HUMAN_APPROVED',
    'SIGNED',
    'ACTIVE',
    'DEPRECATED',
)
SKILL_NEXT_STATE = dict(zip(SKILL_STATES, SKILL_STATES[1:]))
AGENT_STATES = {
    'IDLE',
    'RETRIEVING',
    'PLANNING',
    'VALIDATING',
    'WAITING_APPROVAL',
    'EXECUTING',
    'VERIFYING',
    'SUCCEEDED',
    'FAILED',
    'ABORTED',
    'EMERGENCY_STOP',
}
AGENT_TERMINAL_STATES = {
    'SUCCEEDED', 'FAILED', 'ABORTED', 'EMERGENCY_STOP',
}
AGENT_FORWARD_TRANSITIONS = {
    'IDLE': {'RETRIEVING'},
    'RETRIEVING': {'PLANNING'},
    'PLANNING': {'VALIDATING'},
    'VALIDATING': {'WAITING_APPROVAL', 'EXECUTING'},
    'WAITING_APPROVAL': {'EXECUTING'},
    'EXECUTING': {'VERIFYING'},
    'VERIFYING': {'SUCCEEDED'},
}


class RegistryContractError(ValueError):
    """Raised when an operation violates a governance contract."""


class RegistryConflictError(RuntimeError):
    """Raised for stale state, immutable version, or duplicate run conflicts."""


class RegistryNotFoundError(LookupError):
    """Raised when a requested Skill version or Agent run is absent."""


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )


def _canonical_hash(value):
    return hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise RegistryContractError(f'{field} must be non-empty text')
    return value.strip()


def _timestamp(clock_ns):
    value = clock_ns()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RegistryContractError('clock must return non-negative integer ns')
    return value


def _connect(database_path):
    if str(database_path) == ':memory:':
        path = ':memory:'
    else:
        resolved = Path(database_path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        path = str(resolved)
    connection = sqlite3.connect(
        path,
        isolation_level=None,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA journal_mode = WAL')
    _initialize_database(connection)
    return connection


def _initialize_database(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            component TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS skill_versions (
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            safety_level TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN (
                'DRAFT', 'GENERATED', 'STATIC_VALIDATED', 'BUILT',
                'UNIT_TESTED', 'SIMULATION_TESTED', 'HUMAN_APPROVED',
                'SIGNED', 'ACTIVE', 'DEPRECATED'
            )),
            signature TEXT,
            signer TEXT,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            updated_at_ns INTEGER NOT NULL CHECK (updated_at_ns >= 0),
            PRIMARY KEY (name, version)
        );

        CREATE TABLE IF NOT EXISTS skill_approvals (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            FOREIGN KEY (name, version)
                REFERENCES skill_versions(name, version)
        );

        CREATE TABLE IF NOT EXISTS skill_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            FOREIGN KEY (name, version)
                REFERENCES skill_versions(name, version)
        );

        CREATE TABLE IF NOT EXISTS execution_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            skill_version TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            invocation_hash TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            expires_at_ns INTEGER NOT NULL CHECK (expires_at_ns >= 0),
            consumed_at_ns INTEGER CHECK (
                consumed_at_ns IS NULL OR consumed_at_ns >= 0
            ),
            consumed_by_run_id TEXT,
            FOREIGN KEY (skill_name, skill_version)
                REFERENCES skill_versions(name, version)
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK (state IN (
                'IDLE', 'RETRIEVING', 'PLANNING', 'VALIDATING',
                'WAITING_APPROVAL', 'EXECUTING', 'VERIFYING', 'SUCCEEDED',
                'FAILED', 'ABORTED', 'EMERGENCY_STOP'
            )),
            request_json TEXT NOT NULL,
            plan_json TEXT,
            terminal_reason TEXT,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            updated_at_ns INTEGER NOT NULL CHECK (updated_at_ns >= 0)
        );

        CREATE TABLE IF NOT EXISTS agent_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
            FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS skill_events_lookup
            ON skill_events(name, version, sequence);
        CREATE INDEX IF NOT EXISTS agent_events_lookup
            ON agent_events(run_id, sequence);
        CREATE INDEX IF NOT EXISTS execution_approvals_lookup
            ON execution_approvals(skill_name, skill_version, created_at_ns);
        """
    )
    row = connection.execute(
        'SELECT schema_version FROM schema_metadata WHERE component = ?',
        ('robot_skill_registry',),
    ).fetchone()
    if row is None:
        connection.execute(
            'INSERT INTO schema_metadata(component, schema_version) '
            'VALUES (?, ?)',
            ('robot_skill_registry', DATABASE_SCHEMA_VERSION),
        )
    elif row['schema_version'] == 1:
        connection.execute(
            'UPDATE schema_metadata SET schema_version = ? '
            'WHERE component = ?',
            (DATABASE_SCHEMA_VERSION, 'robot_skill_registry'),
        )
    elif row['schema_version'] != DATABASE_SCHEMA_VERSION:
        raise RegistryContractError('unsupported registry database schema')


@contextmanager
def _write_transaction(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
    except Exception:
        connection.execute('ROLLBACK')
        raise
    else:
        connection.execute('COMMIT')


def _skill_record(row):
    return {
        'schema_version': 1,
        'name': row['name'],
        'version': row['version'],
        'artifact_hash': row['artifact_hash'],
        'manifest': json.loads(row['manifest_json']),
        'safety_level': row['safety_level'],
        'state': row['state'],
        'signature': row['signature'],
        'signer': row['signer'],
        'created_at_ns': row['created_at_ns'],
        'updated_at_ns': row['updated_at_ns'],
    }


def _agent_record(row):
    return {
        'schema_version': 1,
        'run_id': row['run_id'],
        'trace_id': row['trace_id'],
        'state': row['state'],
        'request': json.loads(row['request_json']),
        'plan': json.loads(row['plan_json']) if row['plan_json'] else None,
        'terminal_reason': row['terminal_reason'],
        'created_at_ns': row['created_at_ns'],
        'updated_at_ns': row['updated_at_ns'],
    }


def _execution_approval_record(row):
    return {
        'schema_version': 1,
        'approval_id': row['approval_id'],
        'run_id': row['run_id'],
        'skill_name': row['skill_name'],
        'skill_version': row['skill_version'],
        'artifact_hash': row['artifact_hash'],
        'invocation_hash': row['invocation_hash'],
        'decision': row['decision'],
        'actor': row['actor'],
        'reason': row['reason'],
        'created_at_ns': row['created_at_ns'],
        'expires_at_ns': row['expires_at_ns'],
        'consumed_at_ns': row['consumed_at_ns'],
        'consumed_by_run_id': row['consumed_by_run_id'],
    }


class _DatabaseOwner:
    def __init__(self, database_path, clock_ns):
        self._connection = _connect(database_path)
        self._clock_ns = clock_ns

    def close(self):
        """Close the owned SQLite connection."""
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, _exception_type, _exception, _traceback):
        self.close()


class SkillRegistry(_DatabaseOwner):
    """Immutable version registry with transactional governance events."""

    def __init__(self, database_path, clock_ns=time.time_ns):
        super().__init__(database_path, clock_ns)

    def register_manifest(self, manifest, artifact_hash=None,
                          actor='skill_author'):
        """Register a validated immutable Skill version at ``DRAFT``."""
        normalized = validate_skill_manifest(manifest)
        canonical_manifest = _canonical_json(normalized)
        effective_hash = artifact_hash or _canonical_hash(normalized)
        if not isinstance(effective_hash, str) or not HASH_PATTERN.fullmatch(
                effective_hash):
            raise RegistryContractError('artifact_hash must be lowercase SHA-256')
        actor = _require_text(actor, 'actor')
        name = normalized['name']
        version = normalized['version']
        now = _timestamp(self._clock_ns)
        with _write_transaction(self._connection):
            existing = self._connection.execute(
                'SELECT * FROM skill_versions WHERE name = ? AND version = ?',
                (name, version),
            ).fetchone()
            if existing:
                if (
                    existing['artifact_hash'] == effective_hash and
                    existing['manifest_json'] == canonical_manifest
                ):
                    return _skill_record(existing)
                raise RegistryConflictError(
                    'Skill name/version is immutable and already has '
                    'different content'
                )
            self._connection.execute(
                """
                INSERT INTO skill_versions(
                    name, version, artifact_hash, manifest_json, safety_level,
                    state, signature, signer, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, 'DRAFT', NULL, NULL, ?, ?)
                """,
                (
                    name, version, effective_hash, canonical_manifest,
                    normalized['safety_level'], now, now,
                ),
            )
            self._insert_skill_event(
                name,
                version,
                effective_hash,
                None,
                'DRAFT',
                actor,
                'registered immutable Skill version',
                now,
            )
        return self.get_skill(name, version)

    def get_skill(self, name, version):
        """Return one Skill record or raise ``RegistryNotFoundError``."""
        row = self._connection.execute(
            'SELECT * FROM skill_versions WHERE name = ? AND version = ?',
            (name, version),
        ).fetchone()
        if row is None:
            raise RegistryNotFoundError(f'Skill not found: {name}@{version}')
        return _skill_record(row)

    def list_skills(self, state=None):
        """List governed Skill versions, optionally filtering by state."""
        if state is None:
            rows = self._connection.execute(
                'SELECT * FROM skill_versions ORDER BY name, version'
            ).fetchall()
        else:
            if state not in SKILL_STATES:
                raise RegistryContractError(f'unsupported Skill state: {state}')
            rows = self._connection.execute(
                'SELECT * FROM skill_versions WHERE state = ? '
                'ORDER BY name, version',
                (state,),
            ).fetchall()
        return [_skill_record(row) for row in rows]

    def advance(self, name, version, target_state, expected_current_state,
                actor, reason):
        """Advance exactly one ordinary lifecycle edge."""
        if target_state in {'HUMAN_APPROVED', 'SIGNED'}:
            raise RegistryContractError(
                f'{target_state} requires its dedicated governance operation'
            )
        return self._transition_skill(
            name,
            version,
            target_state,
            expected_current_state,
            actor,
            reason,
        )

    def approve(self, name, version, expected_artifact_hash, actor, reason,
                decision='APPROVED'):
        """Record a hash-bound decision and atomically approve when accepted."""
        if decision not in {'APPROVED', 'REJECTED'}:
            raise RegistryContractError('decision must be APPROVED or REJECTED')
        actor = _require_text(actor, 'actor')
        reason = _require_text(reason, 'reason')
        now = _timestamp(self._clock_ns)
        with _write_transaction(self._connection):
            row = self._skill_row(name, version)
            self._check_artifact_hash(row, expected_artifact_hash)
            if row['state'] != 'SIMULATION_TESTED':
                raise RegistryConflictError(
                    'approval requires state SIMULATION_TESTED'
                )
            self._connection.execute(
                """
                INSERT INTO skill_approvals(
                    name, version, artifact_hash, decision, actor, reason,
                    created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, version, row['artifact_hash'], decision, actor,
                    reason, now,
                ),
            )
            if decision == 'APPROVED':
                self._connection.execute(
                    'UPDATE skill_versions SET state = ?, updated_at_ns = ? '
                    'WHERE name = ? AND version = ?',
                    ('HUMAN_APPROVED', now, name, version),
                )
                self._insert_skill_event(
                    name,
                    version,
                    row['artifact_hash'],
                    'SIMULATION_TESTED',
                    'HUMAN_APPROVED',
                    actor,
                    reason,
                    now,
                )
        return self.get_skill(name, version)

    def record_verified_signature(self, name, version, expected_artifact_hash,
                                  signature, signer, reason):
        """Store an externally verified signature and enter ``SIGNED``."""
        signature = _require_text(signature, 'signature')
        signer = _require_text(signer, 'signer')
        reason = _require_text(reason, 'reason')
        now = _timestamp(self._clock_ns)
        with _write_transaction(self._connection):
            row = self._skill_row(name, version)
            self._check_artifact_hash(row, expected_artifact_hash)
            if row['state'] != 'HUMAN_APPROVED':
                raise RegistryConflictError(
                    'signature requires state HUMAN_APPROVED'
                )
            self._connection.execute(
                """
                UPDATE skill_versions
                SET state = 'SIGNED', signature = ?, signer = ?,
                    updated_at_ns = ?
                WHERE name = ? AND version = ?
                """,
                (signature, signer, now, name, version),
            )
            self._insert_skill_event(
                name,
                version,
                row['artifact_hash'],
                'HUMAN_APPROVED',
                'SIGNED',
                signer,
                reason,
                now,
            )
        return self.get_skill(name, version)

    def list_events(self, name, version):
        """Return the append-only lifecycle audit trail."""
        self.get_skill(name, version)
        rows = self._connection.execute(
            'SELECT * FROM skill_events WHERE name = ? AND version = ? '
            'ORDER BY sequence',
            (name, version),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_approvals(self, name, version):
        """Return every accepted or rejected hash-bound approval decision."""
        self.get_skill(name, version)
        rows = self._connection.execute(
            'SELECT * FROM skill_approvals WHERE name = ? AND version = ? '
            'ORDER BY sequence',
            (name, version),
        ).fetchall()
        return [dict(row) for row in rows]

    def issue_execution_approval(self, invocation, actor, reason,
                                 ttl_sec=120.0, decision='APPROVED'):
        """Create one expiring approval bound to an exact invocation."""
        if not isinstance(invocation, dict):
            raise RegistryContractError('invocation must be an object')
        required = {
            'approval_id', 'run_id', 'trace_id', 'skill_name',
            'skill_version', 'artifact_hash', 'inputs',
        }
        missing = sorted(required - invocation.keys())
        if missing:
            raise RegistryContractError(
                f'execution approval invocation is missing: {missing}'
            )
        approval_id = _require_text(
            invocation['approval_id'], 'approval_id',
        )
        run_id = _require_text(invocation['run_id'], 'run_id')
        if not IDENTIFIER_PATTERN.fullmatch(approval_id):
            raise RegistryContractError('approval_id has invalid format')
        if not IDENTIFIER_PATTERN.fullmatch(run_id):
            raise RegistryContractError('run_id has invalid format')
        if decision not in {'APPROVED', 'REJECTED'}:
            raise RegistryContractError(
                'decision must be APPROVED or REJECTED'
            )
        actor = _require_text(actor, 'actor')
        reason = _require_text(reason, 'reason')
        if isinstance(ttl_sec, bool) or not isinstance(ttl_sec, (int, float)):
            raise RegistryContractError('ttl_sec must be numeric')
        ttl_sec = float(ttl_sec)
        if not 1.0 <= ttl_sec <= 300.0:
            raise RegistryContractError('ttl_sec must be in [1, 300]')
        name = _require_text(invocation['skill_name'], 'skill_name')
        version = _require_text(invocation['skill_version'], 'skill_version')
        artifact_hash = _require_text(
            invocation['artifact_hash'], 'artifact_hash',
        )
        if not HASH_PATTERN.fullmatch(artifact_hash):
            raise RegistryContractError(
                'artifact_hash must be lowercase SHA-256'
            )
        now = _timestamp(self._clock_ns)
        expires_at_ns = now + int(ttl_sec * 1_000_000_000)
        invocation_hash = _canonical_hash(invocation)
        with _write_transaction(self._connection):
            skill = self._skill_row(name, version)
            self._check_artifact_hash(skill, artifact_hash)
            if skill['state'] != 'ACTIVE':
                raise RegistryConflictError(
                    'execution approval requires an ACTIVE Skill'
                )
            manifest = json.loads(skill['manifest_json'])
            if not (
                manifest['requires_human_approval'] or
                manifest['safety_level'] in {'controlled', 'high'}
            ):
                raise RegistryContractError(
                    'read-only Skill does not accept execution approval'
                )
            try:
                self._connection.execute(
                    """
                    INSERT INTO execution_approvals(
                        approval_id, run_id, skill_name, skill_version,
                        artifact_hash, invocation_hash, decision, actor,
                        reason, created_at_ns, expires_at_ns,
                        consumed_at_ns, consumed_by_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        approval_id, run_id, name, version, artifact_hash,
                        invocation_hash, decision, actor, reason, now,
                        expires_at_ns,
                    ),
                )
            except sqlite3.IntegrityError as exception:
                raise RegistryConflictError(
                    'approval_id must be unique'
                ) from exception
        return self.get_execution_approval(approval_id)

    def get_execution_approval(self, approval_id):
        """Return one execution approval without consuming it."""
        row = self._connection.execute(
            'SELECT * FROM execution_approvals WHERE approval_id = ?',
            (approval_id,),
        ).fetchone()
        if row is None:
            raise RegistryNotFoundError(
                f'Execution approval not found: {approval_id}'
            )
        return _execution_approval_record(row)

    def consume_execution_approval(self, approval_id, invocation):
        """Atomically consume one fresh exact-invocation approval."""
        if not isinstance(invocation, dict):
            raise RegistryContractError('invocation must be an object')
        now = _timestamp(self._clock_ns)
        invocation_hash = _canonical_hash(invocation)
        run_id = _require_text(invocation.get('run_id'), 'run_id')
        with _write_transaction(self._connection):
            row = self._connection.execute(
                'SELECT * FROM execution_approvals WHERE approval_id = ?',
                (approval_id,),
            ).fetchone()
            if row is None:
                raise RegistryNotFoundError(
                    f'Execution approval not found: {approval_id}'
                )
            if row['decision'] != 'APPROVED':
                raise RegistryContractError('execution approval was rejected')
            if row['consumed_at_ns'] is not None:
                raise RegistryConflictError(
                    'execution approval has already been consumed'
                )
            if now > row['expires_at_ns']:
                raise RegistryContractError('execution approval has expired')
            if row['run_id'] != run_id:
                raise RegistryContractError(
                    'execution approval run_id does not match invocation'
                )
            if row['invocation_hash'] != invocation_hash:
                raise RegistryContractError(
                    'execution approval is not bound to this invocation'
                )
            self._connection.execute(
                """
                UPDATE execution_approvals
                SET consumed_at_ns = ?, consumed_by_run_id = ?
                WHERE approval_id = ? AND consumed_at_ns IS NULL
                """,
                (now, run_id, approval_id),
            )
        return self.get_execution_approval(approval_id)

    def _transition_skill(self, name, version, target_state,
                          expected_current_state, actor, reason):
        if target_state not in SKILL_STATES:
            raise RegistryContractError(
                f'unsupported Skill state: {target_state}'
            )
        actor = _require_text(actor, 'actor')
        reason = _require_text(reason, 'reason')
        now = _timestamp(self._clock_ns)
        with _write_transaction(self._connection):
            row = self._skill_row(name, version)
            current = row['state']
            if current != expected_current_state:
                raise RegistryConflictError(
                    f'stale Skill state: expected {expected_current_state}, '
                    f'found {current}'
                )
            if SKILL_NEXT_STATE.get(current) != target_state:
                raise RegistryContractError(
                    f'illegal Skill transition: {current} -> {target_state}'
                )
            if target_state == 'ACTIVE' and not row['signature']:
                raise RegistryContractError(
                    'ACTIVE Skill requires a stored verified signature'
                )
            self._connection.execute(
                'UPDATE skill_versions SET state = ?, updated_at_ns = ? '
                'WHERE name = ? AND version = ?',
                (target_state, now, name, version),
            )
            self._insert_skill_event(
                name,
                version,
                row['artifact_hash'],
                current,
                target_state,
                actor,
                reason,
                now,
            )
        return self.get_skill(name, version)

    def _skill_row(self, name, version):
        row = self._connection.execute(
            'SELECT * FROM skill_versions WHERE name = ? AND version = ?',
            (name, version),
        ).fetchone()
        if row is None:
            raise RegistryNotFoundError(f'Skill not found: {name}@{version}')
        return row

    @staticmethod
    def _check_artifact_hash(row, expected_artifact_hash):
        if row['artifact_hash'] != expected_artifact_hash:
            raise RegistryConflictError('artifact hash does not match approval target')

    def _insert_skill_event(self, name, version, artifact_hash, from_state,
                            to_state, actor, reason, timestamp_ns):
        self._connection.execute(
            """
            INSERT INTO skill_events(
                name, version, artifact_hash, from_state, to_state, actor,
                reason, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, version, artifact_hash, from_state, to_state, actor,
                reason, timestamp_ns,
            ),
        )


class AgentRunStore(_DatabaseOwner):
    """Persistent bounded Agent run state with append-only transitions."""

    def __init__(self, database_path, clock_ns=time.time_ns):
        super().__init__(database_path, clock_ns)

    def create_run(self, run_id, trace_id, request, actor='runtime'):
        """Create an ``IDLE`` run and its first audit event."""
        run_id = _require_text(run_id, 'run_id')
        trace_id = _require_text(trace_id, 'trace_id')
        actor = _require_text(actor, 'actor')
        if not isinstance(request, dict):
            raise RegistryContractError('request must be an object')
        now = _timestamp(self._clock_ns)
        try:
            with _write_transaction(self._connection):
                self._connection.execute(
                    """
                    INSERT INTO agent_runs(
                        run_id, trace_id, state, request_json, plan_json,
                        terminal_reason, created_at_ns, updated_at_ns
                    ) VALUES (?, ?, 'IDLE', ?, NULL, NULL, ?, ?)
                    """,
                    (run_id, trace_id, _canonical_json(request), now, now),
                )
                self._insert_agent_event(
                    run_id,
                    None,
                    'IDLE',
                    actor,
                    'created bounded Agent run',
                    now,
                )
        except sqlite3.IntegrityError as error:
            raise RegistryConflictError(
                'run_id and trace_id must be unique'
            ) from error
        return self.get_run(run_id)

    def get_run(self, run_id):
        """Return one persistent Agent run."""
        row = self._connection.execute(
            'SELECT * FROM agent_runs WHERE run_id = ?',
            (run_id,),
        ).fetchone()
        if row is None:
            raise RegistryNotFoundError(f'Agent run not found: {run_id}')
        return _agent_record(row)

    def transition(self, run_id, target_state, expected_current_state,
                   actor, reason, plan=None):
        """Apply one bounded state transition with optimistic concurrency."""
        if target_state not in AGENT_STATES:
            raise RegistryContractError(
                f'unsupported Agent state: {target_state}'
            )
        actor = _require_text(actor, 'actor')
        reason = _require_text(reason, 'reason')
        if plan is not None and not isinstance(plan, dict):
            raise RegistryContractError('plan must be an object')
        now = _timestamp(self._clock_ns)
        with _write_transaction(self._connection):
            row = self._agent_row(run_id)
            current = row['state']
            if current != expected_current_state:
                raise RegistryConflictError(
                    f'stale Agent state: expected {expected_current_state}, '
                    f'found {current}'
                )
            if not self._agent_transition_allowed(current, target_state):
                raise RegistryContractError(
                    f'illegal Agent transition: {current} -> {target_state}'
                )
            if target_state == 'VALIDATING' and plan is None:
                raise RegistryContractError(
                    'PLANNING -> VALIDATING requires a structured plan'
                )
            if plan is not None and target_state != 'VALIDATING':
                raise RegistryContractError(
                    'plan can only be stored when entering VALIDATING'
                )
            plan_json = _canonical_json(plan) if plan is not None else row['plan_json']
            if target_state == 'EXECUTING' and plan_json is None:
                raise RegistryContractError('EXECUTING requires a stored plan')
            terminal_reason = reason if target_state in AGENT_TERMINAL_STATES else None
            self._connection.execute(
                """
                UPDATE agent_runs
                SET state = ?, plan_json = ?, terminal_reason = ?,
                    updated_at_ns = ?
                WHERE run_id = ?
                """,
                (target_state, plan_json, terminal_reason, now, run_id),
            )
            self._insert_agent_event(
                run_id,
                current,
                target_state,
                actor,
                reason,
                now,
            )
        return self.get_run(run_id)

    def fail_closed_recover(self, actor='startup_recovery'):
        """Abort unfinished runs so a restart cannot repeat side effects."""
        actor = _require_text(actor, 'actor')
        now = _timestamp(self._clock_ns)
        active_states = sorted(
            AGENT_STATES - AGENT_TERMINAL_STATES - {'IDLE'}
        )
        placeholders = ','.join('?' for _ in active_states)
        recovered = []
        with _write_transaction(self._connection):
            rows = self._connection.execute(
                f'SELECT * FROM agent_runs WHERE state IN ({placeholders}) '
                'ORDER BY run_id',
                active_states,
            ).fetchall()
            for row in rows:
                reason = 'process_restart_fail_closed'
                self._connection.execute(
                    """
                    UPDATE agent_runs
                    SET state = 'ABORTED', terminal_reason = ?, updated_at_ns = ?
                    WHERE run_id = ?
                    """,
                    (reason, now, row['run_id']),
                )
                self._insert_agent_event(
                    row['run_id'],
                    row['state'],
                    'ABORTED',
                    actor,
                    reason,
                    now,
                )
                recovered.append(row['run_id'])
        return recovered

    def list_events(self, run_id):
        """Return the append-only Agent run transition trail."""
        self.get_run(run_id)
        rows = self._connection.execute(
            'SELECT * FROM agent_events WHERE run_id = ? ORDER BY sequence',
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _agent_row(self, run_id):
        row = self._connection.execute(
            'SELECT * FROM agent_runs WHERE run_id = ?',
            (run_id,),
        ).fetchone()
        if row is None:
            raise RegistryNotFoundError(f'Agent run not found: {run_id}')
        return row

    @staticmethod
    def _agent_transition_allowed(current, target):
        if current in AGENT_TERMINAL_STATES:
            return False
        if target == 'EMERGENCY_STOP':
            return True
        if target in {'FAILED', 'ABORTED'}:
            return current != 'IDLE'
        return target in AGENT_FORWARD_TRANSITIONS.get(current, set())

    def _insert_agent_event(self, run_id, from_state, to_state, actor,
                            reason, timestamp_ns):
        self._connection.execute(
            """
            INSERT INTO agent_events(
                run_id, from_state, to_state, actor, reason, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, from_state, to_state, actor, reason, timestamp_ns),
        )
