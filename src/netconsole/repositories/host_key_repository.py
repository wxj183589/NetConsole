from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Iterator

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal


HOST_KEY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HostKeyRecord:
    id: int
    device_id: str
    management_ip: str
    ssh_port: int
    key_type: str
    current_fingerprint_sha256: str | None
    first_seen_at: str | None
    last_verified_at: str | None
    last_changed_at: str | None
    update_policy: str
    pending_token: str | None
    pending_fingerprint_sha256: str | None
    pending_key_type: str | None
    pending_status: str | None
    pending_observed_at: str | None
    revision: int


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS host_key_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS host_key_records (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    management_ip TEXT NOT NULL,
    ssh_port INTEGER NOT NULL CHECK (ssh_port BETWEEN 1 AND 65535),
    key_type TEXT NOT NULL DEFAULT '',
    current_fingerprint_sha256 TEXT,
    first_seen_at TEXT,
    last_verified_at TEXT,
    last_changed_at TEXT,
    update_policy TEXT NOT NULL DEFAULT 'AUTO_UPDATE'
        CHECK (update_policy IN ('AUTO_UPDATE', 'STRICT')),
    pending_token TEXT,
    pending_fingerprint_sha256 TEXT,
    pending_key_type TEXT,
    pending_status TEXT
        CHECK (pending_status IS NULL OR pending_status IN (
            'VERIFYING', 'PENDING_TRUST', 'PENDING_UPDATE'
        )),
    pending_observed_at TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (device_id, management_ip, ssh_port)
);

CREATE TABLE IF NOT EXISTS host_key_history (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES host_key_records(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    management_ip TEXT NOT NULL,
    ssh_port INTEGER NOT NULL,
    key_type TEXT NOT NULL,
    fingerprint_sha256 TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_fingerprint_sha256 TEXT,
    new_fingerprint_sha256 TEXT,
    observed_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    pending_token TEXT
);

CREATE INDEX IF NOT EXISTS idx_host_key_history_identity
    ON host_key_history(device_id, management_ip, ssh_port, observed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS host_key_events (
    event_id TEXT PRIMARY KEY,
    record_id INTEGER REFERENCES host_key_records(id) ON DELETE SET NULL,
    device_id TEXT NOT NULL,
    management_ip TEXT NOT NULL,
    ssh_port INTEGER NOT NULL,
    key_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_fingerprint_sha256 TEXT,
    new_fingerprint_sha256 TEXT,
    update_policy TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    pending_token TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (pending_token, event_type, result)
);

CREATE INDEX IF NOT EXISTS idx_host_key_events_identity
    ON host_key_events(device_id, management_ip, ssh_port, created_at DESC, event_id DESC);
"""


class HostKeyRepository:
    """SQLite owner for Host Key metadata and audit history.

    The managed known_hosts file remains a compatibility cache for Paramiko.
    This database is the authority for device identity, policy, pending state,
    current fingerprint and historical events.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.write_transaction() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0] or 0)
            if version > HOST_KEY_SCHEMA_VERSION:
                raise RuntimeError(
                    f"不支持的 Host Key schema 版本：{version} > {HOST_KEY_SCHEMA_VERSION}"
                )
            for statement in SCHEMA_SQL.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                """
                INSERT INTO host_key_schema_meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(HOST_KEY_SCHEMA_VERSION),),
            )
            connection.execute(f"PRAGMA user_version = {HOST_KEY_SCHEMA_VERSION}")

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = connect_sqlite(self.path, timeout=30, foreign_keys=True)
        initialize_sqlite_wal(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = connect_sqlite(self.path, timeout=30, foreign_keys=True)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def record_from_row(row: sqlite3.Row | None) -> HostKeyRecord | None:
        if row is None:
            return None
        return HostKeyRecord(
            id=int(row["id"]),
            device_id=str(row["device_id"]),
            management_ip=str(row["management_ip"]),
            ssh_port=int(row["ssh_port"]),
            key_type=str(row["key_type"] or ""),
            current_fingerprint_sha256=(
                str(row["current_fingerprint_sha256"])
                if row["current_fingerprint_sha256"]
                else None
            ),
            first_seen_at=(str(row["first_seen_at"]) if row["first_seen_at"] else None),
            last_verified_at=(
                str(row["last_verified_at"]) if row["last_verified_at"] else None
            ),
            last_changed_at=(
                str(row["last_changed_at"]) if row["last_changed_at"] else None
            ),
            update_policy=str(row["update_policy"]),
            pending_token=(str(row["pending_token"]) if row["pending_token"] else None),
            pending_fingerprint_sha256=(
                str(row["pending_fingerprint_sha256"])
                if row["pending_fingerprint_sha256"]
                else None
            ),
            pending_key_type=(
                str(row["pending_key_type"]) if row["pending_key_type"] else None
            ),
            pending_status=(
                str(row["pending_status"]) if row["pending_status"] else None
            ),
            pending_observed_at=(
                str(row["pending_observed_at"]) if row["pending_observed_at"] else None
            ),
            revision=int(row["revision"] or 0),
        )

    def get(self, device_id: str, management_ip: str, ssh_port: int) -> HostKeyRecord | None:
        with self.read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM host_key_records
                WHERE device_id = ? AND management_ip = ? AND ssh_port = ?
                """,
                (device_id, management_ip, ssh_port),
            ).fetchone()
        return self.record_from_row(row)

    def list_history(
        self,
        device_id: str,
        management_ip: str | None = None,
        ssh_port: int | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        clauses = ["device_id = ?"]
        params: list[object] = [device_id]
        if management_ip:
            clauses.append("management_ip = ?")
            params.append(management_ip)
        if ssh_port is not None:
            clauses.append("ssh_port = ?")
            params.append(int(ssh_port))
        params.append(min(max(int(limit), 1), 1000))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, device_id, management_ip, ssh_port, key_type,
                       fingerprint_sha256, event_type, old_fingerprint_sha256,
                       new_fingerprint_sha256, observed_at, reason, result,
                       pending_token
                FROM host_key_history
                WHERE {' AND '.join(clauses)}
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(
        self,
        device_id: str,
        management_ip: str | None = None,
        ssh_port: int | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        clauses = ["device_id = ?"]
        params: list[object] = [device_id]
        if management_ip:
            clauses.append("management_ip = ?")
            params.append(management_ip)
        if ssh_port is not None:
            clauses.append("ssh_port = ?")
            params.append(int(ssh_port))
        params.append(min(max(int(limit), 1), 1000))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT event_id, record_id, device_id, management_ip, ssh_port,
                       key_type, event_type, old_fingerprint_sha256,
                       new_fingerprint_sha256, update_policy, result, reason,
                       pending_token, created_at
                FROM host_key_events
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC, event_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]


__all__ = ["HOST_KEY_SCHEMA_VERSION", "HostKeyRecord", "HostKeyRepository"]
