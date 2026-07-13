from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
)


SCHEMA_VERSION = 1
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
    mr_name TEXT NOT NULL DEFAULT '',
    executor_kind TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL,
    mapping_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT,
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
                        controller_task_id, session_id, site_id, device_id, device_name, mr_name,
                        executor_kind, agent_id, phase, mapping_state, created_at, updated_at,
                        terminal_at, error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        session_id = ?, device_id = ?, device_name = ?, mr_name = ?, executor_kind = ?,
                        agent_id = ?, phase = ?, mapping_state = ?, updated_at = ?, terminal_at = ?,
                        error_code = ?, error_message = ?
                    WHERE controller_task_id = ? AND site_id = ?
                    """,
                    (
                        mapping.session_id,
                        mapping.device_id,
                        mapping.device_name,
                        mapping.mr_name,
                        mapping.executor_kind.value,
                        mapping.agent_id,
                        mapping.phase.value,
                        mapping.mapping_state.value,
                        mapping.updated_at,
                        mapping.terminal_at,
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

    def get_by_session(self, session_id: str) -> OnlineMrTaskSessionMapping | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM online_mr_task_sessions WHERE session_id = ? AND site_id = ?",
                (session_id, self.site_id),
            ).fetchone()
        return self._from_row(dict(row)) if row is not None else None

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
            mapping.mr_name,
            mapping.executor_kind.value,
            mapping.agent_id,
            mapping.phase.value,
            mapping.mapping_state.value,
            mapping.created_at,
            mapping.updated_at,
            mapping.terminal_at,
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
            mr_name=str(row.get("mr_name") or ""),
            executor_kind=OnlineMrExecutorKind(str(row["executor_kind"])),
            agent_id=str(row.get("agent_id") or ""),
            phase=OnlineMrPhase(str(row["phase"])),
            mapping_state=OnlineMrMappingState(str(row["mapping_state"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            terminal_at=str(row["terminal_at"]) if row.get("terminal_at") not in (None, "") else None,
            error_code=str(row.get("error_code") or ""),
            error_message=str(row.get("error_message") or ""),
        )


__all__ = ["OnlineMrTaskSessionRepository", "SCHEMA_VERSION"]
