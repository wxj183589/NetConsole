from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
    calculate_duration_minutes,
)


SCHEMA_VERSION = 3
SCHEMA = """
CREATE TABLE IF NOT EXISTS online_mr_task_session_schema (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO online_mr_task_session_schema(singleton, version) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS online_mr_task_sessions (
    controller_task_id TEXT PRIMARY KEY,
    session_id TEXT UNIQUE,
    site_id TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    device_name TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    mr_name TEXT NOT NULL DEFAULT '',
    executor_kind TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    agent_profile_id TEXT NOT NULL DEFAULT '',
    agent_task_id TEXT NOT NULL DEFAULT '',
    remote_session_id TEXT NOT NULL DEFAULT '',
    remote_package_id TEXT NOT NULL DEFAULT '',
    last_remote_status TEXT NOT NULL DEFAULT '',
    last_remote_seen_at TEXT,
    consecutive_status_failures INTEGER NOT NULL DEFAULT 0,
    deadline_at TEXT,
    phase TEXT NOT NULL,
    mapping_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    duration_minutes REAL,
    stop_reason TEXT NOT NULL DEFAULT '',
    force_stopped INTEGER NOT NULL DEFAULT 0,
    terminal_at TEXT,
    error_summary TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_online_mr_task_sessions_site_updated
    ON online_mr_task_sessions(site_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_online_mr_task_sessions_state_updated
    ON online_mr_task_sessions(mapping_state, updated_at DESC);
"""


