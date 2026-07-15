from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    AgentTaskMapping,
    ExecutionTargetKind,
    TrafficPingSample,
    TrafficRun,
    TrafficRunPage,
    TrafficSyncState,
    TrafficTestType,
)


TRAFFIC_SCHEMA_VERSION = 1

_SECRET_KEYS = frozenset({"authorization", "credential", "password", "secret", "token", "x-agent-token"})


class TrafficRunRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, foreign_keys=True)

    def initialize(self) -> None:
        def operation() -> None:
            with self._connect() as conn:
                initialize_sqlite_wal(conn)
                mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).casefold()
                if mode != "wal":
                    raise RuntimeError(f"traffic database requires WAL mode, got {mode}")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    self._ensure_schema(conn)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        run_sqlite_with_retry(operation)

    def create(self, run: TrafficRun) -> TrafficRun:
        _assert_safe_json(run.normalized_config)

        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO traffic_runs (
                        traffic_run_id, controller_task_id, test_type, role, executor_kind, agent_id,
                        normalized_config_json, status, created_at, started_at, finished_at,
                        summary_json, error_code, error_message, raw_reference, result_reference,
                        local_iperf_run_id, retry_of_traffic_run_id, parent_task_id, correlation_id,
                        last_event_sequence, sync_state, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._run_values(run),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return run

    def save(self, run: TrafficRun) -> TrafficRun:
        _assert_safe_json(run.normalized_config)

        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO traffic_runs (
                        traffic_run_id, controller_task_id, test_type, role, executor_kind, agent_id,
                        normalized_config_json, status, created_at, started_at, finished_at,
                        summary_json, error_code, error_message, raw_reference, result_reference,
                        local_iperf_run_id, retry_of_traffic_run_id, parent_task_id, correlation_id,
                        last_event_sequence, sync_state, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(traffic_run_id) DO UPDATE SET
                        controller_task_id=excluded.controller_task_id,
                        test_type=excluded.test_type,
                        role=excluded.role,
                        executor_kind=excluded.executor_kind,
                        agent_id=excluded.agent_id,
                        normalized_config_json=excluded.normalized_config_json,
                        status=excluded.status,
                        started_at=excluded.started_at,
                        finished_at=excluded.finished_at,
                        summary_json=excluded.summary_json,
                        error_code=excluded.error_code,
                        error_message=excluded.error_message,
                        raw_reference=excluded.raw_reference,
                        result_reference=excluded.result_reference,
                        local_iperf_run_id=excluded.local_iperf_run_id,
                        retry_of_traffic_run_id=excluded.retry_of_traffic_run_id,
                        parent_task_id=excluded.parent_task_id,
                        correlation_id=excluded.correlation_id,
                        last_event_sequence=MAX(traffic_runs.last_event_sequence, excluded.last_event_sequence),
                        sync_state=excluded.sync_state,
                        updated_at=excluded.updated_at
                    """,
                    self._run_values(run),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return run

    def get(self, traffic_run_id: str) -> TrafficRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traffic_runs WHERE traffic_run_id = ?", (traffic_run_id,)).fetchone()
        return self._run_from_row(dict(row)) if row is not None else None

    def get_by_controller_task(self, controller_task_id: str) -> TrafficRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traffic_runs WHERE controller_task_id = ?", (controller_task_id,)).fetchone()
        return self._run_from_row(dict(row)) if row is not None else None

    def list(
        self,
        *,
        statuses: set[TaskState] | None = None,
        test_type: TrafficTestType | None = None,
        executor_kind: ExecutionTargetKind | None = None,
        agent_id: str | None = None,
        limit: int = 200,
    ) -> list[TrafficRun]:
        clauses, params = self._run_filter_parts(
            statuses=statuses,
            test_type=test_type,
            executor_kind=executor_kind,
            agent_id=agent_id,
        )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 2_000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM traffic_runs {where} ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._run_from_row(dict(row)) for row in rows]

    def list_page(
        self,
        *,
        statuses: set[TaskState] | None = None,
        test_type: TrafficTestType | None = None,
        executor_kind: ExecutionTargetKind | None = None,
        agent_id: str | None = None,
        created_after: str = "",
        created_before: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> TrafficRunPage:
        clauses, params = self._run_filter_parts(
            statuses=statuses,
            test_type=test_type,
            executor_kind=executor_kind,
            agent_id=agent_id,
            created_after=created_after,
            created_before=created_before,
        )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        selected_offset = max(0, int(offset))
        selected_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM traffic_runs {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT * FROM traffic_runs
                {where}
                ORDER BY updated_at DESC, created_at DESC, traffic_run_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, selected_limit, selected_offset],
            ).fetchall()
        items = [self._run_from_row(dict(row)) for row in rows]
        return TrafficRunPage(
            items=items,
            total=total,
            offset=selected_offset,
            limit=selected_limit,
            has_more=selected_offset + len(items) < total,
        )

    @staticmethod
    def _run_filter_parts(
        *,
        statuses: set[TaskState] | None = None,
        test_type: TrafficTestType | None = None,
        executor_kind: ExecutionTargetKind | None = None,
        agent_id: str | None = None,
        created_after: str = "",
        created_before: str = "",
    ) -> tuple[list[str], list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if statuses:
            values = sorted(item.value for item in statuses)
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if test_type is not None:
            clauses.append("test_type = ?")
            params.append(test_type.value)
        if executor_kind is not None:
            clauses.append("executor_kind = ?")
            params.append(executor_kind.value)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if created_after:
            clauses.append("created_at >= ?")
            params.append(str(created_after))
        if created_before:
            clauses.append("created_at <= ?")
            params.append(str(created_before))
        return clauses, params

    def delete(self, traffic_run_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute("DELETE FROM traffic_runs WHERE traffic_run_id = ?", (traffic_run_id,))
                conn.commit()
                return cursor.rowcount == 1

        return run_sqlite_with_retry(operation)

    def update_last_event_sequence(self, traffic_run_id: str, sequence: int, updated_at: str) -> None:
        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    UPDATE traffic_runs
                    SET last_event_sequence = MAX(last_event_sequence, ?), updated_at = ?
                    WHERE traffic_run_id = ?
                    """,
                    (max(0, int(sequence)), updated_at, traffic_run_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(traffic_run_id)
                conn.commit()

        run_sqlite_with_retry(operation)

    def save_agent_mapping(self, mapping: AgentTaskMapping) -> AgentTaskMapping:
        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO traffic_agent_tasks (
                        traffic_run_id, controller_task_id, agent_id, agent_task_id, agent_task_type,
                        last_remote_sequence, last_remote_status, last_polled_at, sync_state,
                        sync_error_code, sync_error_message, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(traffic_run_id) DO UPDATE SET
                        controller_task_id=excluded.controller_task_id,
                        agent_id=excluded.agent_id,
                        agent_task_id=excluded.agent_task_id,
                        agent_task_type=excluded.agent_task_type,
                        last_remote_sequence=MAX(traffic_agent_tasks.last_remote_sequence, excluded.last_remote_sequence),
                        last_remote_status=excluded.last_remote_status,
                        last_polled_at=excluded.last_polled_at,
                        sync_state=excluded.sync_state,
                        sync_error_code=excluded.sync_error_code,
                        sync_error_message=excluded.sync_error_message,
                        updated_at=excluded.updated_at
                    """,
                    self._mapping_values(mapping),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return mapping

    def get_agent_mapping(self, traffic_run_id: str) -> AgentTaskMapping | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traffic_agent_tasks WHERE traffic_run_id = ?", (traffic_run_id,)).fetchone()
        return self._mapping_from_row(dict(row)) if row is not None else None

    def get_agent_mapping_by_remote_task(self, agent_id: str, agent_task_id: str) -> AgentTaskMapping | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM traffic_agent_tasks WHERE agent_id = ? AND agent_task_id = ?",
                (agent_id, agent_task_id),
            ).fetchone()
        return self._mapping_from_row(dict(row)) if row is not None else None

    def delete_agent_mapping(self, traffic_run_id: str) -> bool:
        def operation() -> bool:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    "DELETE FROM traffic_agent_tasks WHERE traffic_run_id = ?",
                    (traffic_run_id,),
                )
                conn.commit()
                return cursor.rowcount == 1

        return run_sqlite_with_retry(operation)

    def list_recoverable_agent_mappings(self, *, limit: int = 500) -> list[AgentTaskMapping]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mapping.*
                FROM traffic_agent_tasks AS mapping
                JOIN traffic_runs AS run ON run.traffic_run_id = mapping.traffic_run_id
                WHERE mapping.sync_state <> ?
                ORDER BY mapping.updated_at ASC
                LIMIT ?
                """,
                (
                    TrafficSyncState.COMPLETED.value,
                    max(1, min(int(limit), 2_000)),
                ),
            ).fetchall()
        return [self._mapping_from_row(dict(row)) for row in rows]

    def insert_ping_samples(self, samples: Iterable[TrafficPingSample], *, updated_at: str = "") -> int:
        rows = list(samples)
        if not rows:
            return 0

        def operation() -> int:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                before = conn.total_changes
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO traffic_ping_samples (
                        traffic_run_id, sequence, timestamp, target, probe_sequence, ok, rtt_ms,
                        timeout, packet_size, error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [self._sample_values(item) for item in rows],
                )
                inserted = conn.total_changes - before
                for traffic_run_id in {sample.traffic_run_id for sample in rows}:
                    stored = conn.execute(
                        "SELECT COALESCE(MAX(sequence), 0) FROM traffic_ping_samples WHERE traffic_run_id = ?",
                        (traffic_run_id,),
                    ).fetchone()
                    sequence = int(stored[0] if stored is not None else 0)
                    conn.execute(
                        """
                        UPDATE traffic_runs
                        SET last_event_sequence = MAX(last_event_sequence, ?),
                            updated_at = CASE WHEN ? <> '' THEN ? ELSE updated_at END
                        WHERE traffic_run_id = ?
                        """,
                        (sequence, updated_at, updated_at, traffic_run_id),
                    )
                conn.commit()
                return inserted

        return run_sqlite_with_retry(operation)

    def list_ping_samples(
        self,
        traffic_run_id: str,
        *,
        after_sequence: int = 0,
        target: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 1_000,
    ) -> list[TrafficPingSample]:
        clauses = ["traffic_run_id = ?", "sequence > ?"]
        params: list[object] = [traffic_run_id, max(0, int(after_sequence))]
        if target is not None:
            clauses.append("target = ?")
            params.append(target)
        if start_time:
            clauses.append("timestamp >= ?")
            params.append(str(start_time))
        if end_time:
            clauses.append("timestamp <= ?")
            params.append(str(end_time))
        params.append(max(1, min(int(limit), 10_000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM traffic_ping_samples WHERE {' AND '.join(clauses)} ORDER BY sequence ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._sample_from_row(dict(row)) for row in rows]

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS traffic_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute("SELECT value FROM traffic_schema_meta WHERE key = 'schema_version'").fetchone()
        if row is not None and int(row["value"]) > TRAFFIC_SCHEMA_VERSION:
            raise RuntimeError(f"unsupported traffic schema version: {row['value']}")
        for statement in _SCHEMA_V1:
            conn.execute(statement)
        conn.execute(
            """
            INSERT INTO traffic_schema_meta(key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(TRAFFIC_SCHEMA_VERSION),),
        )

    @staticmethod
    def _run_values(run: TrafficRun) -> tuple[object, ...]:
        _assert_safe_json(run.summary)
        _assert_relative_reference(run.raw_reference)
        _assert_relative_reference(run.result_reference)
        return (
            run.traffic_run_id,
            run.controller_task_id or None,
            run.test_type.value,
            run.role,
            run.executor_kind.value,
            run.agent_id or None,
            _json_dump(run.normalized_config),
            run.status.value,
            run.created_at,
            run.started_at,
            run.finished_at,
            _json_dump(run.summary),
            run.error_code,
            run.error_message,
            run.raw_reference,
            run.result_reference,
            run.local_iperf_run_id or None,
            run.retry_of_traffic_run_id or None,
            run.parent_task_id or None,
            run.correlation_id or None,
            max(0, int(run.last_event_sequence)),
            run.sync_state.value,
            run.updated_at,
        )

    @staticmethod
    def _mapping_values(mapping: AgentTaskMapping) -> tuple[object, ...]:
        return (
            mapping.traffic_run_id,
            mapping.controller_task_id,
            mapping.agent_id,
            mapping.agent_task_id,
            mapping.agent_task_type,
            max(0, int(mapping.last_remote_sequence)),
            mapping.last_remote_status,
            mapping.last_polled_at,
            mapping.sync_state.value,
            mapping.sync_error_code,
            mapping.sync_error_message,
            mapping.created_at,
            mapping.updated_at,
        )

    @staticmethod
    def _sample_values(sample: TrafficPingSample) -> tuple[object, ...]:
        rtt_ms = float(sample.rtt_ms) if sample.rtt_ms is not None else None
        if sample.timeout:
            rtt_ms = None
        return (
            sample.traffic_run_id,
            max(1, int(sample.sequence)),
            sample.timestamp,
            sample.target,
            int(sample.probe_sequence) if sample.probe_sequence is not None else None,
            int(bool(sample.ok)),
            rtt_ms,
            int(bool(sample.timeout)),
            int(sample.packet_size) if sample.packet_size is not None else None,
            sample.error_code,
            sample.error_message,
        )

    @staticmethod
    def _run_from_row(row: dict[str, Any]) -> TrafficRun:
        return TrafficRun(
            traffic_run_id=str(row["traffic_run_id"]),
            controller_task_id=str(row.get("controller_task_id") or ""),
            test_type=TrafficTestType(str(row["test_type"])),
            role=str(row["role"]),
            executor_kind=ExecutionTargetKind(str(row["executor_kind"])),
            agent_id=str(row.get("agent_id") or ""),
            normalized_config=_json_object(row.get("normalized_config_json")),
            status=TaskState(str(row["status"])),
            created_at=str(row["created_at"]),
            started_at=str(row.get("started_at") or ""),
            finished_at=str(row.get("finished_at") or ""),
            summary=_json_object(row.get("summary_json")),
            error_code=str(row.get("error_code") or ""),
            error_message=str(row.get("error_message") or ""),
            raw_reference=str(row.get("raw_reference") or ""),
            result_reference=str(row.get("result_reference") or ""),
            local_iperf_run_id=str(row.get("local_iperf_run_id") or ""),
            retry_of_traffic_run_id=str(row.get("retry_of_traffic_run_id") or ""),
            parent_task_id=str(row.get("parent_task_id") or ""),
            correlation_id=str(row.get("correlation_id") or ""),
            last_event_sequence=int(row.get("last_event_sequence") or 0),
            sync_state=TrafficSyncState(str(row.get("sync_state") or TrafficSyncState.ACTIVE.value)),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _mapping_from_row(row: dict[str, Any]) -> AgentTaskMapping:
        return AgentTaskMapping(
            traffic_run_id=str(row["traffic_run_id"]),
            controller_task_id=str(row["controller_task_id"]),
            agent_id=str(row["agent_id"]),
            agent_task_id=str(row["agent_task_id"]),
            agent_task_type=str(row["agent_task_type"]),
            last_remote_sequence=int(row.get("last_remote_sequence") or 0),
            last_remote_status=str(row.get("last_remote_status") or ""),
            last_polled_at=str(row.get("last_polled_at") or ""),
            sync_state=TrafficSyncState(str(row.get("sync_state") or TrafficSyncState.ACTIVE.value)),
            sync_error_code=str(row.get("sync_error_code") or ""),
            sync_error_message=str(row.get("sync_error_message") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    @staticmethod
    def _sample_from_row(row: dict[str, Any]) -> TrafficPingSample:
        return TrafficPingSample(
            traffic_run_id=str(row["traffic_run_id"]),
            sequence=int(row["sequence"]),
            timestamp=str(row["timestamp"]),
            target=str(row["target"]),
            probe_sequence=int(row["probe_sequence"]) if row.get("probe_sequence") is not None else None,
            ok=bool(row["ok"]),
            rtt_ms=float(row["rtt_ms"]) if row.get("rtt_ms") is not None else None,
            timeout=bool(row["timeout"]),
            packet_size=int(row["packet_size"]) if row.get("packet_size") is not None else None,
            error_code=str(row.get("error_code") or ""),
            error_message=str(row.get("error_message") or ""),
        )


_SCHEMA_V1 = (
    """
    CREATE TABLE IF NOT EXISTS traffic_runs (
        traffic_run_id TEXT PRIMARY KEY,
        controller_task_id TEXT,
        test_type TEXT NOT NULL,
        role TEXT NOT NULL,
        executor_kind TEXT NOT NULL,
        agent_id TEXT,
        normalized_config_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        started_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '',
        summary_json TEXT NOT NULL DEFAULT '{}',
        error_code TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        raw_reference TEXT NOT NULL DEFAULT '',
        result_reference TEXT NOT NULL DEFAULT '',
        local_iperf_run_id TEXT,
        retry_of_traffic_run_id TEXT,
        parent_task_id TEXT,
        correlation_id TEXT,
        last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_event_sequence >= 0),
        sync_state TEXT NOT NULL DEFAULT 'ACTIVE',
        updated_at TEXT NOT NULL,
        FOREIGN KEY(retry_of_traffic_run_id) REFERENCES traffic_runs(traffic_run_id) ON DELETE RESTRICT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_traffic_runs_controller_task ON traffic_runs(controller_task_id) WHERE controller_task_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_traffic_runs_local_iperf ON traffic_runs(local_iperf_run_id) WHERE local_iperf_run_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_traffic_runs_status_updated ON traffic_runs(status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_traffic_runs_agent_sync ON traffic_runs(agent_id, sync_state, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_traffic_runs_correlation ON traffic_runs(correlation_id) WHERE correlation_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS traffic_agent_tasks (
        traffic_run_id TEXT PRIMARY KEY,
        controller_task_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        agent_task_id TEXT NOT NULL,
        agent_task_type TEXT NOT NULL,
        last_remote_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_remote_sequence >= 0),
        last_remote_status TEXT NOT NULL DEFAULT 'created',
        last_polled_at TEXT NOT NULL DEFAULT '',
        sync_state TEXT NOT NULL DEFAULT 'ACTIVE',
        sync_error_code TEXT NOT NULL DEFAULT '',
        sync_error_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(traffic_run_id) REFERENCES traffic_runs(traffic_run_id) ON DELETE CASCADE,
        UNIQUE(agent_id, agent_task_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_traffic_agent_tasks_recovery ON traffic_agent_tasks(sync_state, last_polled_at, updated_at)",
    """
    CREATE TABLE IF NOT EXISTS traffic_ping_samples (
        traffic_run_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence > 0),
        timestamp TEXT NOT NULL,
        target TEXT NOT NULL,
        probe_sequence INTEGER,
        ok INTEGER NOT NULL CHECK(ok IN (0, 1)),
        rtt_ms REAL,
        timeout INTEGER NOT NULL DEFAULT 0 CHECK(timeout IN (0, 1)),
        packet_size INTEGER,
        error_code TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(traffic_run_id, sequence),
        FOREIGN KEY(traffic_run_id) REFERENCES traffic_runs(traffic_run_id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_traffic_ping_probe_identity ON traffic_ping_samples(traffic_run_id, target, probe_sequence) WHERE probe_sequence IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_traffic_ping_run_time ON traffic_ping_samples(traffic_run_id, timestamp, sequence)",
)


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _assert_safe_json(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("_", "-")
            if normalized in _SECRET_KEYS or any(part in normalized for part in ("password", "secret", "token")):
                raise ValueError(f"sensitive field is not allowed in traffic storage: {key}")
            _assert_safe_json(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_safe_json(item)


def _assert_relative_reference(value: str) -> None:
    if not value:
        return
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("traffic file references must be relative paths")
