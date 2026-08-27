from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Collection
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.task_result_rollout import (
    TASK_RESULT_RUNTIME_WRITE_STATE as MODEL_TASK_RESULT_RUNTIME_WRITE_STATE,
    TaskResultRolloutStatus,
    TaskResultStorageState,
)
from netconsole.models.task_state import TaskState
from netconsole.models.task_snapshot import (
    TEXT_INTEGRITY_VALUES,
    TaskEvent,
    TaskSnapshot,
    utc_now_iso,
)
from netconsole.models.task_history_policy import (
    ACTIVE_TASK_STATE_VALUES,
    TASK_HISTORY_SCOPE_LIMIT,
    TERMINAL_TASK_STATE_VALUES,
    task_expires_at,
    task_has_long_term_reference,
    task_requires_attention,
    task_history_scope,
    utc_time_reached,
)
from netconsole.repositories.history_store import TaskHistoryStore, verify_task_result_row
from netconsole.repositories.task_result_blob_repository import (
    TASK_RESULT_BLOB_CODEC_ZLIB,
    TaskResultBlobError,
    ensure_blob,
    read_blob,
)


TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO task_schema_meta(key, value) VALUES ('schema_version', '5');

CREATE TABLE IF NOT EXISTS task_result_storage_rollout (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    state TEXT NOT NULL CHECK(state IN (
        'LEGACY_DUAL_FULL',
        'TASK_RESULTS_DUAL_WRITE',
        'TASK_RESULTS_VERIFIED',
        'RESULT_REF_AUTHORITY'
    )),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);
INSERT OR IGNORE INTO task_result_storage_rollout (
    singleton_id, state, revision, updated_at, updated_by, reason, schema_version
) VALUES (
    1,
    'RESULT_REF_AUTHORITY',
    1,
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    'schema',
    'result authority and blob storage rollout',
    5
);