class OnlineMrTaskSessionRepository:
    """与 TaskRepository 共用 tasks.db 的 Online MR 轻量映射表。"""

    def __init__(self, db_path: str | Path, *, site_id: str) -> None:
        self.db_path = Path(db_path)
        self.site_id = str(site_id or "")
        if not self.site_id:
            raise ValueError("site_id 不能为空")
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, foreign_keys=True)

    def initialize(self) -> None:
        def operation() -> None:
            with self._connect() as conn:
                initialize_sqlite_wal(conn)
                conn.executescript(SCHEMA)
                self._ensure_columns(conn)
                conn.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS idx_online_mr_task_sessions_agent_task
                    ON online_mr_task_sessions(agent_id, agent_task_id)
                    WHERE agent_id <> '' AND agent_task_id <> ''"""
                )
                conn.execute(
                    "UPDATE online_mr_task_session_schema SET version = MAX(version, ?) WHERE singleton = 1",
                    (SCHEMA_VERSION,),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def create(self, mapping: OnlineMrTaskSessionMapping) -> OnlineMrTaskSessionMapping:
        self._require_site(mapping)

        def operation() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO online_mr_task_sessions (
                        controller_task_id, session_id, site_id, device_id, device_name, mr_id, mr_name,
                        executor_kind, agent_id, agent_profile_id, agent_task_id, remote_session_id, remote_package_id,
                        last_remote_status, last_remote_seen_at, consecutive_status_failures, deadline_at,
                        phase, mapping_state, created_at, updated_at,
                        started_at, ended_at, duration_minutes, stop_reason, force_stopped,
                        terminal_at, error_summary, error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._values(mapping),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return mapping

    def save(self, mapping: OnlineMrTaskSessionMapping) -> OnlineMrTaskSessionMapping:
        self._require_site(mapping)

        def operation() -> None:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE online_mr_task_sessions SET
                        session_id = ?, device_id = ?, device_name = ?, mr_id = ?, mr_name = ?, executor_kind = ?,
                        agent_id = ?, agent_profile_id = ?, agent_task_id = ?, remote_session_id = ?, remote_package_id = ?,
                        last_remote_status = ?, last_remote_seen_at = ?, consecutive_status_failures = ?, deadline_at = ?,
                        phase = ?, mapping_state = ?, updated_at = ?, terminal_at = ?,
                        started_at = ?, ended_at = ?, duration_minutes = ?, stop_reason = ?,
                        force_stopped = ?, error_summary = ?, error_code = ?, error_message = ?
                    WHERE controller_task_id = ? AND site_id = ?
                    """,
                    (
                        mapping.session_id,
                        mapping.device_id,
                        mapping.device_name,
                        mapping.mr_id,
                        mapping.mr_name,
                        mapping.executor_kind.value,
                        mapping.agent_id,
                        mapping.agent_profile_id,
                        mapping.agent_task_id,
                        mapping.remote_session_id,
                        mapping.remote_package_id,
                        mapping.last_remote_status,
                        mapping.last_remote_seen_at,
                        mapping.consecutive_status_failures,
                        mapping.deadline_at,
                        mapping.phase.value,
                        mapping.mapping_state.value,
                        mapping.updated_at,
                        mapping.terminal_at,
                        mapping.started_at,
                        mapping.ended_at,
                        mapping.duration_minutes,
                        mapping.stop_reason,
                        int(mapping.force_stopped),
                        mapping.error_summary,
                        mapping.error_code,
                        mapping.error_message,
                        mapping.controller_task_id,
                        self.site_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(mapping.controller_task_id)
                conn.commit()

        run_sqlite_with_retry(operation)
        return mapping

    def get_by_task(self, controller_task_id: str) -> OnlineMrTaskSessionMapping | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM online_mr_task_sessions WHERE controller_task_id = ? AND site_id = ?",
                (controller_task_id, self.site_id),
            ).fetchone()
        return self._from_row(dict(row)) if row is not None else None

    def delete(self, controller_task_id: str) -> None:
        """仅用于尚未发布成功的导入事务回滚，不删除 Session 文件。"""

        def operation() -> None:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM online_mr_task_sessions WHERE controller_task_id = ? AND site_id = ?",
                    (controller_task_id, self.site_id),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def find_by_task(self, controller_task_id: str) -> OnlineMrTaskSessionMapping | None:
        return self.get_by_task(controller_task_id)

    def get_by_session(self, session_id: str) -> OnlineMrTaskSessionMapping | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM online_mr_task_sessions WHERE session_id = ? AND site_id = ?",
                (session_id, self.site_id),
            ).fetchone()
        return self._from_row(dict(row)) if row is not None else None

    def find_active_by_session(self, session_id: str) -> OnlineMrTaskSessionMapping | None:
        mapping = self.get_by_session(session_id)
        if mapping is None or mapping.mapping_state not in {
            OnlineMrMappingState.PENDING_SESSION,
            OnlineMrMappingState.LINKED,
        }:
            return None
        return mapping

    def list_active(self, *, limit: int = 1000) -> list[OnlineMrTaskSessionMapping]:
        return self.list(
            states={OnlineMrMappingState.PENDING_SESSION, OnlineMrMappingState.LINKED},
            limit=limit,
        )

    def mark_stopping(
        self,
        controller_task_id: str,
        *,
        phase: OnlineMrPhase,
        stop_reason: str,
        force_stopped: bool = False,
        updated_at: str,
    ) -> OnlineMrTaskSessionMapping:
        mapping = self._required(controller_task_id)
        if mapping.mapping_state not in {
            OnlineMrMappingState.PENDING_SESSION,
            OnlineMrMappingState.LINKED,
        }:
            return mapping
        return self.save(
            replace(
                mapping,
                phase=phase,
                stop_reason=str(stop_reason or mapping.stop_reason),
                force_stopped=bool(force_stopped or mapping.force_stopped),
                updated_at=updated_at,
            )
        )

    def mark_terminal(
        self,
        controller_task_id: str,
        *,
        started_at: str | None = None,
        ended_at: str,
        updated_at: str | None = None,
        duration_minutes: float,
        stop_reason: str,
        force_stopped: bool,
        error_summary: str = "",
        error_code: str = "",
        mapping_state: OnlineMrMappingState = OnlineMrMappingState.TERMINAL,
    ) -> OnlineMrTaskSessionMapping:
        mapping = self._required(controller_task_id)
        terminal_time = str(updated_at or ended_at)
        return self.save(
            replace(
                mapping,
                phase=OnlineMrPhase.TERMINAL,
                mapping_state=mapping_state,
                updated_at=terminal_time,
                terminal_at=terminal_time,
                started_at=started_at or mapping.started_at,
                ended_at=ended_at,
                duration_minutes=max(0.0, float(duration_minutes)),
                stop_reason=str(stop_reason or mapping.stop_reason),
                force_stopped=bool(force_stopped or mapping.force_stopped),
                error_summary=str(error_summary or mapping.error_summary),
                error_code=str(error_code or mapping.error_code),
                error_message=str(error_summary or mapping.error_message),
            )
        )

    def update_duration(
        self,
        controller_task_id: str,
        *,
        started_at: str | None,
        ended_at: str,
        duration_minutes: float,
    ) -> OnlineMrTaskSessionMapping:
        mapping = self._required(controller_task_id)
        return self.save(
            replace(
                mapping,
                started_at=started_at or mapping.started_at,
                ended_at=ended_at,
                duration_minutes=max(0.0, float(duration_minutes)),
                updated_at=ended_at,
            )
        )

    def update_error_summary(
        self,
        controller_task_id: str,
        error_summary: str,
        *,
        updated_at: str,
    ) -> OnlineMrTaskSessionMapping:
        mapping = self._required(controller_task_id)
        return self.save(
            replace(
                mapping,
                error_summary=str(error_summary or ""),
                error_message=str(error_summary or mapping.error_message),
                updated_at=updated_at,
            )
        )

    def recover_active_as_aborted(self, *, ended_at: str, reason: str) -> list[OnlineMrTaskSessionMapping]:
        return [
            self.mark_terminal(
                mapping.controller_task_id,
                started_at=mapping.started_at or mapping.created_at,
                ended_at=ended_at,
                duration_minutes=calculate_duration_minutes(mapping.started_at or mapping.created_at, ended_at),
                stop_reason="recovered_aborted",
                force_stopped=mapping.force_stopped,
                error_summary=reason,
                mapping_state=OnlineMrMappingState.STALE,
            )
            for mapping in self.list_active()
        ]

    def list(
        self,
        *,
        states: set[OnlineMrMappingState] | None = None,
        device_id: str | int | None = None,
        limit: int = 200,
    ) -> list[OnlineMrTaskSessionMapping]:
        where = ["site_id = ?"]
        params: list[object] = [self.site_id]
        if states:
            values = sorted(state.value for state in states)
            where.append(f"mapping_state IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if device_id not in (None, ""):
            where.append("device_id = ?")
            params.append(str(device_id))
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM online_mr_task_sessions WHERE {' AND '.join(where)} ORDER BY updated_at DESC, controller_task_id LIMIT ?",
                params,
            ).fetchall()
        return [self._from_row(dict(row)) for row in rows]

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT version FROM online_mr_task_session_schema WHERE singleton = 1").fetchone()
        return int(row["version"] if row is not None else 0)

    def _required(self, controller_task_id: str) -> OnlineMrTaskSessionMapping:
        mapping = self.get_by_task(controller_task_id)
        if mapping is None:
            raise KeyError(controller_task_id)
        return mapping

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(online_mr_task_sessions)")}
        for name, definition in {
            "mr_id": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TEXT",
            "ended_at": "TEXT",
            "duration_minutes": "REAL",
            "stop_reason": "TEXT NOT NULL DEFAULT ''",
            "force_stopped": "INTEGER NOT NULL DEFAULT 0",
            "error_summary": "TEXT NOT NULL DEFAULT ''",
            "agent_task_id": "TEXT NOT NULL DEFAULT ''",
            "agent_profile_id": "TEXT NOT NULL DEFAULT ''",
            "remote_session_id": "TEXT NOT NULL DEFAULT ''",
            "remote_package_id": "TEXT NOT NULL DEFAULT ''",
            "last_remote_status": "TEXT NOT NULL DEFAULT ''",
            "last_remote_seen_at": "TEXT",
            "consecutive_status_failures": "INTEGER NOT NULL DEFAULT 0",
            "deadline_at": "TEXT",
        }.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE online_mr_task_sessions ADD COLUMN {name} {definition}")

    def _require_site(self, mapping: OnlineMrTaskSessionMapping) -> None:
        if mapping.site_id != self.site_id:
            raise ValueError("Online MR mapping 局点不匹配")

    @staticmethod
    def _values(mapping: OnlineMrTaskSessionMapping) -> tuple[object, ...]:
        return (
            mapping.controller_task_id,
            mapping.session_id,
            mapping.site_id,
            mapping.device_id,
            mapping.device_name,
            mapping.mr_id,
            mapping.mr_name,
            mapping.executor_kind.value,
            mapping.agent_id,
            mapping.agent_profile_id,
            mapping.agent_task_id,
            mapping.remote_session_id,
            mapping.remote_package_id,
            mapping.last_remote_status,
            mapping.last_remote_seen_at,
            mapping.consecutive_status_failures,
            mapping.deadline_at,
            mapping.phase.value,
            mapping.mapping_state.value,
            mapping.created_at,
            mapping.updated_at,
            mapping.started_at,
            mapping.ended_at,
            mapping.duration_minutes,
            mapping.stop_reason,
            int(mapping.force_stopped),
            mapping.terminal_at,
            mapping.error_summary,
            mapping.error_code,
            mapping.error_message,
        )

    @staticmethod
    def _from_row(row: dict[str, object]) -> OnlineMrTaskSessionMapping:
        return OnlineMrTaskSessionMapping(
            controller_task_id=str(row["controller_task_id"]),
            session_id=str(row["session_id"]) if row.get("session_id") not in (None, "") else None,
            site_id=str(row["site_id"]),
            device_id=str(row.get("device_id") or ""),
            device_name=str(row.get("device_name") or ""),
            mr_id=str(row.get("mr_id") or ""),
            mr_name=str(row.get("mr_name") or ""),
            executor_kind=OnlineMrExecutorKind(str(row["executor_kind"])),
            agent_id=str(row.get("agent_id") or ""),
            agent_profile_id=str(row.get("agent_profile_id") or ""),
            agent_task_id=str(row.get("agent_task_id") or ""),
            remote_session_id=str(row.get("remote_session_id") or ""),
            remote_package_id=str(row.get("remote_package_id") or ""),
            last_remote_status=str(row.get("last_remote_status") or ""),
            last_remote_seen_at=(
                str(row["last_remote_seen_at"])
                if row.get("last_remote_seen_at") not in (None, "")
                else None
            ),
            consecutive_status_failures=int(row.get("consecutive_status_failures") or 0),
            deadline_at=str(row["deadline_at"]) if row.get("deadline_at") not in (None, "") else None,
            phase=OnlineMrPhase(str(row["phase"])),
            mapping_state=OnlineMrMappingState(str(row["mapping_state"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=str(row["started_at"]) if row.get("started_at") not in (None, "") else None,
            ended_at=str(row["ended_at"]) if row.get("ended_at") not in (None, "") else None,
            duration_minutes=float(row["duration_minutes"]) if row.get("duration_minutes") is not None else None,
            stop_reason=str(row.get("stop_reason") or ""),
            force_stopped=bool(row.get("force_stopped")),
            terminal_at=str(row["terminal_at"]) if row.get("terminal_at") not in (None, "") else None,
            error_summary=str(row.get("error_summary") or ""),
            error_code=str(row.get("error_code") or ""),
            error_message=str(row.get("error_message") or ""),
        )


__all__ = ["OnlineMrTaskSessionRepository", "SCHEMA_VERSION"]
