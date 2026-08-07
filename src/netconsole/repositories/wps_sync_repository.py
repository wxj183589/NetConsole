from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data
from netconsole.models.wps_sync import WpsSyncTarget, WpsTargetType


WPS_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS wps_credentials (
    credential_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    encrypted_token BLOB,
    token_suffix TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_verified_at TEXT NOT NULL DEFAULT '',
    last_verify_status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wps_sync_targets (
    target_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    business_key TEXT NOT NULL,
    target_code TEXT NOT NULL,
    target_type TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    document_open_url TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    expected_document_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    protocol_version INTEGER NOT NULL DEFAULT 2,
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    last_test_at TEXT NOT NULL DEFAULT '',
    last_test_status TEXT NOT NULL DEFAULT '',
    last_test_message TEXT NOT NULL DEFAULT '',
    last_sync_at TEXT NOT NULL DEFAULT '',
    last_sync_status TEXT NOT NULL DEFAULT '',
    last_sync_revision TEXT NOT NULL DEFAULT '',
    runtime_capability TEXT NOT NULL DEFAULT 'DEPLOYMENT_PENDING',
    last_runtime_probe_at TEXT NOT NULL DEFAULT '',
    binding_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    remote_binding_id TEXT NOT NULL DEFAULT '',
    remote_site_id TEXT NOT NULL DEFAULT '',
    remote_site_name TEXT NOT NULL DEFAULT '',
    remote_business_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, business_key, target_code),
    FOREIGN KEY (credential_id) REFERENCES wps_credentials(credential_id)
);
CREATE TABLE IF NOT EXISTS wps_sync_batches (
    batch_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    business_key TEXT NOT NULL,
    snapshot_revision TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    snapshot_generated_at TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 0,
    success_target_count INTEGER NOT NULL DEFAULT 0,
    failed_target_count INTEGER NOT NULL DEFAULT 0,
    result_summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS wps_sync_target_runs (
    target_batch_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_code TEXT NOT NULL,
    target_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    remote_document_id TEXT NOT NULL DEFAULT '',
    remote_script_version TEXT NOT NULL DEFAULT '',
    written_object_count INTEGER NOT NULL DEFAULT 0,
    written_row_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    sanitized_error_message TEXT NOT NULL DEFAULT '',
    result_summary TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (batch_id) REFERENCES wps_sync_batches(batch_id),
    FOREIGN KEY (target_id) REFERENCES wps_sync_targets(target_id)
);
CREATE INDEX IF NOT EXISTS idx_wps_sync_batches_site_business_requested
ON wps_sync_batches(site_id, business_key, requested_at DESC);
"""


class WpsSyncRepository:
    def __init__(
        self,
        paths: PathResolver,
        site_id: str,
        *,
        protect: Callable[[bytes, bytes], bytes] = protect_windows_data,
        unprotect: Callable[[bytes, bytes], bytes] = unprotect_windows_data,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id or "").strip()
        self.path = paths.site_sync_dir(self.site_id) / "wps_sync.sqlite"
        self._protect = protect
        self._unprotect = unprotect

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            initialize_sqlite_wal(connection)
            connection.executescript(WPS_SYNC_SCHEMA)
            self._ensure_target_columns(connection)
            connection.commit()

    @staticmethod
    def _ensure_target_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(wps_sync_targets)").fetchall()
        }
        for name, definition in {
            "runtime_capability": "TEXT NOT NULL DEFAULT 'DEPLOYMENT_PENDING'",
            "last_runtime_probe_at": "TEXT NOT NULL DEFAULT ''",
            "binding_status": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
            "remote_binding_id": "TEXT NOT NULL DEFAULT ''",
            "remote_site_id": "TEXT NOT NULL DEFAULT ''",
            "remote_site_name": "TEXT NOT NULL DEFAULT ''",
            "remote_business_key": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE wps_sync_targets ADD COLUMN {name} {definition}")

    def upsert_target(
        self,
        *,
        business_key: str,
        target_code: str,
        target_type: WpsTargetType,
        target_name: str,
        document_open_url: str,
        webhook_url: str,
        expected_document_id: str,
        enabled: bool = True,
        timeout_seconds: int = 30,
        token: str | None = None,
        credential_id: str | None = None,
    ) -> WpsSyncTarget:
        self.initialize()
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT target_id, credential_id FROM wps_sync_targets "
                "WHERE site_id = ? AND business_key = ? AND target_code = ?",
                (self.site_id, business_key, target_code),
            ).fetchone()
            target_id = str(row["target_id"]) if row else f"wst_{uuid4().hex}"
            credential_id = (
                str(credential_id)
                if credential_id is not None
                else str(row["credential_id"])
                if row
                else f"wsc_{uuid4().hex}"
            )
            connection.execute(
                """
                INSERT INTO wps_credentials (
                    credential_id, name, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(credential_id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (credential_id, "WPS AirScript", now, now),
            )
            if token is not None:
                normalized = str(token).strip()
                if not normalized:
                    raise ValueError("WPS Token 不能为空")
                encrypted = self._protect(
                    normalized.encode("utf-8"),
                    self._entropy(credential_id),
                )
                connection.execute(
                    "UPDATE wps_credentials SET encrypted_token = ?, token_suffix = ?, "
                    "updated_at = ? WHERE credential_id = ?",
                    (encrypted, normalized[-4:], now, credential_id),
                )
            connection.execute(
                """
                INSERT INTO wps_sync_targets (
                    target_id, site_id, business_key, target_code, target_type,
                    credential_id, target_name, document_open_url, webhook_url,
                    expected_document_id, enabled, protocol_version,
                    timeout_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?, ?, ?)
                ON CONFLICT(site_id, business_key, target_code) DO UPDATE SET
                    target_type = excluded.target_type,
                    credential_id = excluded.credential_id,
                    target_name = excluded.target_name,
                    document_open_url = excluded.document_open_url,
                    webhook_url = excluded.webhook_url,
                    expected_document_id = excluded.expected_document_id,
                    enabled = excluded.enabled,
                    timeout_seconds = excluded.timeout_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    target_id,
                    self.site_id,
                    business_key,
                    target_code,
                    target_type.value,
                    credential_id,
                    target_name,
                    document_open_url,
                    webhook_url,
                    expected_document_id,
                    int(enabled),
                    max(5, min(int(timeout_seconds), 120)),
                    now,
                    now,
                ),
            )
            connection.commit()
        return self.get_target(business_key, target_code)

    def list_targets(self, business_key: str) -> list[WpsSyncTarget]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, c.token_suffix,
                       CASE WHEN c.encrypted_token IS NULL THEN 0 ELSE 1 END AS token_configured
                FROM wps_sync_targets t
                JOIN wps_credentials c ON c.credential_id = t.credential_id
                WHERE t.site_id = ? AND t.business_key = ?
                ORDER BY t.target_code
                """,
                (self.site_id, business_key),
            ).fetchall()
        return [_target_from_row(row) for row in rows]

    def get_target(self, business_key: str, target_code: str) -> WpsSyncTarget:
        targets = [
            target
            for target in self.list_targets(business_key)
            if target.target_code == target_code
        ]
        if not targets:
            raise KeyError(target_code)
        return targets[0]

    def resolve_token(self, target: WpsSyncTarget) -> str:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_token FROM wps_credentials WHERE credential_id = ?",
                (target.credential_id,),
            ).fetchone()
        if row is None or row["encrypted_token"] is None:
            return ""
        clear = self._unprotect(
            bytes(row["encrypted_token"]),
            self._entropy(target.credential_id),
        )
        return clear.decode("utf-8")

    def update_target_test(self, target_id: str, *, status: str, message: str) -> None:
        self._update_target(
            target_id,
            "last_test_at = ?, last_test_status = ?, last_test_message = ?",
            (_now(), status, _sanitize(message)),
        )

    def update_target_sync(
        self,
        target_id: str,
        *,
        status: str,
        revision: str,
    ) -> None:
        self._update_target(
            target_id,
            "last_sync_at = ?, last_sync_status = ?, last_sync_revision = ?",
            (_now(), status, revision),
        )

    def update_target_remote_state(
        self,
        target_id: str,
        *,
        binding_status: str,
        result: dict[str, object],
        runtime_capability: str | None = None,
    ) -> None:
        assignments = [
            "binding_status = ?",
            "remote_binding_id = ?",
            "remote_site_id = ?",
            "remote_site_name = ?",
            "remote_business_key = ?",
        ]
        values: list[object] = [
            str(binding_status or "UNKNOWN"),
            str(result.get("binding_id") or ""),
            str(result.get("site_id") or ""),
            str(result.get("site_name") or ""),
            str(result.get("business_key") or ""),
        ]
        if runtime_capability is not None:
            assignments.extend(["runtime_capability = ?", "last_runtime_probe_at = ?"])
            values.extend([str(runtime_capability), _now()])
        self._update_target(target_id, ", ".join(assignments), values)

    def set_runtime_capability(self, target_id: str, value: str) -> None:
        self._update_target(
            target_id,
            "runtime_capability = ?, last_runtime_probe_at = ?",
            (str(value), _now()),
        )

    def create_batch(
        self,
        *,
        batch_id: str,
        business_key: str,
        revision: str,
        snapshot_sha256: str,
        snapshot_generated_at: str,
        target_count: int,
    ) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wps_sync_batches (
                    batch_id, site_id, business_key, snapshot_revision,
                    snapshot_sha256, snapshot_generated_at, requested_at,
                    status, target_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)
                """,
                (
                    batch_id,
                    self.site_id,
                    business_key,
                    revision,
                    snapshot_sha256,
                    snapshot_generated_at,
                    _now(),
                    target_count,
                ),
            )
            connection.commit()

    def create_target_run(
        self,
        *,
        target_batch_id: str,
        batch_id: str,
        target: WpsSyncTarget,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wps_sync_target_runs (
                    target_batch_id, batch_id, target_id, target_code,
                    target_type, started_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING')
                """,
                (
                    target_batch_id,
                    batch_id,
                    target.target_id,
                    target.target_code,
                    target.target_type.value,
                    _now(),
                ),
            )
            connection.commit()

    def complete_target_run(
        self,
        target_batch_id: str,
        *,
        status: str,
        result: dict[str, object],
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        import json

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE wps_sync_target_runs SET
                    completed_at = ?, status = ?, remote_document_id = ?,
                    remote_script_version = ?, written_object_count = ?,
                    written_row_count = ?, error_code = ?,
                    sanitized_error_message = ?, result_summary = ?
                WHERE target_batch_id = ?
                """,
                (
                    _now(),
                    status,
                    str(result.get("document_id") or ""),
                    str(result.get("script_version") or ""),
                    int(result.get("written_object_count") or 0),
                    int(result.get("written_row_count") or 0),
                    error_code,
                    _sanitize(error_message),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    target_batch_id,
                ),
            )
            connection.commit()

    def complete_batch(
        self,
        batch_id: str,
        *,
        status: str,
        success_count: int,
        failed_count: int,
        summary: dict[str, object],
    ) -> None:
        import json

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE wps_sync_batches SET completed_at = ?, status = ?,
                    success_target_count = ?, failed_target_count = ?,
                    result_summary = ? WHERE batch_id = ?
                """,
                (
                    _now(),
                    status,
                    success_count,
                    failed_count,
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    batch_id,
                ),
            )
            connection.commit()

    def recent_batches(self, business_key: str, limit: int = 10) -> list[dict[str, object]]:
        import json

        self.initialize()
        with self._connect() as connection:
            batches = connection.execute(
                "SELECT * FROM wps_sync_batches WHERE site_id = ? AND business_key = ? "
                "ORDER BY requested_at DESC LIMIT ?",
                (self.site_id, business_key, max(1, min(int(limit), 100))),
            ).fetchall()
            result: list[dict[str, object]] = []
            for batch in batches:
                item = dict(batch)
                summary = str(item.pop("result_summary", "") or "")
                item["result_summary"] = json.loads(summary) if summary else {}
                runs = connection.execute(
                    "SELECT * FROM wps_sync_target_runs WHERE batch_id = ? ORDER BY target_code",
                    (item["batch_id"],),
                ).fetchall()
                item["targets"] = [dict(row) for row in runs]
                for run in item["targets"]:
                    raw = str(run.pop("result_summary", "") or "")
                    run["result_summary"] = json.loads(raw) if raw else {}
                result.append(item)
        return result

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.path, foreign_keys=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _entropy(self, credential_id: str) -> bytes:
        return f"NetConsole:WPS:{self.site_id}:{credential_id}".encode("utf-8")

    def _update_target(
        self,
        target_id: str,
        assignment: str,
        values: Iterable[object],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                f"UPDATE wps_sync_targets SET {assignment}, updated_at = ? WHERE target_id = ?",
                (*values, _now(), target_id),
            )
            connection.commit()