CREATE TABLE IF NOT EXISTS task_result_storage_rollout_audit (
    revision INTEGER PRIMARY KEY CHECK(revision >= 2),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_task_result_rollout_audit_immutable_update
BEFORE UPDATE ON task_result_storage_rollout_audit
BEGIN
    SELECT RAISE(ABORT, 'task result rollout audit rows are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_task_result_rollout_audit_immutable_delete
BEFORE DELETE ON task_result_storage_rollout_audit
BEGIN
    SELECT RAISE(ABORT, 'task result rollout audit rows are immutable');
END;

CREATE TABLE IF NOT EXISTS task_snapshots (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    task_name TEXT NOT NULL,
    created_time TEXT NOT NULL,
    started_time TEXT NOT NULL DEFAULT '',
    finished_time TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    current INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '',
    result_path TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    result_id TEXT NOT NULL DEFAULT '',
    result_hash TEXT NOT NULL DEFAULT '',
    result_summary_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'local',
    site_name TEXT NOT NULL DEFAULT 'demo',
    owner_pid INTEGER NOT NULL DEFAULT 0,
    resource_keys_json TEXT NOT NULL DEFAULT '[]',
    text_integrity TEXT NOT NULL DEFAULT 'ok',
    text_integrity_reason TEXT NOT NULL DEFAULT '',
    text_integrity_updated_at TEXT NOT NULL DEFAULT '',
    text_schema_version INTEGER NOT NULL DEFAULT 1,
    producer_kind TEXT NOT NULL DEFAULT 'legacy',
    producer_version TEXT NOT NULL DEFAULT 'unknown',
    producer_commit TEXT NOT NULL DEFAULT 'unknown',
    expires_at TEXT NOT NULL DEFAULT '',
    acknowledged_at TEXT NOT NULL DEFAULT '',
    dismissed_at TEXT NOT NULL DEFAULT '',
    dismissed_by TEXT NOT NULL DEFAULT '',
    dismiss_reason TEXT NOT NULL DEFAULT '',
    updated_time TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_status_updated
    ON task_snapshots(status, updated_time DESC);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_type_updated
    ON task_snapshots(task_type, updated_time DESC);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_file_filter
    ON task_snapshots(task_type, owner, source, site_name, status, updated_time DESC);

CREATE TABLE IF NOT EXISTS task_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    terminal_event_type TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    created_time TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    blob_codec TEXT NOT NULL DEFAULT '',
    blob_ready INTEGER NOT NULL DEFAULT 0 CHECK(blob_ready IN (0, 1)),
    UNIQUE(task_id, terminal_event_type, sha256)
);
CREATE INDEX IF NOT EXISTS idx_task_results_task_created
    ON task_results(task_id, created_time DESC, result_id);
CREATE TABLE IF NOT EXISTS task_result_blobs (
    content_sha256 TEXT PRIMARY KEY,
    codec TEXT NOT NULL CHECK(codec IN ('zlib')),
    compressed_blob BLOB NOT NULL,
    uncompressed_bytes INTEGER NOT NULL,
    compressed_bytes INTEGER NOT NULL,
    created_time TEXT NOT NULL,
    verified_at TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS trg_task_results_immutable
BEFORE UPDATE ON task_results
WHEN NOT (
    OLD.result_id = NEW.result_id
    AND OLD.task_id = NEW.task_id
    AND OLD.terminal_event_type = NEW.terminal_event_type
    AND OLD.canonical_json = NEW.canonical_json
    AND OLD.sha256 = NEW.sha256
    AND OLD.byte_size = NEW.byte_size
    AND OLD.schema_version = NEW.schema_version
    AND OLD.created_time = NEW.created_time
    AND (
        (OLD.content_sha256 = NEW.content_sha256
         AND OLD.blob_codec = NEW.blob_codec
         AND OLD.blob_ready = NEW.blob_ready)
        OR (OLD.blob_ready = 0
            AND NEW.blob_ready = 1
            AND NEW.content_sha256 = OLD.sha256
            AND NEW.blob_codec = 'zlib')
    )
)
BEGIN
    SELECT RAISE(ABORT, 'task_results rows are immutable');
END;

CREATE TABLE IF NOT EXISTS task_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'service',
    payload_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(task_id) REFERENCES task_snapshots(task_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence
    ON task_events(task_id, sequence DESC);

CREATE TABLE IF NOT EXISTS task_retention_tombstones (
    task_id TEXT PRIMARY KEY,
    retired_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
"""

PROGRESS_EVENT_HEARTBEAT_SECONDS = 30
TASK_RESULT_SCHEMA_VERSION = 1
TERMINAL_RESULT_EVENT_TYPES = frozenset({"finished", "error", "cancelled"})
# Persisted rollout rows remain available for historical maintenance, but they
# cannot alter the current writer until a separately approved rollout phase.
TASK_RESULT_RUNTIME_WRITE_STATE = MODEL_TASK_RESULT_RUNTIME_WRITE_STATE


class TaskRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        # task_results are immutable and addressed by deterministic result_id.
        # Cache verified canonical payloads so a task detail read does not
        # re-hash one large result for the snapshot and each terminal event.
        self._verified_result_cache: dict[str, dict[str, Any]] = {}
        self.task_history = TaskHistoryStore(self.db_path)
        self.initialize()

    def _connect(self):
        return connect_sqlite(self.db_path, foreign_keys=True)

    def initialize(self) -> None:
        def operation() -> None:
            with self._connect() as conn:
                initialize_sqlite_wal(conn)
                conn.executescript(TASK_SCHEMA)
                # ``executescript`` runs DDL in its own implicit transaction.
                # Serialize the compatibility pass separately so concurrent
                # Task Center workers cannot race a trigger recreation.
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                self._ensure_schema_compat(conn)
                conn.commit()

        run_sqlite_with_retry(operation)

    def save(self, snapshot: TaskSnapshot) -> None:
        def operation() -> None:
            with self._connect() as conn:
                stored_snapshot = snapshot
                terminal_event_type = self._terminal_event_type_for_status(
                    snapshot.status
                )
                if (
                    terminal_event_type
                    and isinstance(snapshot.result, dict)
                    and snapshot.result
                ):
                    stored_snapshot, _ = self._prepare_terminal_result(
                        conn,
                        snapshot,
                        TaskEvent(
                            event_id=f"save-{snapshot.task_id}",
                            task_id=snapshot.task_id,
                            type=terminal_event_type,
                            time=(
                                snapshot.finished_time
                                or snapshot.updated_time
                                or utc_now_iso()
                            ),
                            source="repository.save",
                            payload={"result": dict(snapshot.result)},
                        ),
                    )
                self._upsert(conn, stored_snapshot)
                conn.commit()

        run_sqlite_with_retry(operation)

    def save_with_resource_guard(
        self,
        snapshot: TaskSnapshot,
        *,
        active_statuses: Collection[TaskState],
    ) -> TaskSnapshot | None:
        """Persist a task only when none of its resource keys are already active."""

        requested = self._resource_key_set(snapshot.resource_keys)
        if not requested:
            self.save(snapshot)
            return None
        conflict: TaskSnapshot | None = None

        def operation() -> None:
            nonlocal conflict
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                active_values = sorted(state.value for state in active_statuses)
                rows = conn.execute(
                    f"""
                    SELECT * FROM task_snapshots
                    WHERE site_name = ?
                      AND status IN ({",".join("?" for _ in active_values)})
                      AND resource_keys_json <> '[]'
                    ORDER BY updated_time DESC, created_time DESC, task_id DESC
                    """,
                    (snapshot.site_name, *active_values),
                ).fetchall()
                for row in rows:
                    current = self._snapshot_from_connection_row(conn, dict(row))
                    if current.task_id == snapshot.task_id:
                        continue
                    if self._resource_key_set(current.resource_keys) & requested:
                        conflict = current
                        conn.rollback()
                        return
                self._upsert(conn, snapshot)
                conn.commit()

        run_sqlite_with_retry(operation)
        return conflict

    def record(
        self,
        snapshot: TaskSnapshot,
        event: TaskEvent,
        *,
        allowed_from: Collection[TaskState] | None = None,
    ) -> bool:
        recorded = False

        def operation() -> None:
            nonlocal recorded
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                exists = conn.execute(
                    "SELECT 1 FROM task_events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if exists is not None:
                    conn.rollback()
                    return
                if self._is_retention_tombstoned(conn, event.task_id):
                    conn.rollback()
                    return
                if self._sample_repeated_progress(conn, event):
                    conn.rollback()
                    recorded = True
                    return
                stored_snapshot, stored_event = self._prepare_terminal_result(
                    conn, snapshot, event
                )
                if not self._upsert(
                    conn, stored_snapshot, allowed_from=allowed_from
                ):
                    conn.rollback()
                    return
                conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, event_type, event_time, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored_event.event_id,
                        stored_event.task_id,
                        stored_event.type,
                        stored_event.time,
                        stored_event.source,
                        json.dumps(
                            stored_event.payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    ),
                )
                conn.commit()
                recorded = True

        run_sqlite_with_retry(operation)
        return recorded

    @classmethod
    def _sample_repeated_progress(cls, conn, event: TaskEvent) -> bool:
        """Keep current progress accurate while bounding identical event history."""

        if event.type != "progress":
            return False
        row = conn.execute(
            """
            SELECT event_type, event_time, source, payload_json
            FROM task_events
            WHERE task_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (event.task_id,),
        ).fetchone()
        if row is None or str(row["event_type"]) != "progress":
            return False
        if str(row["source"] or "") != str(event.source or ""):
            return False
        try:
            previous_payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if previous_payload != event.payload:
            return False
        previous_time = cls._event_datetime(str(row["event_time"] or ""))
        current_time = cls._event_datetime(event.time)
        if previous_time is None or current_time is None:
            return False
        elapsed = (current_time - previous_time).total_seconds()
        return 0 <= elapsed < PROGRESS_EVENT_HEARTBEAT_SECONDS

    @staticmethod
    def _event_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def record_once(
        self,
        snapshot: TaskSnapshot,
        event: TaskEvent,
        *,
        allowed_from: Collection[TaskState] | None = None,
    ) -> bool:
        """Atomically persist a snapshot/event pair only once by event id."""

        recorded = False

        def operation() -> None:
            nonlocal recorded
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                exists = conn.execute(
                    "SELECT 1 FROM task_events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if exists is not None:
                    conn.rollback()
                    return
                if self._is_retention_tombstoned(conn, event.task_id):
                    conn.rollback()
                    return
                stored_snapshot, stored_event = self._prepare_terminal_result(
                    conn, snapshot, event
                )
                if not self._upsert(conn, stored_snapshot, allowed_from=allowed_from):
                    conn.rollback()
                    return
                conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, event_type, event_time, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored_event.event_id,
                        stored_event.task_id,
                        stored_event.type,
                        stored_event.time,
                        stored_event.source,
                        json.dumps(
                            stored_event.payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    ),
                )
                conn.commit()
                recorded = True

        run_sqlite_with_retry(operation)
        return recorded

    def _prepare_terminal_result(
        self,
        conn,
        snapshot: TaskSnapshot,
        event: TaskEvent,
    ) -> tuple[TaskSnapshot, TaskEvent]:
        """Persist one immutable authority row for every terminal task event."""

        terminal_event_type = self._terminal_event_type_for_status(snapshot.status)
        if terminal_event_type != str(event.type):
            incoming_result = snapshot.result
            result_id = str(snapshot.result_id or "")
            if not isinstance(incoming_result, dict) or not incoming_result or not result_id:
                return snapshot, event

            referenced = self._result_row(conn, result_id)
            if referenced is None:
                # A new full projection supersedes an unavailable historical
                # reference; the immutable authority row itself is untouched.
                return replace(
                    snapshot, result_id="", result_hash="", result_summary={}
                ), event

            verified = self._verified_result_for_read(dict(referenced), conn=conn)
            if str(verified["task_id"]) != str(snapshot.task_id):
                raise sqlite3.DatabaseError("task snapshot result task binding mismatch")
            stored_hash = str(snapshot.result_hash or "")
            if stored_hash and stored_hash != str(verified["sha256"]):
                return replace(
                    snapshot, result_id="", result_hash="", result_summary={}
                ), event
            if self._canonical_result_json(incoming_result) == str(
                verified["canonical_json"]
            ):
                return snapshot, event
            return replace(
                snapshot, result_id="", result_hash="", result_summary={}
            ), event

        incoming_result = snapshot.result
        if not isinstance(incoming_result, dict):
            incoming_result = {}
        explicit_result_id = str(snapshot.result_id or "")
        if explicit_result_id:
            # Legacy/ref-only snapshots already identify their immutable
            # authority. Preserve the reference so reads can validate the
            # task binding and resolve from TaskHistoryStore when necessary.
            referenced = self._result_row(conn, explicit_result_id)
            if referenced is None:
                # A legacy producer may commit the snapshot before its sealed
                # history row is copied.  Keep the reference intact so the
                # reader fails closed until that authority becomes available;
                # never synthesize a new full payload here.
                return snapshot, event
            verified = self._verified_result_for_read(dict(referenced), conn=conn)
            if str(verified["task_id"]) != str(snapshot.task_id):
                raise sqlite3.DatabaseError("task snapshot result task binding mismatch")
            if str(snapshot.result_hash or "") not in {"", str(verified["sha256"])}:
                raise sqlite3.DatabaseError("task snapshot result hash mismatch")
            if incoming_result and self._canonical_result_json(incoming_result) != str(
                verified["canonical_json"]
            ):
                raise sqlite3.DatabaseError("task snapshot result content mismatch")
            if self._is_local_result_row(conn, explicit_result_id):
                verified = self._ensure_result_blob_for_row(conn, verified)
            return snapshot, event
        event_payload = dict(event.payload or {})
        payload_result = event_payload.get("result")
        if not incoming_result and isinstance(payload_result, dict):
            incoming_result = dict(payload_result)

        existing = conn.execute(
            """
            SELECT * FROM task_results
            WHERE task_id = ? AND terminal_event_type = ?
            ORDER BY created_time, result_id
            LIMIT 1
            """,
            (snapshot.task_id, terminal_event_type),
        ).fetchone()
        if existing is not None:
            verified = self._verified_result_for_read(dict(existing), conn=conn)
            verified = self._ensure_result_blob_for_row(conn, verified)
            result = dict(verified["result"])
        else:
            result = dict(incoming_result)
            canonical_json = self._canonical_result_json(result)
            encoded = canonical_json.encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
            result_id = "tr-" + hashlib.sha256(
                f"{snapshot.task_id}\0{terminal_event_type}\0{digest}".encode("utf-8")
            ).hexdigest()
            created_time = str(
                event.time or snapshot.finished_time or snapshot.updated_time or utc_now_iso()
            )
            self._ensure_result_blob(
                conn,
                canonical_json=canonical_json,
                content_sha256=digest,
                created_time=created_time,
                verified_at=created_time,
            )
            # Once the shared blob is the runtime authority, do not recreate a
            # second full payload projection in ``task_results``.  The legacy
            # column remains readable for pre-existing rows and for the
            # migration tool, while new rows keep only immutable metadata here.
            stored_canonical_json = (
                ""
                if TASK_RESULT_RUNTIME_WRITE_STATE
                == TaskResultStorageState.RESULT_REF_AUTHORITY
                else canonical_json
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO task_results (
                    result_id, task_id, terminal_event_type, canonical_json,
                    sha256, byte_size, schema_version, created_time,
                    content_sha256, blob_codec, blob_ready
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    snapshot.task_id,
                    terminal_event_type,
                    stored_canonical_json,
                    digest,
                    len(encoded),
                    TASK_RESULT_SCHEMA_VERSION,
                    created_time,
                    digest,
                    TASK_RESULT_BLOB_CODEC_ZLIB,
                    1,
                ),
            )
            verified = self._verified_result_for_read(
                dict(
                    conn.execute(
                        "SELECT * FROM task_results WHERE result_id = ?",
                        (result_id,),
                    ).fetchone()
                ),
                conn=conn,
            )
            verified = self._ensure_result_blob_for_row(conn, verified)
            result = dict(verified["result"])

        result_id = str(verified["result_id"])
        result_hash = str(verified["sha256"])
        result_summary = self._result_summary(
            result, byte_size=int(verified["byte_size"])
        )
        event_payload.pop("result", None)
        event_payload.update(
            {
                "result_id": result_id,
                "result_hash": result_hash,
                "result_summary": result_summary,
            }
        )
        stored_snapshot = replace(
            snapshot,
            result={},
            result_id=result_id,
            result_hash=result_hash,
            result_summary=result_summary,
        )
        stored_event = replace(event, payload=event_payload)
        return stored_snapshot, stored_event

    @staticmethod
    def _is_retention_tombstoned(conn, task_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM task_retention_tombstones WHERE task_id = ?",
            (str(task_id),),
        ).fetchone()
        return row is not None

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = self._result_row(conn, str(result_id))
            if row is None:
                return None
            return self._verified_result_for_read(dict(row), conn=conn)

    def task_result_rollout_status(self) -> TaskResultRolloutStatus:
        with self._connect() as conn:
            return self._task_result_rollout_status_from_connection(conn)

    def task_result_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM task_results").fetchone()
            return int(row["count"]) if row is not None else 0

    def compare_and_set_task_result_rollout(
        self,
        *,
        expected_state: TaskResultStorageState,
        expected_revision: int,
        target_state: TaskResultStorageState,
        updated_by: str,
        reason: str,
        allow_advanced: bool = False,
    ) -> TaskResultRolloutStatus | None:
        production_transitions = {
            (
                TaskResultStorageState.LEGACY_DUAL_FULL,
                TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            ),
            (
                TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
                TaskResultStorageState.LEGACY_DUAL_FULL,
            ),
        }
        advanced_transitions = {
            (
                TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
                TaskResultStorageState.TASK_RESULTS_VERIFIED,
            ),
            (
                TaskResultStorageState.TASK_RESULTS_VERIFIED,
                TaskResultStorageState.RESULT_REF_AUTHORITY,
            ),
        }
        transition = (expected_state, target_state)
        if transition not in production_transitions and not (
            allow_advanced and transition in advanced_transitions
        ):
            raise ValueError("task result rollout persistence transition is blocked")
        updated: TaskResultRolloutStatus | None = None

        def operation() -> None:
            nonlocal updated
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                changed_at = utc_now_iso()
                next_revision = int(expected_revision) + 1
                cursor = conn.execute(
                    """
                    UPDATE task_result_storage_rollout
                    SET state = ?, revision = ?, updated_at = ?, updated_by = ?,
                        reason = ?, schema_version = 5
                    WHERE singleton_id = 1 AND state = ? AND revision = ?
                    """,
                    (
                        target_state.value,
                        next_revision,
                        changed_at,
                        updated_by,
                        reason,
                        expected_state.value,
                        int(expected_revision),
                    ),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return
                conn.execute(
                    """
                    INSERT INTO task_result_storage_rollout_audit (
                        revision, from_state, to_state, changed_at,
                        changed_by, reason, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, 5)
                    """,
                    (
                        next_revision,
                        expected_state.value,
                        target_state.value,
                        changed_at,
                        updated_by,
                        reason,
                    ),
                )
                updated = self._task_result_rollout_status_from_connection(conn)
                conn.commit()

        run_sqlite_with_retry(operation)
        return updated

    def list_task_result_rollout_audit(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT revision, from_state, to_state, changed_at,
                       changed_by, reason, schema_version
                FROM task_result_storage_rollout_audit
                ORDER BY revision
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_snapshots WHERE task_id = ?", (task_id,)
            ).fetchone()
            return (
                self._snapshot_from_connection_row(conn, dict(row))
                if row is not None
                else None
            )

    def list(
        self,
        *,
        statuses: set[TaskState] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TaskSnapshot]:
        return self.list_filtered(statuses=statuses, limit=limit, offset=offset)

    def list_filtered(
        self,
        *,
        statuses: Collection[TaskState] | None = None,
        owner: str | None = None,
        source: str | None = None,
        site_name: str | None = None,
        task_types: Collection[str] | None = None,
        device: str | None = None,
        device_aliases: Collection[str] | None = None,
        include_dismissed: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TaskSnapshot]:
        where, params = self._snapshot_filter(
            statuses=statuses,
            owner=owner,
            source=source,
            site_name=site_name,
            task_types=task_types,
            device=device,
            device_aliases=device_aliases,
            include_dismissed=include_dismissed,
        )
        params.extend((max(1, min(int(limit), 1000)), max(0, int(offset))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_snapshots {where} "
                "ORDER BY updated_time DESC, created_time DESC, task_id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [self._snapshot_from_connection_row(conn, dict(row)) for row in rows]

    def count_filtered(
        self,
        *,
        statuses: Collection[TaskState] | None = None,
        owner: str | None = None,
        source: str | None = None,
        site_name: str | None = None,
        task_types: Collection[str] | None = None,
        device: str | None = None,
        device_aliases: Collection[str] | None = None,
        include_dismissed: bool = False,
    ) -> int:
        where, params = self._snapshot_filter(
            statuses=statuses,
            owner=owner,
            source=source,
            site_name=site_name,
            task_types=task_types,
            device=device,
            device_aliases=device_aliases,
            include_dismissed=include_dismissed,
        )
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM task_snapshots {where}", params
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    @staticmethod
    def _snapshot_filter(
        *,
        statuses: Collection[TaskState] | None,
        owner: str | None,
        source: str | None,
        site_name: str | None,
        task_types: Collection[str] | None,
        device: str | None,
        device_aliases: Collection[str] | None,
        include_dismissed: bool,
    ) -> tuple[str, list[object]]:
        params: list[object] = []
        clauses: list[str] = []
        if not include_dismissed:
            clauses.append("dismissed_at = ''")
        if statuses:
            values = sorted(state.value for state in statuses)
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if owner is not None:
            clauses.append("owner = ?")
            params.append(str(owner))
        if source is not None:
            clauses.append("source = ?")
            params.append(str(source))
        if site_name is not None:
            clauses.append("site_name = ?")
            params.append(str(site_name))
        if task_types:
            values = sorted(str(task_type) for task_type in task_types)
            clauses.append(f"task_type IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if device is not None and device_aliases:
            raise ValueError("device 与 device_aliases 不得同时提供")
        if device is not None:
            clauses.append("device = ?")
            params.append(str(device))
        if device_aliases:
            values = sorted(
                {str(value).strip() for value in device_aliases if str(value).strip()}
            )
            if values:
                clauses.append(f"device IN ({','.join('?' for _ in values)})")
                params.extend(values)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def acknowledge_attention_tasks(
        self,
        *,
        task_ids: Collection[str] | None = None,
        acknowledge_all: bool = False,
        acknowledged_at: str | None = None,
    ) -> dict[str, object]:
        requested = {
            str(task_id).strip() for task_id in (task_ids or ()) if str(task_id).strip()
        }
        if not requested and not acknowledge_all:
            return {"acknowledged": 0, "task_ids": [], "acknowledged_at": ""}
        timestamp = str(acknowledged_at or utc_now_iso())
        acknowledged: list[str] = []

        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT task_id, status, error_message, result_json
                           , result_summary_json
                    FROM task_snapshots
                    WHERE dismissed_at = '' AND acknowledged_at = ''
                    """
                ).fetchall()
                for row in rows:
                    task_id = str(row["task_id"])
                    if not acknowledge_all and task_id not in requested:
                        continue
                    status = str(row["status"]).upper()
                    if status not in TERMINAL_TASK_STATE_VALUES:
                        continue
                    if not task_requires_attention(
                        status,
                        error_message=str(row["error_message"] or ""),
                        result=self._policy_result(conn, row),
                    ):
                        continue
                    cursor = conn.execute(
                        """
                        UPDATE task_snapshots
                        SET acknowledged_at = ?
                        WHERE task_id = ? AND dismissed_at = ''
                          AND acknowledged_at = '' AND status = ?
                        """,
                        (timestamp, task_id, status),
                    )
                    if cursor.rowcount:
                        acknowledged.append(task_id)
                conn.commit()

        run_sqlite_with_retry(operation)
        return {
            "acknowledged": len(acknowledged),
            "task_ids": acknowledged,
            "acknowledged_at": timestamp if acknowledged else "",
        }

    def dismiss_task(
        self,
        task_id: str,
        *,
        dismissed_by: str,
        dismiss_reason: str = "single",
        dismissed_at: str | None = None,
    ) -> dict[str, object]:
        timestamp = str(dismissed_at or utc_now_iso())
        dismissed: list[str] = []
        skipped_active = 0
        skipped_unacknowledged = 0

        def operation() -> None:
            nonlocal skipped_active, skipped_unacknowledged
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT task_id, status, error_message, result_json,
                           result_summary_json, acknowledged_at
                    FROM task_snapshots
                    WHERE task_id = ? AND dismissed_at = ''
                    """,
                    (str(task_id),),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return
                status = str(row["status"]).upper()
                if status in ACTIVE_TASK_STATE_VALUES:
                    skipped_active = 1
                    conn.rollback()
                    return
                attention = task_requires_attention(
                    status,
                    error_message=str(row["error_message"] or ""),
                    result=self._policy_result(conn, row),
                )
                if attention and not str(row["acknowledged_at"] or ""):
                    skipped_unacknowledged = 1
                    conn.rollback()
                    return
                cursor = conn.execute(
                    """
                    UPDATE task_snapshots
                    SET dismissed_at = ?, dismissed_by = ?, dismiss_reason = ?
                    WHERE task_id = ? AND dismissed_at = ?
                      AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                    """,
                    (
                        timestamp,
                        str(dismissed_by or "local-user"),
                        str(dismiss_reason or "single"),
                        str(task_id),
                        "",
                    ),
                )
                if cursor.rowcount:
                    dismissed.append(str(task_id))
                conn.commit()

        run_sqlite_with_retry(operation)
        return {
            "matched": 1 if dismissed else 0,
            "dismissed": len(dismissed),
            "skipped_active": skipped_active,
            "skipped_unacknowledged": skipped_unacknowledged,
            "artifacts_deleted": 0,
            "task_ids": dismissed,
            "counts": {
                "completed": 0,
                "cancelled": 0,
                "expired": 0,
                "alerts": 0,
            },
        }

    def cleanup_history(
        self,
        cleanup_type: str,
        *,
        include_states: Collection[str] | None = None,
        exclude_states: Collection[str] | None = None,
        dismissed_by: str,
        dry_run: bool = False,
        dismissed_at: str | None = None,
    ) -> dict[str, object]:
        cleanup = str(cleanup_type or "").strip().casefold()
        allowed_types = {
            "completed",
            "cancelled",
            "expired",
            "completed_and_expired",
            "resolved_alerts",
            "all_history",
        }
        if cleanup not in allowed_types:
            raise ValueError("不支持的任务清理类型")
        included = {
            str(value).strip().upper()
            for value in (include_states or ())
            if str(value).strip()
        }
        excluded = {
            str(value).strip().upper()
            for value in (exclude_states or ())
            if str(value).strip()
        }
        timestamp = str(dismissed_at or utc_now_iso())
        now = datetime.now(UTC)
        matched_ids: list[str] = []
        skipped_active = 0
        skipped_unacknowledged = 0
        counts = {"completed": 0, "cancelled": 0, "expired": 0, "alerts": 0}

        def operation() -> None:
            nonlocal skipped_active, skipped_unacknowledged
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT task_id, status, finished_time, updated_time, error_message,
                           result_json, result_summary_json, expires_at, acknowledged_at
                    FROM task_snapshots
                    WHERE dismissed_at = ''
                    ORDER BY updated_time DESC, task_id DESC
                    """
                ).fetchall()
                for row in rows:
                    status = str(row["status"]).upper()
                    if status in ACTIVE_TASK_STATE_VALUES:
                        if status in included:
                            skipped_active += 1
                        continue
                    if status not in TERMINAL_TASK_STATE_VALUES:
                        continue
                    if included and status not in included:
                        continue
                    if status in excluded:
                        continue
                    result = self._policy_result(conn, row)
                    attention = task_requires_attention(
                        status,
                        error_message=str(row["error_message"] or ""),
                        result=result,
                    )
                    acknowledged = bool(str(row["acknowledged_at"] or ""))
                    expires_at = str(row["expires_at"] or "") or task_expires_at(
                        status,
                        finished_time=str(row["finished_time"] or ""),
                        updated_time=str(row["updated_time"] or ""),
                        error_message=str(row["error_message"] or ""),
                        result=result,
                    )
                    expired = utc_time_reached(expires_at, now=now)
                    eligible = False
                    category = ""
                    if cleanup == "completed":
                        eligible = status == TaskState.COMPLETED.value and not attention
                        category = "completed"
                    elif cleanup == "cancelled":
                        eligible = status == TaskState.CANCELLED.value
                        category = "cancelled"
                    elif cleanup == "expired":
                        eligible = expired and (not attention or acknowledged)
                        category = "expired"
                    elif cleanup == "completed_and_expired":
                        if status == TaskState.COMPLETED.value and not attention:
                            eligible = True
                            category = "completed"
                        elif status == TaskState.CANCELLED.value:
                            eligible = True
                            category = "cancelled"
                        elif expired and attention and acknowledged:
                            eligible = True
                            category = "expired"
                    elif cleanup == "resolved_alerts":
                        eligible = attention and acknowledged
                        category = "alerts"
                    elif cleanup == "all_history":
                        eligible = not attention or acknowledged
                        category = "alerts" if attention else (
                            "cancelled"
                            if status == TaskState.CANCELLED.value
                            else "completed"
                        )
                    if not eligible:
                        if attention and not acknowledged and (
                            cleanup in {"resolved_alerts", "all_history"}
                            or (cleanup in {"expired", "completed_and_expired"} and expired)
                        ):
                            skipped_unacknowledged += 1
                        continue
                    matched_ids.append(str(row["task_id"]))
                    counts[category] += 1
                if not dry_run and matched_ids:
                    for start in range(0, len(matched_ids), 500):
                        chunk = matched_ids[start : start + 500]
                        conn.execute(
                            f"""
                            UPDATE task_snapshots
                            SET dismissed_at = ?, dismissed_by = ?, dismiss_reason = ?
                            WHERE dismissed_at = ''
                              AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                              AND task_id IN ({','.join('?' for _ in chunk)})
                            """,
                            (
                                timestamp,
                                str(dismissed_by or "local-user"),
                                cleanup,
                                *chunk,
                            ),
                        )
                conn.commit()

        run_sqlite_with_retry(operation)
        return {
            "matched": len(matched_ids),
            "dismissed": 0 if dry_run else len(matched_ids),
            "skipped_active": skipped_active,
            "skipped_unacknowledged": skipped_unacknowledged,
            "artifacts_deleted": 0,
            "task_ids": [] if dry_run else matched_ids,
            "counts": counts,
        }

    def delete_task_owned_rows(
        self,
        task_ids: Collection[str],
        *,
        reason: str = "explicit_task_cleanup",
    ) -> dict[str, object]:
        """Delete explicitly approved task-owned rows in one repository transaction.

        The caller owns the business/reference decision.  This method owns the
        SQLite mutation boundary and rechecks that every candidate is still a
        terminal task before deleting its events, result metadata and snapshot.
        It never touches Online MR, Ground, history or artifact files.
        """

        normalized = list(dict.fromkeys(str(task_id).strip() for task_id in task_ids if str(task_id).strip()))
        deleted = {"task_events": 0, "task_snapshots": 0, "task_results": 0}
        deleted_ids: list[str] = []
        orphan_blobs_removed = 0
        orphan_blob_bytes_removed = 0
        quick_check = "not_run"

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if normalized and "task_snapshots" in tables:
                placeholders = ",".join("?" for _ in normalized)
                rows = conn.execute(
                    f"SELECT task_id, status FROM task_snapshots WHERE task_id IN ({placeholders})",
                    normalized,
                ).fetchall()
                deleted_ids = [
                    str(row[0])
                    for row in rows
                    if str(row[1] or "").upper() in TERMINAL_TASK_STATE_VALUES
                ]
                for start in range(0, len(deleted_ids), 500):
                    chunk = deleted_ids[start : start + 500]
                    chunk_placeholders = ",".join("?" for _ in chunk)
                    if "task_events" in tables:
                        cursor = conn.execute(
                            f"DELETE FROM task_events WHERE task_id IN ({chunk_placeholders})",
                            chunk,
                        )
                        deleted["task_events"] += max(0, int(cursor.rowcount))
                    if "task_results" in tables:
                        cursor = conn.execute(
                            f"DELETE FROM task_results WHERE task_id IN ({chunk_placeholders})",
                            chunk,
                        )
                        deleted["task_results"] += max(0, int(cursor.rowcount))
                    cursor = conn.execute(
                        f"DELETE FROM task_snapshots WHERE task_id IN ({chunk_placeholders})",
                        chunk,
                    )
                    deleted["task_snapshots"] += max(0, int(cursor.rowcount))
                    if "task_retention_tombstones" in tables:
                        conn.executemany(
                            "INSERT OR IGNORE INTO task_retention_tombstones"
                            "(task_id, retired_at, reason) VALUES (?, ?, ?)",
                            [(task_id, utc_now_iso(), reason) for task_id in chunk],
                        )
            if "task_result_blobs" in tables and "task_results" in tables:
                orphan_rows = conn.execute(
                    "SELECT content_sha256, compressed_bytes FROM task_result_blobs "
                    "WHERE NOT EXISTS (SELECT 1 FROM task_results "
                    "WHERE blob_ready=1 AND content_sha256=task_result_blobs.content_sha256)"
                ).fetchall()
                if orphan_rows:
                    conn.executemany(
                        "DELETE FROM task_result_blobs WHERE content_sha256=?",
                        [(str(row[0]),) for row in orphan_rows],
                    )
                    orphan_blobs_removed = len(orphan_rows)
                    orphan_blob_bytes_removed = sum(
                        int(row[1] or 0) for row in orphan_rows
                    )
            conn.commit()
            quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])

        return {
            "deleted_task_ids": deleted_ids,
            "deleted": deleted,
            "orphan_blobs_removed": orphan_blobs_removed,
            "orphan_blob_bytes_removed": orphan_blob_bytes_removed,
            "quick_check": quick_check,
        }

    def read_task_cleanup_context(self, task_id: str) -> dict[str, object] | None:
        """Read the repository-owned facts needed for a cleanup decision.

        The cleanup service may inspect Ground and Artifact authorities, but it
        must not open or query ``tasks.db`` itself.  Keeping this projection in
        the repository also makes Blob-first result verification identical for
        Task Center, maintenance and cleanup callers.
        """

        normalized = str(task_id or "").strip()
        if not normalized:
            return None
        with self._connect() as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "task_snapshots" not in tables:
                return None
            raw = conn.execute(
                "SELECT * FROM task_snapshots WHERE task_id=?", (normalized,)
            ).fetchone()
            if raw is None:
                return None
            row = dict(raw)
            online_mapping = False
            if "online_mr_task_sessions" in tables:
                online_mapping = (
                    conn.execute(
                        "SELECT 1 FROM online_mr_task_sessions "
                        "WHERE controller_task_id=? LIMIT 1",
                        (normalized,),
                    ).fetchone()
                    is not None
                )

            result: dict[str, object] | None = None
            result_valid = True
            result_id = str(row.get("result_id") or "")
            if result_id:
                authority = (
                    conn.execute(
                        "SELECT * FROM task_results WHERE result_id=?", (result_id,)
                    ).fetchone()
                    if "task_results" in tables
                    else None
                )
                if authority is None:
                    result_valid = False
                else:
                    try:
                        result = self._verified_result_for_read(
                            dict(authority), conn=conn
                        ).get("result")
                    except (sqlite3.DatabaseError, TaskResultBlobError):
                        result_valid = False
            else:
                try:
                    parsed = json.loads(str(row.get("result_json") or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                    result_valid = False
                if isinstance(parsed, dict):
                    result = dict(parsed)
                elif parsed is not None:
                    result_valid = False

            event_rows = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM task_events WHERE task_id=?",
                        (normalized,),
                    ).fetchone()[0]
                )
                if "task_events" in tables
                else 0
            )
            result_rows = 0
            result_bytes = 0
            if "task_results" in tables:
                result_count = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) "
                    "FROM task_results WHERE task_id=?",
                    (normalized,),
                ).fetchone()
                result_rows = int(result_count[0])
                result_bytes = int(result_count[1])
            return {
                "snapshot": row,
                "online_mapping": online_mapping,
                "result": result,
                "result_valid": result_valid,
                "event_rows": event_rows,
                "result_rows": result_rows,
                "result_bytes": result_bytes,
            }

    def enforce_terminal_history_retention(self) -> dict[str, object]:
        """Keep recent ordinary terminal tasks and remove only safe DB rows atomically.

        This compatibility entrypoint remains repository-owned.  It neither
        archives to ``TaskHistoryStore`` nor touches artifact files, Ground
        data, Online MR mappings or external raw evidence.
        """

        deleted = {"task_snapshots": 0, "task_events": 0, "task_results": 0}
        protected = {
            "active": 0,
            "online_mr_mapping": 0,
            "long_term_reference": 0,
            "unreadable_metadata": 0,
        }
        result: dict[str, object] = {
            "limit_per_scope": TASK_HISTORY_SCOPE_LIMIT,
            "scopes": 0,
            "retained_terminal": 0,
            "deleted_task_ids": [],
            "deleted": deleted,
            "protected": protected,
        }

        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                tables = {
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "task_snapshots" not in tables:
                    conn.rollback()
                    return
                online_mr_task_ids = self._online_mr_mapped_task_ids(conn, tables)
                result_authority_by_id = self._task_result_authority_by_id(conn, tables)
                rows = conn.execute(
                    "SELECT task_id, task_type, site_name, status, finished_time, "
                    "updated_time, result_json, result_id, result_summary_json, "
                    "resource_keys_json FROM task_snapshots ORDER BY site_name, "
                    "task_type, finished_time DESC, updated_time DESC, task_id DESC"
                ).fetchall()
                ordinary_by_scope: dict[tuple[str, str], list[tuple[str, str]]] = {}
                for raw in rows:
                    row = dict(raw)
                    protection = self._terminal_retention_protection(
                        row, online_mr_task_ids, result_authority_by_id
                    )
                    if protection:
                        protected[protection] += 1
                        continue
                    if str(row["status"] or "").upper() not in TERMINAL_TASK_STATE_VALUES:
                        continue
                    scope = task_history_scope(row["site_name"], row["task_type"])
                    timestamp = str(row["finished_time"] or row["updated_time"] or "")
                    ordinary_by_scope.setdefault(scope, []).append((timestamp, str(row["task_id"])))
                result["scopes"] = len(ordinary_by_scope)
                retained_task_ids: set[str] = set()
                delete_ids: list[str] = []
                for candidates in ordinary_by_scope.values():
                    ordered = [task_id for _stamp, task_id in sorted(candidates, reverse=True)]
                    retained_task_ids.update(ordered[:TASK_HISTORY_SCOPE_LIMIT])
                    delete_ids.extend(ordered[TASK_HISTORY_SCOPE_LIMIT:])
                result["retained_terminal"] = len(retained_task_ids)
                if not delete_ids:
                    conn.commit()
                    return
                retired_at = utc_now_iso()
                conn.executemany(
                    "INSERT OR IGNORE INTO task_retention_tombstones"
                    "(task_id, retired_at, reason) VALUES (?, ?, ?)",
                    [(task_id, retired_at, "terminal_history_retention") for task_id in delete_ids],
                )
                for start in range(0, len(delete_ids), 500):
                    chunk = delete_ids[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    for table, key in (
                        ("task_results", "task_results"),
                        ("task_events", "task_events"),
                        ("task_snapshots", "task_snapshots"),
                    ):
                        if table not in tables:
                            continue
                        cursor = conn.execute(
                            f"DELETE FROM {table} WHERE task_id IN ({placeholders})",
                            chunk,
                        )
                        deleted[key] += max(0, int(cursor.rowcount))
                result["deleted_task_ids"] = delete_ids
                conn.commit()

        run_sqlite_with_retry(operation)
        return result

    @classmethod
    def _online_mr_mapped_task_ids(cls, conn, tables: set[str]) -> set[str]:
        if "online_mr_task_sessions" not in tables:
            return set()
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(online_mr_task_sessions)"
            ).fetchall()
        }
        task_column = next(
            (
                column
                for column in ("controller_task_id", "task_id")
                if column in columns
            ),
            "",
        )
        if not task_column:
            return set()
        rows = conn.execute(
            f"SELECT \"{task_column}\" AS task_id FROM online_mr_task_sessions "
            f"WHERE \"{task_column}\" IS NOT NULL AND \"{task_column}\" <> ''"
        ).fetchall()
        return {str(row["task_id"]) for row in rows}

    @classmethod
    def _task_result_authority_by_id(
        cls, conn, tables: set[str]
    ) -> dict[str, dict[str, object] | None]:
        if "task_results" not in tables:
            return {}
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(task_results)").fetchall()
        }
        required = {
            "result_id",
            "task_id",
            "terminal_event_type",
            "canonical_json",
            "sha256",
            "byte_size",
            "schema_version",
            "created_time",
        }
        if not required.issubset(columns):
            return {}
        blob_columns = ""
        if {"content_sha256", "blob_codec", "blob_ready"}.issubset(columns):
            blob_columns = ", content_sha256, blob_codec, blob_ready"
        rows = conn.execute(
            "SELECT result_id, task_id, terminal_event_type, canonical_json, "
            "sha256, byte_size, schema_version, created_time"
            f"{blob_columns} FROM task_results"
        ).fetchall()
        authority: dict[str, dict[str, object] | None] = {}
        for raw in rows:
            row = dict(raw)
            result_id = str(row.get("result_id") or "")
            if not result_id:
                continue
            try:
                if int(row.get("blob_ready") or 0):
                    row["canonical_json"] = read_blob(
                        conn,
                        content_sha256=str(
                            row.get("content_sha256") or row.get("sha256") or ""
                        ),
                        expected_bytes=int(row.get("byte_size") or -1),
                    )
                authority[result_id] = verify_task_result_row(row)
            except (sqlite3.DatabaseError, TaskResultBlobError):
                authority[result_id] = None
        return authority

    @classmethod
    def _terminal_retention_protection(
        cls,
        row: dict[str, object],
        online_mr_task_ids: set[str],
        result_authority_by_id: dict[str, dict[str, object] | None],
    ) -> str:
        status = str(row.get("status") or "").upper()
        if status in ACTIVE_TASK_STATE_VALUES:
            return "active"
        if str(row.get("task_id") or "") in online_mr_task_ids:
            return "online_mr_mapping"
        if status in TERMINAL_TASK_STATE_VALUES and cls._event_datetime(
            str(row.get("finished_time") or row.get("updated_time") or "")
        ) is None:
            return "unreadable_metadata"
        resource_keys, resource_keys_valid = cls._retention_json_list(
            row.get("resource_keys_json")
        )
        task_result, result_valid = cls._retention_json_object(
            row.get("result_json")
        )
        result_summary, summary_valid = cls._retention_json_object(
            row.get("result_summary_json")
        )
        if not resource_keys_valid or not result_valid or not summary_valid:
            return "unreadable_metadata"
        result_id = str(row.get("result_id") or "")
        authority_result: dict[str, object] = {}
        if result_id:
            raw_authority = result_authority_by_id.get(result_id)
            if raw_authority is None:
                return "unreadable_metadata"
            else:
                if str(raw_authority.get("task_id") or "") != str(
                    row.get("task_id") or ""
                ):
                    return "unreadable_metadata"
                authority_result = dict(raw_authority.get("result") or {})
        if task_has_long_term_reference(
            resource_keys=resource_keys,
            result={**authority_result, **result_summary, **task_result},
        ):
            return "long_term_reference"
        return ""

    @staticmethod
    def _retention_json_list(value: object) -> tuple[list[object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return [], True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return [], False
        return (list(parsed), True) if isinstance(parsed, list) else ([], False)

    @staticmethod
    def _retention_json_object(value: object) -> tuple[dict[str, object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return {}, True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}, False
        return (dict(parsed), True) if isinstance(parsed, dict) else ({}, False)

    def visible_attention_summary(self) -> dict[str, int]:
        summary = {"running": 0, "queued": 0, "failed": 0, "warning": 0}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, error_message, result_json, acknowledged_at
                       , result_summary_json
                FROM task_snapshots
                WHERE dismissed_at = ''
                """
            ).fetchall()
            for row in rows:
                status = str(row["status"]).upper()
                if status == TaskState.PENDING.value:
                    summary["queued"] += 1
                elif status in {
                    TaskState.STARTING.value,
                    TaskState.RUNNING.value,
                    TaskState.STOPPING.value,
                }:
                    summary["running"] += 1
                if str(row["acknowledged_at"] or ""):
                    continue
                result = self._policy_result(conn, row)
                if status == TaskState.FAILED.value:
                    summary["failed"] += 1
                elif task_requires_attention(
                    status,
                    error_message=str(row["error_message"] or ""),
                    result=result,
                ):
                    summary["warning"] += 1
        return summary

    def list_events(
        self, task_id: str, *, after_sequence: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        safe_after = max(0, int(after_sequence))
        safe_limit = max(1, min(int(limit), 2000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sequence, event_id, task_id, event_type, event_time, source, payload_json
                FROM task_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (task_id, safe_after, safe_limit),
            ).fetchall()
            current = [self._event_from_connection_row(conn, dict(row)) for row in rows]
            archived_rows = self.task_history.list_events(
                task_id, after_sequence=safe_after, limit=safe_limit
            )
            archived = [
                self._event_from_connection_row(conn, row) for row in archived_rows
            ]
        merged = {str(event["id"]): event for event in (*archived, *current)}
        return sorted(
            merged.values(), key=lambda event: (int(event["sequence"]), str(event["id"]))
        )[:safe_limit]

    def list_events_for_tasks(
        self,
        task_ids: Collection[str],
        *,
        event_types: Collection[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """批量读取指定任务事件，避免任务列表逐条查询事件。"""

        ids = sorted(
            {str(task_id).strip() for task_id in task_ids if str(task_id).strip()}
        )
        if not ids:
            return {}
        grouped = {task_id: [] for task_id in ids}
        types = sorted(
            {
                str(event_type).strip()
                for event_type in (event_types or ())
                if str(event_type).strip()
            }
        )
        with self._connect() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                clauses = [f"task_id IN ({','.join('?' for _ in chunk)})"]
                params: list[object] = list(chunk)
                if types:
                    clauses.append(f"event_type IN ({','.join('?' for _ in types)})")
                    params.extend(types)
                rows = conn.execute(
                    "SELECT sequence, event_id, task_id, event_type, event_time, source, payload_json "
                    f"FROM task_events WHERE {' AND '.join(clauses)} ORDER BY sequence ASC",
                    params,
                ).fetchall()
                for row in rows:
                    event = self._event_from_connection_row(conn, dict(row))
                    grouped.setdefault(str(event["task_id"]), []).append(event)
            archived_by_task = self.task_history.list_events_for_tasks(
                ids,
                event_types=types,
            )
            for task_id in ids:
                for row in archived_by_task.get(task_id, []):
                    event = self._event_from_connection_row(conn, row)
                    grouped.setdefault(task_id, []).append(event)
                deduplicated = {
                    str(event["id"]): event for event in grouped.get(task_id, [])
                }
                grouped[task_id] = sorted(
                    deduplicated.values(),
                    key=lambda event: (int(event["sequence"]), str(event["id"])),
                )
        return grouped

    def list_all_events(
        self, *, after_sequence: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sequence, event_id, task_id, event_type, event_time, source, payload_json
                FROM task_events
                WHERE sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (max(0, int(after_sequence)), max(1, min(int(limit), 2000))),
            ).fetchall()
            return [self._event_from_connection_row(conn, dict(row)) for row in rows]

    def last_event_sequence(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sequence), 0) AS value FROM task_events").fetchone()
        return int(row["value"] if row is not None else 0)

    def reconcile_orphaned_local_tasks(
        self,
        is_process_alive,
        is_locally_hosted=None,
    ) -> list[TaskSnapshot]:
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        changed: list[TaskSnapshot] = []
        for snapshot in self.list(statuses=active, limit=1000):
            if snapshot.source != "local":
                continue
            hosted = bool(is_locally_hosted and is_locally_hosted(snapshot.task_id))
            process_alive = snapshot.owner_pid > 0 and is_process_alive(snapshot.owner_pid)
            if hosted or process_alive or (snapshot.owner_pid <= 0 and is_locally_hosted is None):
                continue
            now = utc_now_iso()
            form_connection_test = snapshot.task_id.startswith("device-form-test-")
            export_runtime_lost = snapshot.task_type.startswith(
                ("web_export_", "device_export_")
            )
            message = (
                "临时表单连接测试不可恢复"
                if form_connection_test
                else (
                    "导出任务执行进程已丢失，请重新导出"
                    if export_runtime_lost
                    else "任务宿主已退出"
                )
            )
            error_message = (
                "上次运行非正常中断，一次性表单凭据已失效，请重新提交测试"
                if form_connection_test
                else (
                    "导出任务执行进程已丢失，请重新导出"
                    if export_runtime_lost
                    else "上次运行非正常中断，未发现仍存活的本地任务宿主"
                )
            )
            updated = TaskSnapshot(
                **{
                    **asdict(snapshot),
                    "status": TaskState.FAILED,
                    "finished_time": now,
                    "updated_time": now,
                    "message": message,
                    "error_message": error_message,
                    "result": {
                        **dict(snapshot.result or {}),
                        **(
                            {"error_code": "WORKER_RUNTIME_LOST"}
                            if export_runtime_lost
                            else {}
                        ),
                    },
                }
            )
            event = TaskEvent(
                event_id=f"recovery-{snapshot.task_id}-{now}",
                task_id=snapshot.task_id,
                type="error",
                time=now,
                source="recovery",
                payload={
                    "message": updated.message,
                    "error": updated.error_message,
                    "cancelled": False,
                },
            )
            if self.record(updated, event, allowed_from={snapshot.status}):
                changed.append(updated)
        return changed

    @staticmethod
    def _task_result_rollout_status_from_connection(
        conn,
    ) -> TaskResultRolloutStatus:
        row = conn.execute(
            """
            SELECT state, revision, updated_at, updated_by, reason, schema_version
            FROM task_result_storage_rollout
            WHERE singleton_id = 1
            """
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("task result storage rollout state is missing")
        try:
            state = TaskResultStorageState(str(row["state"]))
        except ValueError as exc:
            raise sqlite3.DatabaseError(
                "task result storage rollout state is invalid"
            ) from exc
        return TaskResultRolloutStatus(
            state=state,
            revision=int(row["revision"]),
            updated_at=str(row["updated_at"]),
            updated_by=str(row["updated_by"]),
            reason=str(row["reason"]),
            schema_version=int(row["schema_version"]),
        )

    @classmethod
    def _ensure_schema_compat(cls, conn) -> None:
        result_columns = {
            "content_sha256": "TEXT NOT NULL DEFAULT ''",
            "blob_codec": "TEXT NOT NULL DEFAULT ''",
            "blob_ready": "INTEGER NOT NULL DEFAULT 0 CHECK(blob_ready IN (0, 1))",
        }
        for column, definition in result_columns.items():
            if not cls._column_exists(conn, "task_results", column):
                conn.execute(
                    f"ALTER TABLE task_results ADD COLUMN {column} {definition}"
                )
        # Older databases already have the unconditional immutable trigger.
        # Recreate it so the migration may fill blob metadata exactly once while
        # keeping the canonical authority row immutable thereafter.
        conn.execute("DROP TRIGGER IF EXISTS trg_task_results_immutable")
        conn.execute(
            """
            CREATE TRIGGER trg_task_results_immutable
            BEFORE UPDATE ON task_results
            WHEN NOT (
                OLD.result_id = NEW.result_id
                AND OLD.task_id = NEW.task_id
                AND OLD.terminal_event_type = NEW.terminal_event_type
                AND OLD.canonical_json = NEW.canonical_json
                AND OLD.sha256 = NEW.sha256
                AND OLD.byte_size = NEW.byte_size
                AND OLD.schema_version = NEW.schema_version
                AND OLD.created_time = NEW.created_time
                AND (
                    (OLD.content_sha256 = NEW.content_sha256
                     AND OLD.blob_codec = NEW.blob_codec
                     AND OLD.blob_ready = NEW.blob_ready)
                    OR (OLD.blob_ready = 0
                        AND NEW.blob_ready = 1
                        AND NEW.content_sha256 = OLD.sha256
                        AND NEW.blob_codec = 'zlib')
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'task_results rows are immutable');
            END;
            """
        )
        columns = {
            "resource_keys_json": "TEXT NOT NULL DEFAULT '[]'",
            "result_id": "TEXT NOT NULL DEFAULT ''",
            "result_hash": "TEXT NOT NULL DEFAULT ''",
            "result_summary_json": "TEXT NOT NULL DEFAULT '{}'",
            "text_integrity": "TEXT NOT NULL DEFAULT ''",
            "text_integrity_reason": "TEXT NOT NULL DEFAULT ''",
            "text_integrity_updated_at": "TEXT NOT NULL DEFAULT ''",
            "text_schema_version": "INTEGER NOT NULL DEFAULT 1",
            "producer_kind": "TEXT NOT NULL DEFAULT 'legacy'",
            "producer_version": "TEXT NOT NULL DEFAULT 'unknown'",
            "producer_commit": "TEXT NOT NULL DEFAULT 'unknown'",
            "expires_at": "TEXT NOT NULL DEFAULT ''",
            "acknowledged_at": "TEXT NOT NULL DEFAULT ''",
            "dismissed_at": "TEXT NOT NULL DEFAULT ''",
            "dismissed_by": "TEXT NOT NULL DEFAULT ''",
            "dismiss_reason": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in columns.items():
            if not cls._column_exists(conn, "task_snapshots", column):
                conn.execute(
                    f"ALTER TABLE task_snapshots ADD COLUMN {column} {definition}"
                )
        cls._migrate_legacy_text_integrity(conn)
        cls._backfill_task_expiration(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_snapshots_visible_updated "
            "ON task_snapshots(dismissed_at, updated_time DESC)"
        )
        conn.execute(
            "INSERT INTO task_schema_meta(key, value) VALUES ('schema_version', '5') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        conn.execute(
            "UPDATE task_result_storage_rollout SET schema_version = 5 WHERE singleton_id = 1"
        )

    @classmethod
    def _backfill_task_expiration(cls, conn) -> None:
        rows = conn.execute(
            """
            SELECT task_id, status, finished_time, updated_time, error_message, result_json
            FROM task_snapshots
            WHERE expires_at = ''
              AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
            """
        ).fetchall()
        for row in rows:
            expires_at = task_expires_at(
                str(row["status"]),
                finished_time=str(row["finished_time"] or ""),
                updated_time=str(row["updated_time"] or ""),
                error_message=str(row["error_message"] or ""),
                result=cls._json_object(row["result_json"]),
            )
            if expires_at:
                conn.execute(
                    "UPDATE task_snapshots SET expires_at = ? WHERE task_id = ?",
                    (expires_at, str(row["task_id"])),
                )

    @classmethod
    def _migrate_legacy_text_integrity(cls, conn) -> None:
        rows = conn.execute(
            """
            SELECT task_id, task_name, message, error_message, result_json,
                   created_time, updated_time
            FROM task_snapshots
            WHERE text_integrity = ''
            """
        ).fetchall()
        if not rows:
            return
        task_ids = {str(row["task_id"]) for row in rows}
        corrupted_events: set[str] = set()
        for start in range(0, len(task_ids), 500):
            chunk = sorted(task_ids)[start : start + 500]
            matches = conn.execute(
                "SELECT DISTINCT task_id FROM task_events "
                f"WHERE task_id IN ({','.join('?' for _ in chunk)}) "
                "AND instr(payload_json, ?) > 0",
                (*chunk, "\ufffd"),
            ).fetchall()
            corrupted_events.update(str(row["task_id"]) for row in matches)
        for row in rows:
            task_id = str(row["task_id"])
            result = cls._json_object(row["result_json"])
            explicit = str(result.get("text_integrity") or "")
            if explicit in TEXT_INTEGRITY_VALUES and explicit != "ok":
                integrity = explicit
                reason = str(
                    result.get("text_integrity_reason")
                    or "legacy_explicit_text_integrity"
                )
            elif task_id in corrupted_events or _contains_replacement_character(
                {
                    "task_name": row["task_name"],
                    "message": row["message"],
                    "error_message": row["error_message"],
                    "result": result,
                }
            ):
                integrity = "historical_corrupted"
                reason = "legacy_task_before_text_schema_v2"
            else:
                integrity = "ok"
                reason = ""
            conn.execute(
                """
                UPDATE task_snapshots
                SET text_integrity = ?, text_integrity_reason = ?,
                    text_integrity_updated_at = ?, text_schema_version = 1,
                    producer_kind = 'legacy', producer_version = 'unknown',
                    producer_commit = 'unknown'
                WHERE task_id = ? AND text_integrity = ''
                """,
                (
                    integrity,
                    reason,
                    str(row["updated_time"] or row["created_time"] or ""),
                    task_id,
                ),
            )

    @staticmethod
    def _column_exists(conn, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        for row in rows:
            name = row["name"] if hasattr(row, "keys") and "name" in row.keys() else row[1]
            if str(name) == column:
                return True
        return False

    @staticmethod
    def _upsert(
        conn,
        snapshot: TaskSnapshot,
        *,
        allowed_from: Collection[TaskState] | None = None,
    ) -> bool:
        allowed_values = (
            None
            if allowed_from is None
            else sorted(state.value for state in allowed_from)
        )
        if allowed_values is None:
            transition_guard = ""
        elif allowed_values:
            transition_guard = f"WHERE task_snapshots.status IN ({','.join('?' for _ in allowed_values)})"
        else:
            transition_guard = "WHERE 0"
        cursor = conn.execute(
            f"""
            INSERT INTO task_snapshots (
                task_id, task_type, task_name, created_time, started_time, finished_time,
                status, progress, stage, current, total, message, owner, device, agent,
                result_path, error_message, result_json, source, site_name, owner_pid,
                result_id, result_hash, result_summary_json,
                resource_keys_json, text_integrity, text_integrity_reason,
                text_integrity_updated_at, text_schema_version, producer_kind,
                producer_version, producer_commit, expires_at, acknowledged_at,
                dismissed_at, dismissed_by, dismiss_reason, updated_time
            ) VALUES ({", ".join("?" for _ in range(38))})
            ON CONFLICT(task_id) DO UPDATE SET
                task_type=excluded.task_type,
                task_name=excluded.task_name,
                started_time=excluded.started_time,
                finished_time=excluded.finished_time,
                status=excluded.status,
                progress=excluded.progress,
                stage=excluded.stage,
                current=excluded.current,
                total=excluded.total,
                message=excluded.message,
                owner=excluded.owner,
                device=excluded.device,
                agent=excluded.agent,
                result_path=excluded.result_path,
                error_message=excluded.error_message,
                result_json=CASE
                    WHEN excluded.result_id <> '' THEN excluded.result_json
                    WHEN excluded.result_json NOT IN ('', '{{}}', 'null')
                        THEN excluded.result_json
                    WHEN task_snapshots.result_id <> '' THEN task_snapshots.result_json
                    ELSE excluded.result_json
                END,
                result_id=CASE
                    WHEN excluded.result_id <> '' THEN excluded.result_id
                    WHEN excluded.result_json NOT IN ('', '{{}}', 'null') THEN ''
                    ELSE task_snapshots.result_id
                END,
                result_hash=CASE
                    WHEN excluded.result_hash <> '' THEN excluded.result_hash
                    WHEN excluded.result_json NOT IN ('', '{{}}', 'null') THEN ''
                    ELSE task_snapshots.result_hash
                END,
                result_summary_json=CASE
                    WHEN excluded.result_id <> '' THEN excluded.result_summary_json
                    WHEN excluded.result_json NOT IN ('', '{{}}', 'null') THEN '{{}}'
                    ELSE task_snapshots.result_summary_json
                END,
                source=excluded.source,
                site_name=excluded.site_name,
                owner_pid=excluded.owner_pid,
                resource_keys_json=excluded.resource_keys_json,
                text_integrity=excluded.text_integrity,
                text_integrity_reason=excluded.text_integrity_reason,
                text_integrity_updated_at=excluded.text_integrity_updated_at,
                text_schema_version=excluded.text_schema_version,
                producer_kind=excluded.producer_kind,
                producer_version=excluded.producer_version,
                producer_commit=excluded.producer_commit,
                expires_at=CASE
                    WHEN task_snapshots.expires_at <> '' THEN task_snapshots.expires_at
                    ELSE excluded.expires_at
                END,
                updated_time=excluded.updated_time
            {transition_guard}
            """,
            (
                snapshot.task_id,
                snapshot.task_type,
                snapshot.task_name,
                snapshot.created_time,
                snapshot.started_time,
                snapshot.finished_time,
                snapshot.status.value,
                max(0, min(int(snapshot.progress), 100)),
                snapshot.stage,
                int(snapshot.current),
                int(snapshot.total),
                snapshot.message,
                snapshot.owner,
                snapshot.device,
                snapshot.agent,
                snapshot.result_path,
                snapshot.error_message,
                json.dumps(snapshot.result, ensure_ascii=False, separators=(",", ":")),
                snapshot.source,
                snapshot.site_name,
                int(snapshot.owner_pid),
                snapshot.result_id,
                snapshot.result_hash,
                json.dumps(
                    snapshot.result_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    list(snapshot.resource_keys or []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                snapshot.text_integrity
                if snapshot.text_integrity in TEXT_INTEGRITY_VALUES
                else "unknown_corrupted",
                snapshot.text_integrity_reason,
                snapshot.text_integrity_updated_at,
                int(snapshot.text_schema_version),
                snapshot.producer_kind,
                snapshot.producer_version,
                snapshot.producer_commit,
                snapshot.expires_at
                or task_expires_at(
                    snapshot.status,
                    finished_time=snapshot.finished_time,
                    updated_time=snapshot.updated_time,
                    error_message=snapshot.error_message,
                    result=snapshot.result or snapshot.result_summary,
                ),
                snapshot.acknowledged_at,
                snapshot.dismissed_at,
                snapshot.dismissed_by,
                snapshot.dismiss_reason,
                snapshot.updated_time,
                *(allowed_values or ()),
            ),
        )
        return cursor.rowcount > 0

    def _snapshot_from_connection_row(
        self, conn, row: dict[str, object]
    ) -> TaskSnapshot:
        result_id = str(row.get("result_id") or "")
        if result_id:
            result = self._result_row(conn, result_id)
            if result is None:
                raise sqlite3.DatabaseError("task snapshot result reference is missing")
            verified = self._verified_result_for_read(dict(result), conn=conn)
            if str(verified["task_id"]) != str(row["task_id"]):
                raise sqlite3.DatabaseError("task snapshot result task binding mismatch")
            if str(row.get("result_hash") or "") not in {"", str(verified["sha256"])}:
                raise sqlite3.DatabaseError("task snapshot result hash mismatch")
            legacy_result_json = str(row.get("result_json") or "").strip()
            if legacy_result_json in {"", "{}", "null"}:
                row["result_json"] = str(verified["canonical_json"])
            elif (
                self._canonical_result_json(self._json_object(legacy_result_json))
                != str(verified["canonical_json"])
            ):
                raise sqlite3.DatabaseError(
                    "task snapshot full result does not match result reference"
                )
            row["result_hash"] = str(verified["sha256"])
            if not self._json_object(row.get("result_summary_json")):
                row["result_summary_json"] = json.dumps(
                    self._result_summary(
                        dict(verified["result"]),
                        byte_size=int(verified["byte_size"]),
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
        return self._snapshot_from_row(row)

    def _policy_result(
        self, conn: sqlite3.Connection, row: sqlite3.Row | dict[str, object]
    ) -> dict[str, Any]:
        """Return bounded task-policy metadata, with authority as a fallback.

        Terminal snapshots intentionally keep ``result_json`` empty after the
        Blob migration. Cleanup and attention policy still needs business
        outcome fields, so use the compact summary first and consult the
        immutable authority only for legacy rows whose summary is unavailable.
        """

        values = dict(row)
        summary = self._json_object(values.get("result_summary_json"))
        legacy = self._json_object(values.get("result_json"))
        result_id = str(values.get("result_id") or "")
        if result_id and not summary:
            try:
                authority = self._result_row(conn, result_id)
                if authority is not None:
                    verified = self._verified_result_for_read(
                        dict(authority), conn=conn
                    )
                    return {**legacy, **dict(verified.get("result") or {})}
            except (sqlite3.DatabaseError, TaskResultBlobError):
                # A broken authority must not make a failed task look healthy;
                # callers still retain lifecycle status/error metadata.
                pass
        return {**legacy, **summary}

    @classmethod
    def _snapshot_from_row(cls, row: dict[str, object]) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=str(row["task_id"]),
            task_type=str(row["task_type"]),
            task_name=str(row["task_name"]),
            created_time=str(row["created_time"]),
            started_time=str(row.get("started_time") or ""),
            finished_time=str(row.get("finished_time") or ""),
            status=TaskState(str(row["status"])),
            progress=int(row.get("progress") or 0),
            stage=str(row.get("stage") or ""),
            current=int(row.get("current") or 0),
            total=int(row.get("total") or 0),
            message=str(row.get("message") or ""),
            owner=str(row.get("owner") or ""),
            device=str(row.get("device") or ""),
            agent=str(row.get("agent") or ""),
            result_path=str(row.get("result_path") or ""),
            error_message=str(row.get("error_message") or ""),
            result=cls._json_object(row.get("result_json")),
            result_id=str(row.get("result_id") or ""),
            result_hash=str(row.get("result_hash") or ""),
            result_summary=cls._json_object(row.get("result_summary_json")),
            source=str(row.get("source") or "local"),
            site_name=str(row.get("site_name") or "demo"),
            owner_pid=int(row.get("owner_pid") or 0),
            resource_keys=cls._json_list(row.get("resource_keys_json")),
            text_integrity=str(row.get("text_integrity") or "ok"),
            text_integrity_reason=str(row.get("text_integrity_reason") or ""),
            text_integrity_updated_at=str(row.get("text_integrity_updated_at") or ""),
            text_schema_version=int(
                row.get("text_schema_version")
                if row.get("text_schema_version") is not None
                else 1
            ),
            producer_kind=str(row.get("producer_kind") or "legacy"),
            producer_version=str(row.get("producer_version") or "unknown"),
            producer_commit=str(row.get("producer_commit") or "unknown"),
            expires_at=str(row.get("expires_at") or ""),
            acknowledged_at=str(row.get("acknowledged_at") or ""),
            dismissed_at=str(row.get("dismissed_at") or ""),
            dismissed_by=str(row.get("dismissed_by") or ""),
            dismiss_reason=str(row.get("dismiss_reason") or ""),
            updated_time=str(row["updated_time"]),
        )

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item or "").strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed]
        return []

    @staticmethod
    def _terminal_event_type_for_status(status: object) -> str:
        try:
            normalized = status.value
        except AttributeError:
            normalized = str(status)
        return {
            TaskState.COMPLETED.value: "finished",
            TaskState.FAILED.value: "error",
            TaskState.CANCELLED.value: "cancelled",
        }.get(str(normalized).upper(), "")

    @staticmethod
    def _resource_key_set(values: Collection[str]) -> set[str]:
        return {str(value or "").strip() for value in values if str(value or "").strip()}

    @classmethod
    def _event_from_row(cls, values: dict[str, object]) -> dict[str, Any]:
        return {
            "sequence": int(values["sequence"]),
            "id": str(values["event_id"]),
            "task_id": str(values["task_id"]),
            "type": str(values["event_type"]),
            "time": str(values["event_time"]),
            "source": str(values["source"]),
            "payload": cls._json_object(values.get("payload_json")),
        }

    def _event_from_connection_row(
        self, conn, values: dict[str, object]
    ) -> dict[str, Any]:
        event = self._event_from_row(values)
        payload = dict(event["payload"])
        result_id = str(payload.get("result_id") or "")
        if result_id:
            row = self._result_row(conn, result_id)
            if row is None:
                raise sqlite3.DatabaseError("task event result reference is missing")
            verified = self._verified_result_for_read(dict(row), conn=conn)
            if str(verified["task_id"]) != str(event["task_id"]):
                raise sqlite3.DatabaseError("task event result task binding mismatch")
            if str(verified["terminal_event_type"]) != str(event["type"]):
                raise sqlite3.DatabaseError(
                    "task event result terminal event binding mismatch"
                )
            if str(payload.get("result_hash") or "") not in {
                "",
                str(verified["sha256"]),
            }:
                raise sqlite3.DatabaseError("task event result hash mismatch")
            if isinstance(payload.get("result"), dict):
                if self._canonical_result_json(dict(payload["result"])) != str(
                    verified["canonical_json"]
                ):
                    raise sqlite3.DatabaseError("task event dual-write result mismatch")
            else:
                payload["result"] = dict(verified["result"])
            payload["result_hash"] = str(verified["sha256"])
            payload.setdefault(
                "result_summary",
                self._result_summary(
                    dict(verified["result"]),
                    byte_size=int(verified["byte_size"]),
                ),
            )
            event["payload"] = payload
        return event

    @staticmethod
    def _canonical_result_json(result: dict[str, Any]) -> str:
        return json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _result_summary(result: dict[str, Any], *, byte_size: int) -> dict[str, Any]:
        keys = sorted(str(key) for key in result)
        summary: dict[str, Any] = {
            "byte_size": int(byte_size),
            "field_count": len(keys),
            "keys": keys[:32],
            "keys_truncated": len(keys) > 32,
        }
        for key in (
            "business_status",
            "business_outcome",
            "success_count",
            "failed_count",
            "skipped_count",
            "warning_count",
            "partial_success",
            "artifact_id",
            "artifact_ref",
            "artifact_path",
            "artifact_name",
            "artifact_source",
            "artifact_type",
            "available",
            "display_name",
            "download_ref",
            "filename",
            "name",
            "size",
            "size_bytes",
            "sha256",
            "result_ref",
            "records_count",
            "snapshot_id",
        ):
            value = result.get(key)
            if isinstance(value, (str, int, bool)):
                summary[key] = value
        for key in (
            "failure_reason_counts",
            "skipped_reason_counts",
            "warning_reason_counts",
        ):
            value = result.get(key)
            if isinstance(value, dict):
                summary[key] = {
                    str(reason): int(count)
                    for reason, count in sorted(
                        value.items(), key=lambda item: str(item[0])
                    )[:32]
                    if isinstance(count, int) and count >= 0
                }
        reason = result.get("primary_failure_reason") or result.get("error_code")
        if isinstance(reason, str) and reason:
            summary["primary_failure_reason"] = reason[:500]
        return summary

    @classmethod
    def _verified_result_row(cls, row: dict[str, object]) -> dict[str, Any]:
        return verify_task_result_row(dict(row))

    def _verified_result_for_read(
        self,
        row: dict[str, object],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        row = dict(row)
        content_sha256 = str(row.get("content_sha256") or "")
        sha256 = str(row.get("sha256") or "")
        if content_sha256 and content_sha256 != sha256:
            raise sqlite3.DatabaseError("task result content hash metadata mismatch")
        try:
            blob_ready = int(row.get("blob_ready") or 0)
        except (TypeError, ValueError) as exc:
            raise sqlite3.DatabaseError("task result blob readiness is invalid") from exc
        if blob_ready:
            if conn is None:
                raise sqlite3.DatabaseError("task result blob read requires a database connection")
            try:
                row["canonical_json"] = read_blob(
                    conn,
                    content_sha256=content_sha256 or sha256,
                    expected_bytes=int(row.get("byte_size") or -1),
                )
            except TaskResultBlobError as exc:
                raise sqlite3.DatabaseError(str(exc)) from exc
        elif content_sha256:
            raise sqlite3.DatabaseError("task result blob is not ready")
        result_id = str(row.get("result_id") or "")
        if result_id and not blob_ready:
            cached = self._verified_result_cache.get(result_id)
            if cached is not None:
                return cached
        verified = self._verified_result_row(row)
        if result_id:
            self._verified_result_cache[result_id] = verified
        return verified

    @staticmethod
    def _is_local_result_row(conn, result_id: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM task_results WHERE result_id=?", (str(result_id),)
            ).fetchone()
            is not None
        )

    @staticmethod
    def _ensure_result_blob(
        conn: sqlite3.Connection,
        *,
        canonical_json: str,
        content_sha256: str,
        created_time: str,
        verified_at: str,
    ) -> None:
        try:
            ensure_blob(
                conn,
                canonical_json=canonical_json,
                content_sha256=content_sha256,
                created_time=created_time,
                verified_at=verified_at,
            )
        except TaskResultBlobError as exc:
            raise sqlite3.DatabaseError(str(exc)) from exc

    def _ensure_result_blob_for_row(
        self,
        conn: sqlite3.Connection,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_json = str(row.get("canonical_json") or "")
        digest = str(row.get("sha256") or "")
        created_time = str(row.get("created_time") or utc_now_iso())
        self._ensure_result_blob(
            conn,
            canonical_json=canonical_json,
            content_sha256=digest,
            created_time=created_time,
            verified_at=utc_now_iso(),
        )
        conn.execute(
            "UPDATE task_results SET content_sha256=?, blob_codec=?, blob_ready=1 "
            "WHERE result_id=? AND blob_ready=0",
            (digest, TASK_RESULT_BLOB_CODEC_ZLIB, str(row.get("result_id") or "")),
        )
        updated = dict(
            conn.execute(
                "SELECT * FROM task_results WHERE result_id=?",
                (str(row.get("result_id") or ""),),
            ).fetchone()
        )
        return self._verified_result_for_read(updated, conn=conn)

    def _result_row(self, conn, result_id: str) -> dict[str, Any] | sqlite3.Row | None:
        row = conn.execute(
            "SELECT * FROM task_results WHERE result_id=?", (str(result_id),)
        ).fetchone()
        if row is not None:
            return row
        return self.task_history.get_result(str(result_id))

def _contains_replacement_character(value: object) -> bool:
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(_contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_replacement_character(item) for item in value)
    return False
