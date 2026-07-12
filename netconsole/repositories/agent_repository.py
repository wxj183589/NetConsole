from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.models.agent import AgentAuthenticationType, AgentConfig, AgentRuntimeSnapshot, AgentStatus


AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO agent_schema_meta(key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    authentication_type TEXT NOT NULL DEFAULT 'none',
    credential_reference TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_configs_base_url_active
    ON agent_configs(base_url) WHERE archived_at = '';
CREATE INDEX IF NOT EXISTS idx_agent_configs_enabled_updated
    ON agent_configs(enabled, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_runtime_snapshots (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_seen_at TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER,
    version TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    architecture TEXT NOT NULL DEFAULT '',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    last_error_code TEXT NOT NULL DEFAULT '',
    last_error_message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(agent_id) REFERENCES agent_configs(agent_id) ON DELETE CASCADE
);
"""


class AgentRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.initialize()

    def _connect(self):
        return connect_sqlite(self.db_path, foreign_keys=True)

    def initialize(self) -> None:
        def operation() -> None:
            with self._connect() as conn:
                initialize_sqlite_wal(conn)
                conn.executescript(AGENT_SCHEMA)
                conn.commit()

        run_sqlite_with_retry(operation)

    def create(self, config: AgentConfig) -> AgentConfig:
        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO agent_configs (
                        agent_id, name, base_url, enabled, authentication_type,
                        credential_reference, tags_json, note, created_at, updated_at, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._config_values(config),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return config

    def update(self, config: AgentConfig) -> AgentConfig:
        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    UPDATE agent_configs SET
                        name = ?, base_url = ?, enabled = ?, authentication_type = ?,
                        credential_reference = ?, tags_json = ?, note = ?, updated_at = ?, archived_at = ?
                    WHERE agent_id = ?
                    """,
                    (
                        config.name,
                        config.base_url,
                        int(config.enabled),
                        config.authentication_type.value,
                        config.credential_reference,
                        json.dumps(config.tags, ensure_ascii=False, separators=(",", ":")),
                        config.note,
                        config.updated_at,
                        config.archived_at,
                        config.agent_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(config.agent_id)
                conn.commit()

        run_sqlite_with_retry(operation)
        return config

    def get(self, agent_id: str, *, include_archived: bool = False) -> AgentConfig | None:
        where = "agent_id = ?" if include_archived else "agent_id = ? AND archived_at = ''"
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM agent_configs WHERE {where}", (agent_id,)).fetchone()
        return self._config_from_row(dict(row)) if row is not None else None

    def list(self, *, include_archived: bool = False) -> list[AgentConfig]:
        where = "" if include_archived else "WHERE archived_at = ''"
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM agent_configs {where} ORDER BY name COLLATE NOCASE, agent_id").fetchall()
        return [self._config_from_row(dict(row)) for row in rows]

    def archive(self, agent_id: str, archived_at: str) -> bool:
        def operation() -> bool:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    "UPDATE agent_configs SET enabled = 0, archived_at = ?, updated_at = ? WHERE agent_id = ? AND archived_at = ''",
                    (archived_at, archived_at, agent_id),
                )
                conn.commit()
                return cursor.rowcount == 1

        return run_sqlite_with_retry(operation)

    def save_runtime(self, snapshot: AgentRuntimeSnapshot) -> AgentRuntimeSnapshot:
        def operation() -> None:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO agent_runtime_snapshots (
                        agent_id, status, last_seen_at, last_checked_at, latency_ms, version,
                        platform, architecture, capabilities_json, last_error_code,
                        last_error_message, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        status = excluded.status,
                        last_seen_at = excluded.last_seen_at,
                        last_checked_at = excluded.last_checked_at,
                        latency_ms = excluded.latency_ms,
                        version = excluded.version,
                        platform = excluded.platform,
                        architecture = excluded.architecture,
                        capabilities_json = excluded.capabilities_json,
                        last_error_code = excluded.last_error_code,
                        last_error_message = excluded.last_error_message,
                        updated_at = excluded.updated_at
                    """,
                    (
                        snapshot.agent_id,
                        snapshot.status.value,
                        snapshot.last_seen_at,
                        snapshot.last_checked_at,
                        snapshot.latency_ms,
                        snapshot.version,
                        snapshot.platform,
                        snapshot.architecture,
                        json.dumps(snapshot.capabilities, ensure_ascii=False, separators=(",", ":")),
                        snapshot.last_error_code,
                        snapshot.last_error_message,
                        snapshot.updated_at,
                    ),
                )
                conn.commit()

        run_sqlite_with_retry(operation)
        return snapshot

    def get_runtime(self, agent_id: str) -> AgentRuntimeSnapshot | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agent_runtime_snapshots WHERE agent_id = ?", (agent_id,)).fetchone()
        return self._runtime_from_row(dict(row)) if row is not None else None

    def list_with_runtime(self) -> list[tuple[AgentConfig, AgentRuntimeSnapshot | None]]:
        return [(config, self.get_runtime(config.agent_id)) for config in self.list()]

    @staticmethod
    def _config_values(config: AgentConfig) -> tuple[object, ...]:
        return (
            config.agent_id,
            config.name,
            config.base_url,
            int(config.enabled),
            config.authentication_type.value,
            config.credential_reference,
            json.dumps(config.tags, ensure_ascii=False, separators=(",", ":")),
            config.note,
            config.created_at,
            config.updated_at,
            config.archived_at,
        )

    @staticmethod
    def _config_from_row(row: dict[str, Any]) -> AgentConfig:
        return AgentConfig(
            agent_id=str(row["agent_id"]),
            name=str(row["name"]),
            base_url=str(row["base_url"]),
            enabled=bool(row["enabled"]),
            authentication_type=AgentAuthenticationType(str(row["authentication_type"])),
            credential_reference=str(row["credential_reference"]),
            tags=list(json.loads(row["tags_json"] or "[]")),
            note=str(row["note"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            archived_at=str(row["archived_at"]),
        )

    @staticmethod
    def _runtime_from_row(row: dict[str, Any]) -> AgentRuntimeSnapshot:
        return AgentRuntimeSnapshot(
            agent_id=str(row["agent_id"]),
            status=AgentStatus(str(row["status"])),
            last_seen_at=str(row["last_seen_at"]),
            last_checked_at=str(row["last_checked_at"]),
            latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
            version=str(row["version"]),
            platform=str(row["platform"]),
            architecture=str(row["architecture"]),
            capabilities=dict(json.loads(row["capabilities_json"] or "{}")),
            last_error_code=str(row["last_error_code"]),
            last_error_message=str(row["last_error_message"]),
            updated_at=str(row["updated_at"]),
        )
