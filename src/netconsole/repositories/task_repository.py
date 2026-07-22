from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import asdict
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.task_state import TaskState
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot, utc_now_iso


TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO task_schema_meta(key, value) VALUES ('schema_version', '1');

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
    source TEXT NOT NULL DEFAULT 'local',
    site_name TEXT NOT NULL DEFAULT 'demo',
    owner_pid INTEGER NOT NULL DEFAULT 0,
    resource_keys_json TEXT NOT NULL DEFAULT '[]',
    updated_time TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_status_updated
    ON task_snapshots(status, updated_time DESC);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_type_updated
    ON task_snapshots(task_type, updated_time DESC);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_file_filter
    ON task_snapshots(task_type, owner, source, site_name, status, updated_time DESC);

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
"""


class TaskRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.initialize()

    def _connect(self):
        return connect_sqlite(self.db_path, foreign_keys=True)

    def initialize(self) -> None:
        def operation() -> None:
            with self._connect() as conn:
                initialize_sqlite_wal(conn)
                conn.executescript(TASK_SCHEMA)
                self._ensure_schema_compat(conn)
                conn.commit()

        run_sqlite_with_retry(operation)

    def save(self, snapshot: TaskSnapshot) -> None:
        def operation() -> None:
            with self._connect() as conn:
                self._upsert(conn, snapshot)
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
                      AND status IN ({','.join('?' for _ in active_values)})
                      AND resource_keys_json <> '[]'
                    ORDER BY updated_time DESC, created_time DESC, task_id DESC
                    """,
                    (snapshot.site_name, *active_values),
                ).fetchall()
                for row in rows:
                    current = self._snapshot_from_row(dict(row))
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
                if not self._upsert(conn, snapshot, allowed_from=allowed_from):
                    conn.rollback()
                    return
                conn.execute(
                    """
                    INSERT OR IGNORE INTO task_events (
                        event_id, task_id, event_type, event_time, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        event.type,
                        event.time,
                        event.source,
                        json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.commit()
                recorded = True

        run_sqlite_with_retry(operation)
        return recorded

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
                if not self._upsert(conn, snapshot, allowed_from=allowed_from):
                    conn.rollback()
                    return
                conn.execute(
                    """
                    INSERT INTO task_events (
                        event_id, task_id, event_type, event_time, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        event.type,
                        event.time,
                        event.source,
                        json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.commit()
                recorded = True

        run_sqlite_with_retry(operation)
        return recorded

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM task_snapshots WHERE task_id = ?", (task_id,)).fetchone()
        return self._snapshot_from_row(dict(row)) if row is not None else None

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
        )
        params.extend((max(1, min(int(limit), 1000)), max(0, int(offset))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_snapshots {where} "
                "ORDER BY updated_time DESC, created_time DESC, task_id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._snapshot_from_row(dict(row)) for row in rows]

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
    ) -> int:
        where, params = self._snapshot_filter(
            statuses=statuses,
            owner=owner,
            source=source,
            site_name=site_name,
            task_types=task_types,
            device=device,
            device_aliases=device_aliases,
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
    ) -> tuple[str, list[object]]:
        params: list[object] = []
        clauses: list[str] = []
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

    def list_events(self, task_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sequence, event_id, task_id, event_type, event_time, source, payload_json
                FROM task_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (task_id, max(0, int(after_sequence)), max(1, min(int(limit), 2000))),
            ).fetchall()
        return [self._event_from_row(dict(row)) for row in rows]

    def list_events_for_tasks(
        self,
        task_ids: Collection[str],
        *,
        event_types: Collection[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """批量读取指定任务事件，避免任务列表逐条查询事件。"""

        ids = sorted({str(task_id).strip() for task_id in task_ids if str(task_id).strip()})
        if not ids:
            return {}
        grouped = {task_id: [] for task_id in ids}
        types = sorted({str(event_type).strip() for event_type in (event_types or ()) if str(event_type).strip()})
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
                    event = self._event_from_row(dict(row))
                    grouped.setdefault(str(event["task_id"]), []).append(event)
        return grouped

    def list_all_events(self, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
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
        return [self._event_from_row(dict(row)) for row in rows]

    def last_event_sequence(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sequence), 0) AS value FROM task_events").fetchone()
        return int(row["value"] if row is not None else 0)

    def reconcile_orphaned_local_tasks(self, is_process_alive) -> list[TaskSnapshot]:
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        changed: list[TaskSnapshot] = []
        for snapshot in self.list(statuses=active, limit=1000):
            if snapshot.source != "local" or snapshot.owner_pid <= 0 or is_process_alive(snapshot.owner_pid):
                continue
            now = utc_now_iso()
            form_connection_test = snapshot.task_id.startswith("device-form-test-")
            message = (
                "临时表单连接测试不可恢复"
                if form_connection_test
                else "任务宿主已退出"
            )
            error_message = (
                "上次运行非正常中断，一次性表单凭据已失效，请重新提交测试"
                if form_connection_test
                else "上次运行非正常中断，未发现仍存活的本地任务宿主"
            )
            updated = TaskSnapshot(
                **{
                    **asdict(snapshot),
                    "status": TaskState.FAILED,
                    "finished_time": now,
                    "updated_time": now,
                    "message": message,
                    "error_message": error_message,
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
    def _ensure_schema_compat(conn) -> None:
        if not TaskRepository._column_exists(conn, "task_snapshots", "resource_keys_json"):
            conn.execute("ALTER TABLE task_snapshots ADD COLUMN resource_keys_json TEXT NOT NULL DEFAULT '[]'")

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
        allowed_values = None if allowed_from is None else sorted(state.value for state in allowed_from)
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
                resource_keys_json, updated_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                result_json=excluded.result_json,
                source=excluded.source,
                site_name=excluded.site_name,
                owner_pid=excluded.owner_pid,
                resource_keys_json=excluded.resource_keys_json,
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
                json.dumps(list(snapshot.resource_keys or []), ensure_ascii=False, separators=(",", ":")),
                snapshot.updated_time,
                *(allowed_values or ()),
            ),
        )
        return cursor.rowcount > 0

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
            source=str(row.get("source") or "local"),
            site_name=str(row.get("site_name") or "demo"),
            owner_pid=int(row.get("owner_pid") or 0),
            resource_keys=cls._json_list(row.get("resource_keys_json")),
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
