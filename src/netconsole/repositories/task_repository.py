from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.task_state import TaskState
from netconsole.models.task_snapshot import (
    TEXT_INTEGRITY_VALUES,
    TaskEvent,
    TaskSnapshot,
    utc_now_iso,
)
from netconsole.services.job_center.task_history_policy import (
    ACTIVE_TASK_STATE_VALUES,
    TERMINAL_TASK_STATE_VALUES,
    task_expires_at,
    task_requires_attention,
    utc_time_reached,
)


TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO task_schema_meta(key, value) VALUES ('schema_version', '3');

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
                        result=self._json_object(row["result_json"]),
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
                    SELECT task_id, status, error_message, result_json, acknowledged_at
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
                    result=self._json_object(row["result_json"]),
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
                           result_json, expires_at, acknowledged_at
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
                    result = self._json_object(row["result_json"])
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

    def visible_attention_summary(self) -> dict[str, int]:
        summary = {"running": 0, "queued": 0, "failed": 0, "warning": 0}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, error_message, result_json, acknowledged_at
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
            result = self._json_object(row["result_json"])
            if status == TaskState.FAILED.value:
                summary["failed"] += 1
            elif task_requires_attention(
                status,
                error_message=str(row["error_message"] or ""),
                result=result,
            ):
                summary["warning"] += 1
        return summary

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

    @classmethod
    def _ensure_schema_compat(cls, conn) -> None:
        columns = {
            "resource_keys_json": "TEXT NOT NULL DEFAULT '[]'",
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
                conn.execute(f"ALTER TABLE task_snapshots ADD COLUMN {column} {definition}")
        cls._migrate_legacy_text_integrity(conn)
        cls._backfill_task_expiration(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_snapshots_visible_updated "
            "ON task_snapshots(dismissed_at, updated_time DESC)"
        )
        conn.execute(
            "INSERT INTO task_schema_meta(key, value) VALUES ('schema_version', '3') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
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
                resource_keys_json, text_integrity, text_integrity_reason,
                text_integrity_updated_at, text_schema_version, producer_kind,
                producer_version, producer_commit, expires_at, updated_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                text_integrity=excluded.text_integrity,
                text_integrity_reason=excluded.text_integrity_reason,
                text_integrity_updated_at=excluded.text_integrity_updated_at,
                text_schema_version=excluded.text_schema_version,
                producer_kind=excluded.producer_kind,
                producer_version=excluded.producer_version,
                producer_commit=excluded.producer_commit,
                expires_at=excluded.expires_at,
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
                snapshot.text_integrity
                if snapshot.text_integrity in TEXT_INTEGRITY_VALUES
                else "unknown_corrupted",
                snapshot.text_integrity_reason,
                snapshot.text_integrity_updated_at,
                int(snapshot.text_schema_version),
                snapshot.producer_kind,
                snapshot.producer_version,
                snapshot.producer_commit,
                task_expires_at(
                    snapshot.status,
                    finished_time=snapshot.finished_time,
                    updated_time=snapshot.updated_time,
                    error_message=snapshot.error_message,
                    result=snapshot.result,
                ),
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


def _contains_replacement_character(value: object) -> bool:
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(_contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_replacement_character(item) for item in value)
    return False