def _target_from_row(row: sqlite3.Row) -> WpsSyncTarget:
    return WpsSyncTarget(
        target_id=str(row["target_id"]),
        site_id=str(row["site_id"]),
        business_key=str(row["business_key"]),
        target_code=str(row["target_code"]),
        target_type=WpsTargetType(str(row["target_type"])),
        credential_id=str(row["credential_id"]),
        target_name=str(row["target_name"]),
        document_open_url=str(row["document_open_url"]),
        webhook_url=str(row["webhook_url"]),
        expected_document_id=str(row["expected_document_id"]),
        enabled=bool(row["enabled"]),
        protocol_version=int(row["protocol_version"]),
        timeout_seconds=int(row["timeout_seconds"]),
        token_configured=bool(row["token_configured"]),
        token_suffix=str(row["token_suffix"] or ""),
        last_test_at=str(row["last_test_at"] or ""),
        last_test_status=str(row["last_test_status"] or ""),
        last_test_message=str(row["last_test_message"] or ""),
        last_sync_at=str(row["last_sync_at"] or ""),
        last_sync_status=str(row["last_sync_status"] or ""),
        last_sync_revision=str(row["last_sync_revision"] or ""),
        runtime_capability=str(row["runtime_capability"] or "DEPLOYMENT_PENDING"),
        last_runtime_probe_at=str(row["last_runtime_probe_at"] or ""),
        binding_status=str(row["binding_status"] or "UNKNOWN"),
        remote_binding_id=str(row["remote_binding_id"] or ""),
        remote_site_id=str(row["remote_site_id"] or ""),
        remote_site_name=str(row["remote_site_name"] or ""),
        remote_business_key=str(row["remote_business_key"] or ""),
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanitize(value: str) -> str:
    text = str(value or "").replace("AirScript-Token", "credential")
    return text[:500]


__all__ = ["WPS_SYNC_SCHEMA", "WpsSyncRepository"]
