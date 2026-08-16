"""Bounded, change-aware history storage for site device databases.

The primary database remains authoritative for current state.  History events
are first committed to a small outbox in that same transaction and are later
drained into a month-partitioned shard.  This deliberately avoids a cross-file
SQLite transaction and keeps startup free of history scans or maintenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import zlib
from calendar import monthrange
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.repositories.history_legacy_migration_repository import (
    HistoryLegacyMigrationRepository,
    SHARD_QUERY_AUTHORITY_STATES,
)

DEFAULT_HEARTBEAT_SECONDS = {
    "device_fact": 3600,
    "device_interface": 3600,
    "device_optical": 900,
    "device_lldp": 1800,
    "fit_ap_resource": 1800,
    "fit_ap_radio": 1800,
    "fit_ap_optical": 900,
    "fit_ap_lldp": 1800,
}

# A heartbeat is the sampling policy for continuous telemetry.  Discrete
# state/configuration fields are passed explicitly by each producer and are
# recorded immediately when they change.
TELEMETRY_SAMPLING_SECONDS = dict(DEFAULT_HEARTBEAT_SECONDS)
OUTBOX_PRESSURE_HIGH_WATERMARK = 5_000
# Unattended draining runs on a low-frequency scheduler.  Its smallest batch
# must still exceed the measured steady event rate; otherwise the outbox would
# simply move the historical growth back into devices.db.
UNATTENDED_DRAIN_BASE_LIMIT = 100
UNATTENDED_DRAIN_ELEVATED_LIMIT = 250
UNATTENDED_DRAIN_MAX_LIMIT = 500
UNATTENDED_SHARD_BATCH_LIMIT = 100
UNATTENDED_DRAIN_MAX_ELAPSED_SECONDS = 2.0
UNATTENDED_ELEVATED_AGE_SECONDS = 300
UNATTENDED_URGENT_AGE_SECONDS = 900

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_outbox (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_outbox_created
    ON history_outbox(created_at, event_id);
CREATE TABLE IF NOT EXISTS history_state (
    kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    last_recorded_at TEXT NOT NULL,
    PRIMARY KEY(kind, entity_key)
);
"""

CATALOG_SCHEMA = """
PRAGMA user_version = 1;
CREATE TABLE IF NOT EXISTS history_catalog (
    shard_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'site_history',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    segment INTEGER NOT NULL DEFAULT 1,
    relative_path TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    content_fingerprint TEXT NOT NULL DEFAULT '',
    min_business_time TEXT NOT NULL DEFAULT '',
    max_business_time TEXT NOT NULL DEFAULT '',
    authority_revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    sealed_at TEXT
);
CREATE TABLE IF NOT EXISTS history_migration_journal (
    source_table TEXT PRIMARY KEY,
    last_source_id INTEGER NOT NULL DEFAULT 0,
    rows_copied INTEGER NOT NULL DEFAULT 0,
    rows_verified INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0,
    rows_deleted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history_migration_skips (
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(source_table, source_id)
);
"""

SHARD_SCHEMA_V1 = """
PRAGMA user_version = 1;
CREATE TABLE IF NOT EXISTS history_events (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_events_entity_time
    ON history_events(kind, entity_key, collected_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_history_events_time
    ON history_events(collected_at DESC, event_id DESC);
"""

STORAGE_SCHEMA_VERSION = 2
PAYLOAD_SCHEMA_VERSION = 2
PAYLOAD_CODEC_JSON = 0
PAYLOAD_CODEC_ZLIB_JSON = 1
_PAYLOAD_ENVELOPE_FIELDS = frozenset(
    {"collected_at", "legacy_source_table", "legacy_source_id"}
)

CATALOG_QUERYABLE_STATES = frozenset(
    {"ACTIVE", "CLOSED", "ARCHIVED", "OPEN", "SEALING", "SEALED", "VERIFIED"}
)
CATALOG_WRITABLE_STATES = frozenset({"ACTIVE", "OPEN"})

SHARD_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS history_storage_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history_kinds_v2 (
    kind_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS history_entities_v2 (
    entity_id INTEGER PRIMARY KEY,
    kind_id INTEGER NOT NULL,
    entity_key TEXT NOT NULL,
    UNIQUE(kind_id, entity_key),
    FOREIGN KEY(kind_id) REFERENCES history_kinds_v2(kind_id)
);
CREATE TABLE IF NOT EXISTS history_event_types_v2 (
    event_type_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS history_payload_schemas_v2 (
    payload_schema_id INTEGER PRIMARY KEY,
    payload_schema_version INTEGER NOT NULL,
    fields_json TEXT NOT NULL,
    UNIQUE(payload_schema_version, fields_json)
);
CREATE TABLE IF NOT EXISTS history_events_v2 (
    event_id BLOB PRIMARY KEY,
    kind_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    event_type_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    payload_schema_id INTEGER NOT NULL,
    payload_codec INTEGER NOT NULL,
    payload BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(kind_id) REFERENCES history_kinds_v2(kind_id),
    FOREIGN KEY(entity_id) REFERENCES history_entities_v2(entity_id),
    FOREIGN KEY(event_type_id) REFERENCES history_event_types_v2(event_type_id),
    FOREIGN KEY(payload_schema_id) REFERENCES history_payload_schemas_v2(payload_schema_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_history_events_v2_entity_time
    ON history_events_v2(entity_id, collected_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_history_events_v2_kind_time
    ON history_events_v2(kind_id, collected_at DESC, event_id DESC);
CREATE TABLE IF NOT EXISTS history_event_provenance_v2 (
    event_id BLOB PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    FOREIGN KEY(event_id) REFERENCES history_events_v2(event_id) ON DELETE CASCADE
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS ux_history_event_provenance_v2_source
    ON history_event_provenance_v2(source_table, source_id);
"""


LEGACY_HISTORY_TABLES = frozenset(
    {
        "device_facts_history",
        "device_interfaces_history",
        "device_optical_modules_history",
        "device_lldp_neighbors_history",
        "ac_fit_ap_resource_history",
        "ac_fit_ap_radio_history",
        "ac_fit_ap_lldp_history",
        "ac_fit_ap_optical_history",
        "ap_lldp_history",
        "ap_optical_history",
    }
)

KIND_CANONICAL_LEGACY_SOURCE = {
    "device_fact": "device_facts_history",
    "device_interface": "device_interfaces_history",
    "device_optical": "device_optical_modules_history",
    "device_lldp": "device_lldp_neighbors_history",
    "fit_ap_resource": "ac_fit_ap_resource_history",
    "fit_ap_radio": "ac_fit_ap_radio_history",
    "fit_ap_lldp": "ac_fit_ap_lldp_history",
    "fit_ap_optical": "ac_fit_ap_optical_history",
}


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return (
            parsed.astimezone().replace(tzinfo=None)
            if parsed.tzinfo is not None
            else parsed
        )
    except (TypeError, ValueError):
        return None


def _local_now() -> datetime:
    """Keep legacy local ISO timestamps while avoiding implicit clock semantics."""

    return datetime.now(UTC).astimezone().replace(tzinfo=None)


def _period(value: str) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m") if parsed else _local_now().strftime("%Y-%m")


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def fingerprint(
    payload: dict[str, Any],
    *,
    ignored: Iterable[str] = (),
    meaningful_fields: Iterable[str] | None = None,
) -> str:
    ignored_keys = {
        "id",
        "created_at",
        "updated_at",
        "collected_at",
        "collect_run_uuid",
        "raw_log_path",
        "session_id",
        "snapshot_uuid",
        "history_uuid",
        *ignored,
    }
    selected = set(meaningful_fields or ())
    stable = {
        key: _json_value(value)
        for key, value in payload.items()
        if key not in ignored_keys and (not selected or key in selected)
    }
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoryDrainResult:
    written: int = 0
    pending: int = 0
    paused: bool = False
    degraded: bool = False
    oldest_pending_age_seconds: int = 0
    attempts: int = 0
    pressure: str = "normal"
    elapsed_ms: int = 0
    budget_exceeded: bool = False
    shard_commits: int = 0


@dataclass(frozen=True)
class HistoryOutboxDiagnostics:
    pending: int = 0
    oldest_pending_age_seconds: int = 0
    attempts: int = 0
    pressure: str = "normal"


@dataclass(frozen=True)
class HistoryMigrationCheckpoint:
    """A copy/verify checkpoint. This phase intentionally has no delete API."""

    source_table: str
    last_source_id: int = 0
    rows_copied: int = 0
    rows_verified: int = 0
    rows_skipped: int = 0
    rows_deleted: int = 0
    status: str = "pending"
    last_error: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class HistoryMigrationResult:
    """Result of one explicitly scheduled, bounded legacy copy batch."""

    source_table: str
    copied: int = 0
    verified: int = 0
    skipped: int = 0
    pending: bool = False
    paused: bool = False
    degraded: bool = False
    checkpoint: HistoryMigrationCheckpoint | None = None


@dataclass(frozen=True)
class _LegacySourceSpec:
    kind: str
    entity_fields: tuple[str, ...]


_LEGACY_SOURCE_SPECS = {
    "device_facts_history": _LegacySourceSpec("device_fact", ("device_uuid",)),
    "device_interfaces_history": _LegacySourceSpec(
        "device_interface", ("device_uuid", "interface_name")
    ),
    "device_optical_modules_history": _LegacySourceSpec(
        "device_optical", ("device_uuid", "interface_name")
    ),
    "device_lldp_neighbors_history": _LegacySourceSpec(
        "device_lldp", ("device_uuid", "local_interface")
    ),
    "ac_fit_ap_resource_history": _LegacySourceSpec(
        "fit_ap_resource", ("ac_device_uuid", "ap_uuid")
    ),
    "ac_fit_ap_radio_history": _LegacySourceSpec("fit_ap_radio", ("ap_uuid", "rid")),
    "ac_fit_ap_lldp_history": _LegacySourceSpec("fit_ap_lldp", ("ap_uuid",)),
    "ap_lldp_history": _LegacySourceSpec("fit_ap_lldp", ("ap_uuid",)),
    "ac_fit_ap_optical_history": _LegacySourceSpec("fit_ap_optical", ("ap_uuid",)),
    "ap_optical_history": _LegacySourceSpec("fit_ap_optical", ("ap_uuid",)),
}


class HistoryStore:
    """Owns outbox, shard and catalog access for one resolved site database."""

    def __init__(
        self,
        database_path: Path,
        *,
        site_id: str = "",
        history_root: Path | None = None,
        heartbeat_seconds: dict[str, int] | None = None,
        clock: Callable[[], datetime] | None = None,
        segment_max_bytes: int | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.site_id = str(site_id or self.database_path.parent.parent.name)
        self.history_root = Path(history_root or self.database_path.parent / "history")
        self.heartbeat_seconds = {**TELEMETRY_SAMPLING_SECONDS, **(heartbeat_seconds or {})}
        self._clock = clock
        configured_segment_bytes = (
            int(segment_max_bytes) if segment_max_bytes is not None else None
        )
        if configured_segment_bytes is not None and configured_segment_bytes <= 0:
            raise ValueError("history segment_max_bytes must be a positive integer")
        self.segment_max_bytes = configured_segment_bytes
        self._last_query_errors: tuple[str, ...] = ()

    def _now(self) -> datetime:
        value = (self._clock or _local_now)()
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> HistoryStore:
        """Use only for connection-local helpers; callers should prefer __init__."""

        raise TypeError("HistoryStore.from_connection requires the database path")

    def ensure_outbox(self, conn: sqlite3.Connection) -> None:
        # executescript commits a pending sqlite3 transaction.  The outbox must
        # share the caller's current-state transaction, so install this small
        # additive schema statement-by-statement.  IF NOT EXISTS makes first
        # collection writes safe when several workers reach a new site at once.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history_outbox (
                event_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_history_outbox_created
            ON history_outbox(created_at, event_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history_state (
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                last_recorded_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_key)
            )
            """
        )

    def record_event(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        entity_key: str,
        payload: dict[str, Any],
        collected_at: str,
        heartbeat_seconds: int | None = None,
        meaningful_fields: Iterable[str] | None = None,
    ) -> bool:
        """Queue only changes or a per-kind low-frequency heartbeat."""

        self.ensure_outbox(conn)
        kind = str(kind).strip()
        entity_key = str(entity_key).strip()
        if not kind or not entity_key:
            return False
        now = str(collected_at or _local_now().isoformat(timespec="seconds"))
        digest = fingerprint(payload, meaningful_fields=meaningful_fields)
        previous = conn.execute(
            "SELECT fingerprint, last_recorded_at FROM history_state WHERE kind=? AND entity_key=?",
            (kind, entity_key),
        ).fetchone()
        event_type = "change"
        should_record = previous is None or str(previous[0]) != digest
        if not should_record:
            interval = int(
                heartbeat_seconds
                if heartbeat_seconds is not None
                else self.heartbeat_seconds.get(kind, 3600)
            )
            previous_time = _parse_time(str(previous[1]))
            current_time = _parse_time(now)
            should_record = bool(
                previous_time is None
                or current_time is None
                or current_time - previous_time >= timedelta(seconds=max(0, interval))
            )
            event_type = "heartbeat"
        if not should_record:
            return False
        created_at = self._now().isoformat(timespec="seconds")
        event_id = hashlib.sha256(
            f"{kind}|{entity_key}|{digest}|{event_type}|{now}".encode()
        ).hexdigest()
        encoded = json.dumps(_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        conn.execute(
            """
            INSERT OR IGNORE INTO history_outbox
                (event_id, kind, entity_key, event_type, collected_at, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, kind, entity_key, event_type, now, encoded, created_at),
        )
        conn.execute(
            """
            INSERT INTO history_state(kind, entity_key, fingerprint, last_recorded_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, entity_key) DO UPDATE SET
                fingerprint=excluded.fingerprint,
                last_recorded_at=excluded.last_recorded_at
            """,
            (kind, entity_key, digest, now),
        )
        return True

    def pending_count(self) -> int:
        if not self.database_path.is_file():
            return 0
        with closing(connect_sqlite(self.database_path, foreign_keys=True)) as conn:
            if not self._table_exists(conn, "history_outbox"):
                return 0
            row = conn.execute("SELECT COUNT(*) FROM history_outbox").fetchone()
        return int(row[0] if row else 0)

    def outbox_diagnostics(self, *, high_watermark: int = OUTBOX_PRESSURE_HIGH_WATERMARK) -> HistoryOutboxDiagnostics:
        """Return bounded pressure diagnostics without scanning payloads."""

        if not self.database_path.is_file():
            return HistoryOutboxDiagnostics()
        try:
            with closing(connect_sqlite(self.database_path, foreign_keys=True)) as conn:
                if not self._table_exists(conn, "history_outbox"):
                    return HistoryOutboxDiagnostics()
                row = conn.execute(
                    "SELECT COUNT(*) AS pending, MIN(created_at) AS oldest, "
                    "COALESCE(MAX(attempts), 0) AS attempts FROM history_outbox"
                ).fetchone()
        except (OSError, sqlite3.Error):
            return HistoryOutboxDiagnostics(pressure="degraded")
        pending = int(row["pending"] if row is not None else 0)
        oldest = _parse_time(str(row["oldest"] or "")) if row is not None else None
        age = max(0, int((self._now() - oldest).total_seconds())) if oldest else 0
        pressure = "high" if pending >= max(1, int(high_watermark)) else "normal"
        return HistoryOutboxDiagnostics(
            pending=pending,
            oldest_pending_age_seconds=age,
            attempts=int(row["attempts"] if row is not None else 0),
            pressure=pressure,
        )

    def drain(
        self,
        *,
        limit: int = 100,
        unattended_active: bool = False,
        high_watermark: int = OUTBOX_PRESSURE_HIGH_WATERMARK,
        max_elapsed_seconds: float | None = None,
    ) -> HistoryDrainResult:
        """Drain a bounded batch while preserving unattended I/O priority.

        Unattended callers may pass their normal small scheduler limit.  The
        outbox chooses its own bounded batch from pending count and age so a
        low-frequency scheduler has sufficient sustained throughput. Admission
        is based on backlog, age and elapsed batch budget; no synthetic disk
        pressure signal is used because no reliable producer supplies one.
        """

        diagnostics = self.outbox_diagnostics(high_watermark=high_watermark)
        effective_limit = max(1, min(int(limit), UNATTENDED_DRAIN_MAX_LIMIT))
        batch_budget: float | None = max_elapsed_seconds
        if unattended_active:
            effective_limit = self._unattended_drain_limit(
                diagnostics, high_watermark=high_watermark
            )
            batch_budget = (
                UNATTENDED_DRAIN_MAX_ELAPSED_SECONDS
                if max_elapsed_seconds is None
                else max(0.0, float(max_elapsed_seconds))
            )
        if not self.database_path.is_file():
            return HistoryDrainResult()
        try:
            with closing(connect_sqlite(self.database_path, foreign_keys=True)) as current:
                if not self._table_exists(current, "history_outbox"):
                    return HistoryDrainResult()
                rows = current.execute(
                    "SELECT * FROM history_outbox ORDER BY created_at, event_id LIMIT ?",
                    (effective_limit,),
                ).fetchall()
            if not rows:
                return HistoryDrainResult()
            written = 0
            shard_commits = 0
            started_at = time.monotonic()
            batches: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                event = dict(row)
                batches.setdefault(_period(str(event["collected_at"])), []).append(event)
            stop_for_budget = False
            budget_exceeded = False
            for batch in batches.values():
                chunk_limit = UNATTENDED_SHARD_BATCH_LIMIT if unattended_active else len(batch)
                for offset in range(0, len(batch), chunk_limit):
                    if (
                        written
                        and batch_budget is not None
                        and time.monotonic() - started_at >= batch_budget
                    ):
                        stop_for_budget = True
                        budget_exceeded = True
                        break
                    chunk = batch[offset : offset + chunk_limit]
                    try:
                        self._write_shard_batch(chunk)
                        with closing(connect_sqlite(self.database_path, foreign_keys=True)) as current:
                            current.executemany(
                                "DELETE FROM history_outbox WHERE event_id=?",
                                [(str(event["event_id"]),) for event in chunk],
                            )
                            current.commit()
                        written += len(chunk)
                        shard_commits += 1
                        if (
                            batch_budget is not None
                            and time.monotonic() - started_at >= batch_budget
                        ):
                            budget_exceeded = True
                            stop_for_budget = True
                    except (OSError, sqlite3.Error, ValueError):
                        with closing(connect_sqlite(self.database_path, foreign_keys=True)) as current:
                            current.executemany(
                                "UPDATE history_outbox SET attempts=attempts+1 WHERE event_id=?",
                                [(str(event["event_id"]),) for event in chunk],
                            )
                            current.commit()
                        return HistoryDrainResult(
                            written=written,
                            pending=self.outbox_diagnostics(high_watermark=high_watermark).pending,
                            degraded=True,
                            pressure="degraded",
                            elapsed_ms=int((time.monotonic() - started_at) * 1000),
                            budget_exceeded=budget_exceeded,
                            shard_commits=shard_commits,
                        )
                if stop_for_budget:
                    break
            with closing(connect_sqlite(self.database_path, foreign_keys=True)) as current:
                self.ensure_outbox(current)
                pending = self._pending_count_on(current)
                current.commit()
            diagnostics = self.outbox_diagnostics(high_watermark=high_watermark)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            return HistoryDrainResult(
                written=written,
                pending=pending,
                oldest_pending_age_seconds=diagnostics.oldest_pending_age_seconds,
                attempts=diagnostics.attempts,
                pressure=diagnostics.pressure,
                elapsed_ms=elapsed_ms,
                budget_exceeded=budget_exceeded,
                shard_commits=shard_commits,
            )
        except (OSError, sqlite3.Error):
            return HistoryDrainResult(degraded=True, pressure="degraded")

    @staticmethod
    def _unattended_drain_limit(
        diagnostics: HistoryOutboxDiagnostics,
        *,
        high_watermark: int,
    ) -> int:
        """Choose a bounded batch that clears normal production backlog."""

        if (
            diagnostics.pending >= max(1, int(high_watermark))
            or diagnostics.oldest_pending_age_seconds >= UNATTENDED_URGENT_AGE_SECONDS
        ):
            return UNATTENDED_DRAIN_MAX_LIMIT
        if (
            diagnostics.pending >= max(UNATTENDED_DRAIN_BASE_LIMIT, int(high_watermark) // 4)
            or diagnostics.oldest_pending_age_seconds >= UNATTENDED_ELEVATED_AGE_SECONDS
        ):
            return UNATTENDED_DRAIN_ELEVATED_LIMIT
        return UNATTENDED_DRAIN_BASE_LIMIT

    def _write_shard_batch(self, rows: list[dict[str, Any]]) -> int:
        """Append one month of durable outbox events with bounded SQLite commits."""

        if not rows:
            return 0
        period = _period(str(rows[0]["collected_at"]))
        if any(_period(str(row["collected_at"])) != period for row in rows):
            raise ValueError("history shard batch must contain one month")
        self.history_root.mkdir(parents=True, exist_ok=True)
        with interprocess_file_lock(self.history_root / ".history-append.lock"):
            return self._write_shard_batch_locked(period, rows)

    def _write_shard_batch_locked(
        self, period: str, rows: list[dict[str, Any]]
    ) -> int:
        unique_rows: dict[str, dict[str, Any]] = {}
        for row in rows:
            event_id = str(row["event_id"])
            previous = unique_rows.get(event_id)
            if previous is not None:
                self._assert_shard_event_content(previous, row)
                continue
            unique_rows[event_id] = row

        existing, writable_shards = self._catalog_event_rows_locked(
            period, list(unique_rows)
        )
        for event_id, stored in existing.items():
            self._assert_shard_event_content(unique_rows[event_id], stored)
        self._refresh_writable_catalog_profiles_locked(writable_shards)
        pending = [
            row for event_id, row in unique_rows.items() if event_id not in existing
        ]
        if not pending:
            return 0

        estimated_bytes = sum(
            len(str(row.get("payload_json") or "").encode("utf-8")) + 256
            for row in pending
        )
        shard_id, shard_path, segment = self._writable_shard(period, estimated_bytes)
        inserted = 0
        with closing(connect_sqlite(shard_path, foreign_keys=True)) as shard:
            self._ensure_shard(shard)
            local_existing = {
                str(row["event_id"]): row
                for row in self._read_event_rows_by_id(
                    shard, [str(row["event_id"]) for row in pending]
                )
            }
            for event_id, stored in local_existing.items():
                self._assert_shard_event_content(unique_rows[event_id], stored)
            pending = [
                row
                for row in pending
                if str(row["event_id"]) not in local_existing
            ]
            kind_ids: dict[str, int] = {}
            entity_ids: dict[tuple[int, str], int] = {}
            event_type_ids: dict[str, int] = {}
            payload_schema_ids: dict[str, int] = {}
            for row in pending:
                event_id = str(row["event_id"])
                kind = str(row["kind"])
                entity_key = str(row["entity_key"])
                event_type = str(row["event_type"])
                if kind not in kind_ids:
                    kind_ids[kind] = self._dictionary_id(
                        shard,
                        table="history_kinds_v2",
                        id_column="kind_id",
                        value_column="name",
                        value=kind,
                    )
                kind_id = kind_ids[kind]
                entity_cache_key = (kind_id, entity_key)
                if entity_cache_key not in entity_ids:
                    entity_ids[entity_cache_key] = self._entity_id(
                        shard, kind_id=kind_id, entity_key=entity_key
                    )
                if event_type not in event_type_ids:
                    event_type_ids[event_type] = self._dictionary_id(
                        shard,
                        table="history_event_types_v2",
                        id_column="event_type_id",
                        value_column="name",
                        value=event_type,
                    )
                event_type_id = event_type_ids[event_type]
                payload = json.loads(str(row["payload_json"]))
                fields_json, codec, encoded_payload = self._encode_payload_v2(payload)
                if fields_json not in payload_schema_ids:
                    payload_schema_ids[fields_json] = self._payload_schema_id(
                        shard, fields_json=fields_json
                    )
                cursor = shard.execute(
                    """
                    INSERT OR IGNORE INTO history_events_v2
                        (event_id, kind_id, entity_id, event_type_id, collected_at,
                         payload_schema_id, payload_codec, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._event_id_bytes(event_id),
                        kind_id,
                        entity_ids[entity_cache_key],
                        event_type_id,
                        str(row["collected_at"]),
                        payload_schema_ids[fields_json],
                        codec,
                        encoded_payload,
                        str(row["created_at"]),
                    ),
                )
                source_table = str(payload.get("legacy_source_table") or "").strip()
                source_id = payload.get("legacy_source_id")
                if source_table or source_id is not None:
                    if source_table not in LEGACY_HISTORY_TABLES:
                        raise ValueError(
                            f"unsupported legacy history source: {source_table}"
                        )
                    try:
                        source_id_int = int(source_id)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("legacy history source id is invalid") from exc
                    if source_id_int <= 0:
                        raise ValueError("legacy history source id is invalid")
                    shard.execute(
                        """
                        INSERT INTO history_event_provenance_v2(event_id, source_table, source_id)
                        VALUES (?, ?, ?)
                        ON CONFLICT(event_id) DO UPDATE SET
                            source_table=excluded.source_table,
                            source_id=excluded.source_id
                        """,
                        (self._event_id_bytes(event_id), source_table, source_id_int),
                    )
                inserted += max(0, cursor.rowcount)
            shard.commit()
        profile = self._shard_profile(shard_path)
        self._publish_shard(
            shard_id=shard_id,
            period=period,
            segment=segment,
            shard_path=shard_path,
            profile=profile,
        )
        return inserted

    def _catalog_event_rows_locked(
        self, period: str, event_ids: list[str]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        found: dict[str, dict[str, Any]] = {}
        writable_shards: dict[str, dict[str, Any]] = {}
        catalog_path = self.history_root / "catalog.db"
        with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            placeholders = ", ".join("?" for _ in CATALOG_QUERYABLE_STATES)
            catalog_rows = catalog.execute(
                "SELECT * FROM history_catalog WHERE period_start=? AND status IN ("
                + placeholders
                + ")"
                + self._catalog_order_by(catalog, include_period=False),
                (f"{period}-01", *sorted(CATALOG_QUERYABLE_STATES)),
            ).fetchall()
            catalog.commit()

        for catalog_row in catalog_rows:
            item = dict(catalog_row)
            shard_path = self._safe_shard_path(str(item.get("relative_path") or ""))
            if shard_path is None or not shard_path.is_file():
                continue
            with closing(self._connect_readonly(shard_path)) as shard:
                stored_rows = self._read_event_rows_by_id(shard, event_ids)
            for stored in stored_rows:
                event_id = str(stored["event_id"])
                if event_id in found:
                    raise sqlite3.DatabaseError(
                        "duplicate history event identity across shards"
                    )
                found[event_id] = stored
                if str(item.get("status") or "") in CATALOG_WRITABLE_STATES:
                    writable_shards[str(item["shard_id"])] = item
        return found, writable_shards

    def _refresh_writable_catalog_profiles_locked(
        self, shards: dict[str, dict[str, Any]]
    ) -> None:
        for item in shards.values():
            if int(item.get("schema_version") or 0) < STORAGE_SCHEMA_VERSION:
                continue
            path = self._safe_shard_path(str(item.get("relative_path") or ""))
            if path is None or not path.is_file():
                continue
            profile = self._shard_profile(path)
            if all(
                str(item.get(key, "")) == str(profile[key])
                for key in (
                    "row_count",
                    "size_bytes",
                    "sha256",
                    "content_fingerprint",
                    "min_business_time",
                    "max_business_time",
                )
            ):
                continue
            self._publish_shard(
                shard_id=str(item["shard_id"]),
                period=str(item["period_start"])[:7],
                segment=int(item.get("segment") or 1),
                shard_path=path,
                profile=profile,
            )

    def _writable_shard(self, period: str, incoming_bytes: int) -> tuple[str, Path, int]:
        catalog_path = self.history_root / "catalog.db"
        latest: dict[str, Any] | None = None
        max_segment = 0
        with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            rows = catalog.execute(
                "SELECT shard_id, relative_path, segment, status FROM history_catalog "
                "WHERE period_start=? ORDER BY segment DESC, shard_id DESC",
                (f"{period}-01",),
            ).fetchall()
            if rows:
                latest = dict(rows[0])
                max_segment = max(int(row["segment"] or 1) for row in rows)
            catalog.commit()

        if latest is not None and str(latest.get("status") or "") in CATALOG_WRITABLE_STATES:
            path = self._safe_shard_path(str(latest.get("relative_path") or ""))
            if path is None:
                raise sqlite3.DatabaseError("history catalog contains an invalid shard path")
            projected = (path.stat().st_size if path.is_file() else 0) + max(0, incoming_bytes)
            if self.segment_max_bytes is None or projected <= self.segment_max_bytes:
                return str(latest["shard_id"]), path, int(latest.get("segment") or 1)
            self._seal_shard_locked(str(latest["shard_id"]))

        if latest is not None and str(latest.get("status") or "") == "SEALING":
            self._seal_shard_locked(str(latest["shard_id"]))

        segment = max(1, max_segment + 1)
        if max_segment == 0:
            shard_id = period
            filename = f"devices-{period}.db"
        else:
            shard_id = f"{period}-{segment:04d}"
            filename = f"devices-{period}-{segment:04d}.db"
        return shard_id, self.history_root / filename, segment

    def _publish_shard(
        self,
        *,
        shard_id: str,
        period: str,
        segment: int,
        shard_path: Path,
        profile: dict[str, Any],
    ) -> None:
        """Publish a fully committed and verified shard as the final write step."""

        year, month = (int(part) for part in period.split("-", 1))
        last_day = monthrange(year, month)[1]
        now = self._now().isoformat(timespec="seconds")
        with closing(connect_sqlite(self.history_root / "catalog.db", foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            catalog.execute(
                """
                INSERT INTO history_catalog
                    (shard_id, site_id, domain, period_start, period_end, segment,
                     relative_path, schema_version, status, row_count, size_bytes,
                     sha256, content_fingerprint, min_business_time,
                     max_business_time, authority_revision, created_at)
                VALUES (?, ?, 'site_history', ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(shard_id) DO UPDATE SET
                    relative_path=excluded.relative_path,
                    schema_version=MAX(history_catalog.schema_version, excluded.schema_version),
                    status=CASE
                        WHEN history_catalog.status IN ('ACTIVE','OPEN') THEN 'OPEN'
                        ELSE history_catalog.status
                    END,
                    row_count=excluded.row_count,
                    size_bytes=excluded.size_bytes,
                    sha256=excluded.sha256,
                    content_fingerprint=excluded.content_fingerprint,
                    min_business_time=excluded.min_business_time,
                    max_business_time=excluded.max_business_time,
                    authority_revision=history_catalog.authority_revision+1
                """,
                (
                    shard_id,
                    self.site_id,
                    f"{period}-01",
                    f"{period}-{last_day:02d}",
                    segment,
                    shard_path.name,
                    STORAGE_SCHEMA_VERSION,
                    int(profile["row_count"]),
                    int(profile["size_bytes"]),
                    str(profile["sha256"]),
                    str(profile["content_fingerprint"]),
                    str(profile["min_business_time"]),
                    str(profile["max_business_time"]),
                    now,
                ),
            )
            catalog.commit()

    def seal_shard(self, shard_id: str) -> dict[str, Any]:
        """Seal one catalog shard; the VERIFIED publish is always the final step."""

        self.history_root.mkdir(parents=True, exist_ok=True)
        with interprocess_file_lock(self.history_root / ".history-append.lock"):
            return self._seal_shard_locked(shard_id)

    def _seal_shard_locked(self, shard_id: str) -> dict[str, Any]:
        catalog_path = self.history_root / "catalog.db"
        with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            row = catalog.execute(
                "SELECT * FROM history_catalog WHERE shard_id=?", (str(shard_id),)
            ).fetchone()
            if row is None:
                raise ValueError("history shard is not registered")
            item = dict(row)
            if str(item.get("status") or "") == "VERIFIED":
                return item
            if str(item.get("status") or "") == "RETIRED":
                raise ValueError("retired history shard cannot be sealed")
            catalog.execute(
                "UPDATE history_catalog SET status='SEALING', authority_revision=authority_revision+1 "
                "WHERE shard_id=?",
                (str(shard_id),),
            )
            catalog.commit()
        path = self._safe_shard_path(str(item.get("relative_path") or ""))
        if path is None or not path.is_file():
            raise sqlite3.DatabaseError("history shard file is missing or invalid")
        profile = self._shard_profile(path)
        # Windows rejects fsync on a read-only file descriptor.  The shard is
        # closed at this point; open it writable only to flush the completed
        # file before the catalog publishes VERIFIED.
        with path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        sealed_at = self._now().isoformat(timespec="seconds")
        with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            catalog.execute(
                """
                UPDATE history_catalog
                SET status='VERIFIED', row_count=?, size_bytes=?, sha256=?,
                    content_fingerprint=?, min_business_time=?, max_business_time=?,
                    closed_at=COALESCE(closed_at, ?), sealed_at=?
                WHERE shard_id=? AND status='SEALING'
                """,
                (
                    int(profile["row_count"]),
                    int(profile["size_bytes"]),
                    str(profile["sha256"]),
                    str(profile["content_fingerprint"]),
                    str(profile["min_business_time"]),
                    str(profile["max_business_time"]),
                    sealed_at,
                    sealed_at,
                    str(shard_id),
                ),
            )
            if catalog.total_changes != 1:
                catalog.rollback()
                raise sqlite3.DatabaseError("history shard seal publish failed")
            catalog.commit()
            result = catalog.execute(
                "SELECT * FROM history_catalog WHERE shard_id=?", (str(shard_id),)
            ).fetchone()
        return dict(result) if result is not None else {}

    def seal_open_shards(self, *, before_period: str | None = None) -> list[dict[str, Any]]:
        catalog_path = self.history_root / "catalog.db"
        if not catalog_path.is_file():
            return []
        with closing(self._connect_readonly(catalog_path)) as catalog:
            clauses = ["status IN ('ACTIVE','OPEN','SEALING')"]
            params: list[Any] = []
            if before_period:
                clauses.append("period_start < ?")
                params.append(f"{before_period}-01")
            rows = catalog.execute(
                "SELECT shard_id FROM history_catalog WHERE "
                + " AND ".join(clauses)
                + self._catalog_order_by(catalog),
                params,
            ).fetchall()
        return [self.seal_shard(str(row[0])) for row in rows]

    def _shard_profile(self, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        with closing(self._connect_readonly(path)) as shard:
            quick_check = str(shard.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check.casefold() != "ok":
                raise sqlite3.DatabaseError("history shard quick_check failed")
            if not self._table_exists(shard, "history_events_v2"):
                raise sqlite3.DatabaseError("history shard schema is incomplete")
            row = shard.execute(
                "SELECT COUNT(*) AS total, MIN(collected_at) AS minimum, "
                "MAX(collected_at) AS maximum FROM history_events_v2"
            ).fetchone()
            for value in shard.execute(
                "SELECT hex(event_id), collected_at, payload_codec, hex(payload) "
                "FROM history_events_v2 ORDER BY collected_at, event_id"
            ):
                digest.update("\0".join(str(item or "") for item in value).encode("utf-8"))
                digest.update(b"\n")
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
        return {
            "row_count": int(row["total"] if row is not None else 0),
            "size_bytes": path.stat().st_size,
            "sha256": file_digest.hexdigest(),
            "content_fingerprint": digest.hexdigest(),
            "min_business_time": str(row["minimum"] or "") if row is not None else "",
            "max_business_time": str(row["maximum"] or "") if row is not None else "",
        }

    def backfill_legacy_provenance(self, *, batch_size: int = 1000) -> dict[str, Any]:
        """Materialize source identity for legacy V2 events in existing shards.

        Older V2 shards may have retained the stable source ``id`` in the
        encoded payload before the explicit provenance table was introduced.
        This maintenance pass converts that evidence into the durable
        ``source_table + source_id`` authority used after source retirement.
        It is explicit, bounded by the caller's maintenance lock, and
        idempotent; normal reads and startup never perform this repair.
        """

        limit = max(1, int(batch_size))
        catalog_path = self.history_root / "catalog.db"
        if not catalog_path.is_file():
            return {"status": "NO_CATALOG", "shards": [], "backfilled": 0}
        self.history_root.mkdir(parents=True, exist_ok=True)
        with interprocess_file_lock(self.history_root / ".history-append.lock"):
            with closing(self._connect_readonly(catalog_path)) as catalog:
                catalog_rows = [
                    dict(row)
                    for row in catalog.execute(
                        "SELECT * FROM history_catalog "
                        "WHERE status IN ('ACTIVE','OPEN','CLOSED','ARCHIVED','SEALING','SEALED','VERIFIED') "
                        + self._catalog_order_by(catalog)
                    ).fetchall()
                ]
            shard_results: list[dict[str, Any]] = []
            total_backfilled = 0
            for catalog_row in catalog_rows:
                relative_path = str(catalog_row.get("relative_path") or "")
                shard_path = self._safe_shard_path(relative_path)
                if shard_path is None or not shard_path.is_file():
                    raise sqlite3.DatabaseError(
                        f"history catalog shard is missing or invalid: {relative_path}"
                    )
                backfilled = 0
                with closing(connect_sqlite(shard_path, foreign_keys=True)) as shard:
                    self._ensure_shard(shard)
                    last_collected_at: str | None = None
                    last_event_id: bytes | None = None
                    while True:
                        rows = shard.execute(
                            """
                            SELECT e.event_id, e.collected_at,
                                   e.payload_codec, e.payload,
                                   s.payload_schema_version, s.fields_json,
                                   k.name AS kind
                            FROM history_events_v2 AS e
                            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
                            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
                            JOIN history_payload_schemas_v2 AS s
                              ON s.payload_schema_id=e.payload_schema_id
                            LEFT JOIN history_event_provenance_v2 AS p
                              ON p.event_id=e.event_id
                            WHERE t.name='legacy' AND p.event_id IS NULL
                              AND (
                                  ? IS NULL
                                  OR e.collected_at > ?
                                  OR (e.collected_at = ? AND e.event_id > ?)
                              )
                            ORDER BY e.collected_at, e.event_id
                            LIMIT ?
                            """,
                            (
                                last_collected_at,
                                last_collected_at,
                                last_collected_at,
                                last_event_id,
                                limit,
                            ),
                        ).fetchall()
                        if not rows:
                            break
                        provenance_rows: list[tuple[bytes, str, int]] = []
                        for row in rows:
                            decoded = self._decode_payload_v2(dict(row))
                            source_table = KIND_CANONICAL_LEGACY_SOURCE.get(
                                str(row["kind"])
                            )
                            source_id = decoded.get("id")
                            if not source_table or source_id is None:
                                raise sqlite3.DatabaseError(
                                    "legacy history provenance cannot be reconstructed"
                                )
                            try:
                                source_id_int = int(source_id)
                            except (TypeError, ValueError) as exc:
                                raise sqlite3.DatabaseError(
                                    "legacy history provenance source id is invalid"
                                ) from exc
                            if source_id_int <= 0:
                                raise sqlite3.DatabaseError(
                                    "legacy history provenance source id is invalid"
                                )
                            provenance_rows.append(
                                (bytes(row["event_id"]), source_table, source_id_int)
                            )
                        shard.executemany(
                            """
                            INSERT INTO history_event_provenance_v2
                                (event_id, source_table, source_id)
                            VALUES (?, ?, ?)
                            ON CONFLICT(event_id) DO NOTHING
                            """,
                            provenance_rows,
                        )
                        shard.commit()
                        backfilled += len(provenance_rows)
                        last_collected_at = str(rows[-1]["collected_at"])
                        last_event_id = bytes(rows[-1]["event_id"])
                    provenance_storage_optimized = (
                        self._optimize_legacy_provenance_storage(shard)
                    )
                profile = self._shard_profile(shard_path)
                self._publish_shard(
                    shard_id=str(catalog_row["shard_id"]),
                    period=str(catalog_row["period_start"])[:7],
                    segment=int(catalog_row.get("segment") or 1),
                    shard_path=shard_path,
                    profile=profile,
                )
                shard_results.append(
                    {
                        "shard_id": str(catalog_row["shard_id"]),
                        "path": str(shard_path),
                        "backfilled": backfilled,
                        "provenance_storage_optimized": provenance_storage_optimized,
                        "rows": int(profile["row_count"]),
                    }
                )
                total_backfilled += backfilled
            return {
                "status": "PASS",
                "shards": shard_results,
                "backfilled": total_backfilled,
            }

    @staticmethod
    def _optimize_legacy_provenance_storage(shard: sqlite3.Connection) -> bool:
        row = shard.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='history_event_provenance_v2'"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("history provenance table is missing")
        table_sql = str(row[0] or "").upper()
        redundant_index = shard.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='index' AND name='idx_history_event_provenance_v2_source'"
        ).fetchone()
        if "WITHOUT ROWID" in table_sql and redundant_index is None:
            return False

        expected = int(
            shard.execute(
                "SELECT COUNT(*) FROM history_event_provenance_v2"
            ).fetchone()[0]
        )
        shard.execute("BEGIN IMMEDIATE")
        try:
            shard.execute(
                """
                CREATE TABLE history_event_provenance_v2_compact (
                    event_id BLOB PRIMARY KEY,
                    source_table TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES history_events_v2(event_id)
                        ON DELETE CASCADE
                ) WITHOUT ROWID
                """
            )
            shard.execute(
                """
                INSERT INTO history_event_provenance_v2_compact
                    (event_id, source_table, source_id)
                SELECT event_id, source_table, source_id
                FROM history_event_provenance_v2
                """
            )
            copied = int(
                shard.execute(
                    "SELECT COUNT(*) FROM history_event_provenance_v2_compact"
                ).fetchone()[0]
            )
            if copied != expected:
                raise sqlite3.DatabaseError(
                    "history provenance storage rewrite count mismatch"
                )
            shard.execute("DROP TABLE history_event_provenance_v2")
            shard.execute(
                "ALTER TABLE history_event_provenance_v2_compact "
                "RENAME TO history_event_provenance_v2"
            )
            shard.execute(
                "CREATE UNIQUE INDEX ux_history_event_provenance_v2_source "
                "ON history_event_provenance_v2(source_table, source_id)"
            )
            shard.commit()
        except BaseException:
            shard.rollback()
            raise
        shard.execute("VACUUM")
        return True

    def copy_legacy_migration_events(
        self, events: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Write and durably verify an explicit COPY-only migration chunk."""

        for event in events:
            if str(event.get("event_type") or "") != "legacy":
                raise ValueError("migration events must use event_type=legacy")
        if not events:
            return 0, 0
        return self.copy_verified_events(events)

    def copy_verified_events(
        self, events: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Idempotently append an explicit non-empty set and verify full content."""

        if not events:
            raise ValueError("history archive scope must not be empty")
        normalized: list[dict[str, Any]] = []
        for event in events:
            event_id = str(event.get("event_id") or "").strip().lower()
            self._event_id_bytes(event_id)
            kind = str(event.get("kind") or "").strip()
            entity_key = str(event.get("entity_key") or "").strip()
            event_type = str(event.get("event_type") or "").strip()
            collected_at = str(event.get("collected_at") or "").strip()
            if not kind or not entity_key or not event_type or _parse_time(collected_at) is None:
                raise ValueError("history archive event identity is incomplete")
            payload = json.loads(str(event.get("payload_json") or "{}"))
            if not isinstance(payload, dict):
                raise ValueError("history archive payload must be an object")
            normalized.append(
                {
                    "event_id": event_id,
                    "kind": kind,
                    "entity_key": entity_key,
                    "event_type": event_type,
                    "collected_at": collected_at,
                    "payload_json": json.dumps(
                        _json_value(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "created_at": str(event.get("created_at") or collected_at),
                }
            )
        if len({event["event_id"] for event in normalized}) != len(normalized):
            raise ValueError("history archive contains duplicate event identities")
        existing = {
            str(row["event_id"]): row for row in self.read_verified_events(normalized)
        }
        if existing:
            self._verify_shard_event_content(
                [event for event in normalized if event["event_id"] in existing]
            )
        pending = [event for event in normalized if event["event_id"] not in existing]
        inserted = 0
        batches: dict[str, list[dict[str, Any]]] = {}
        for event in pending:
            batches.setdefault(_period(str(event["collected_at"])), []).append(event)
        for batch in batches.values():
            inserted += self._write_shard_batch(batch)
        self._verify_shard_event_content(normalized)
        return inserted, len(normalized)

    def read_legacy_migration_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Read exact copied events for digest/sample verification."""

        return self.read_verified_events(events)

    def read_verified_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Read exact catalog-published events by deterministic identity."""

        found: dict[str, dict[str, Any]] = {}
        by_period: dict[str, list[str]] = {}
        for event in events:
            by_period.setdefault(_period(str(event["collected_at"])), []).append(
                str(event["event_id"])
            )
        for period, event_ids in by_period.items():
            event_ids = sorted(set(event_ids))
            catalog_path = self.history_root / "catalog.db"
            if not catalog_path.is_file():
                continue
            with closing(self._connect_readonly(catalog_path)) as catalog:
                if not self._table_exists(catalog, "history_catalog"):
                    continue
                rows = catalog.execute(
                    "SELECT relative_path FROM history_catalog WHERE period_start=? "
                    "AND status IN ('ACTIVE','CLOSED','ARCHIVED','OPEN','SEALING','SEALED','VERIFIED') "
                    + self._catalog_order_by(catalog, include_period=False),
                    (f"{period}-01",),
                ).fetchall()
            for catalog_row in rows:
                shard_path = self._safe_shard_path(str(catalog_row[0]))
                if shard_path is None or not shard_path.is_file():
                    continue
                with closing(self._connect_readonly(shard_path)) as shard:
                    for offset in range(0, len(event_ids), 500):
                        chunk = event_ids[offset : offset + 500]
                        placeholders = ", ".join("?" for _ in chunk)
                        if self._table_exists(shard, "history_events"):
                            rows_v1 = shard.execute(
                                "SELECT * FROM history_events WHERE event_id IN ("
                                + placeholders
                                + ")",
                                chunk,
                            ).fetchall()
                            found.update((str(row["event_id"]), dict(row)) for row in rows_v1)
                        if self._table_exists(shard, "history_events_v2"):
                            rows_v2 = self._read_v2_storage_rows(shard, chunk)
                            found.update((str(row["event_id"]), row) for row in rows_v2)
        return [found[str(event["event_id"])] for event in events if str(event["event_id"]) in found]

    def _verify_shard_event_content(self, events: list[dict[str, Any]]) -> None:
        found = {
            str(row["event_id"]): row for row in self.read_verified_events(events)
        }
        for event in events:
            event_id = str(event["event_id"])
            row = found.get(event_id)
            if row is None:
                raise sqlite3.DatabaseError("history shard event verification failed")
            self._assert_shard_event_content(event, row)

    @staticmethod
    def _assert_shard_event_content(
        expected: dict[str, Any], actual: dict[str, Any]
    ) -> None:
        expected_payload = HistoryStore._normalized_shard_payload(expected)
        actual_payload = HistoryStore._normalized_shard_payload(actual)
        if (
            str(actual.get("kind") or "") != str(expected["kind"])
            or str(actual.get("entity_key") or "") != str(expected["entity_key"])
            or str(actual.get("event_type") or "") != str(expected["event_type"])
            or str(actual.get("collected_at") or "")
            != str(expected["collected_at"])
            or actual_payload != expected_payload
        ):
            raise sqlite3.DatabaseError("history shard event content mismatch")
        expected_source = (
            str(expected.get("legacy_source_table") or ""),
            str(expected.get("legacy_source_id") or ""),
        )
        actual_source = (
            str(actual.get("legacy_source_table") or ""),
            str(actual.get("legacy_source_id") or ""),
        )
        if expected_source != ("", "") and actual_source != expected_source:
            raise sqlite3.DatabaseError("history shard source identity mismatch")

    @staticmethod
    def _normalized_shard_payload(event: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(str(event.get("payload_json") or "{}"))
        if not isinstance(payload, dict):
            payload = {"value": payload}
        normalized = {
            str(key): _json_value(value)
            for key, value in payload.items()
            if str(key) not in _PAYLOAD_ENVELOPE_FIELDS
        }
        normalized["collected_at"] = str(event["collected_at"])
        return normalized

    @staticmethod
    def legacy_migration_event(source_table: str, row: dict[str, Any]) -> dict[str, Any]:
        """Build the stable shard event used by the maintenance migration."""

        return HistoryStore._legacy_event(source_table, row)

    def query_events(
        self,
        *,
        kind: str,
        entity_key: str | None = None,
        entity_prefix: str | None = None,
        limit: int = 200,
        offset: int = 0,
        collected_from: str | None = None,
        collected_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read known shards without creating, repairing, or discovering any database."""

        events: list[dict[str, Any]] = []
        errors: list[str] = []
        # UI callers pass a small page size. Export callers explicitly pass a
        # bounded export limit, which must not be silently truncated here.
        # Keep only the requested window while walking older monthly shards:
        # that preserves global ordering without materializing every shard.
        safe_limit = max(1, int(limit))
        safe_offset = max(0, int(offset))
        requested = safe_limit + safe_offset
        include_legacy = self._kind_uses_shard_authority(kind)
        if self.database_path.is_file():
            try:
                with closing(self._connect_readonly(self.database_path)) as current:
                    if self._table_exists(current, "history_outbox"):
                        pending = self._query_rows(
                            current,
                            "history_outbox",
                            kind=kind,
                            entity_key=entity_key,
                            entity_prefix=entity_prefix,
                            limit=requested,
                            collected_from=collected_from,
                            collected_to=collected_to,
                            include_legacy=False,
                        )
                        events.extend(self._event_dict(dict(row)) for row in pending)
            except (OSError, sqlite3.Error) as exc:
                errors.append(f"current:{exc.__class__.__name__}")
        catalog_path = self.history_root / "catalog.db"
        if not catalog_path.is_file():
            self._last_query_errors = tuple(errors)
            return self._sort_unique_events(events)[safe_offset:requested]
        try:
            with closing(self._connect_readonly(catalog_path)) as catalog:
                if not self._table_exists(catalog, "history_catalog"):
                    self._last_query_errors = (*errors, "catalog:missing_schema")
                    return self._sort_unique_events(events)[safe_offset:requested]
                clauses = [
                    "status IN ('ACTIVE','CLOSED','ARCHIVED','OPEN','SEALING','SEALED','VERIFIED')"
                ]
                params: list[Any] = []
                if collected_from:
                    clauses.append("period_end >= ?")
                    params.append(str(collected_from)[:7])
                if collected_to:
                    clauses.append("period_start <= ?")
                    params.append(f"{str(collected_to)[:7]}-31")
                shards = catalog.execute(
                    "SELECT relative_path FROM history_catalog WHERE "
                    + " AND ".join(clauses)
                    + self._catalog_order_by(catalog, descending=True),
                    params,
                ).fetchall()
            for shard_row in shards:
                relative_path = str(shard_row[0])
                path = self._safe_shard_path(relative_path)
                if path is None:
                    errors.append(f"shard:{relative_path}:invalid_path")
                    continue
                if not path.is_file():
                    errors.append(f"shard:{path.name}:missing")
                    continue
                try:
                    with closing(self._connect_readonly(path)) as shard:
                        has_v1 = self._table_exists(shard, "history_events")
                        has_v2 = self._table_exists(shard, "history_events_v2")
                        if not has_v1 and not has_v2:
                            errors.append(f"shard:{path.name}:missing_schema")
                            continue
                        shard_events: list[dict[str, Any]] = []
                        if has_v1:
                            rows_v1 = self._query_rows(
                                shard,
                                "history_events",
                                kind=kind,
                                entity_key=entity_key,
                                entity_prefix=entity_prefix,
                                limit=requested,
                                collected_from=collected_from,
                                collected_to=collected_to,
                                include_legacy=include_legacy,
                            )
                            shard_events.extend(
                                self._event_dict(dict(row)) for row in rows_v1
                            )
                        if has_v2:
                            shard_events.extend(
                                self._query_v2_events(
                                    shard,
                                    kind=kind,
                                    entity_key=entity_key,
                                    entity_prefix=entity_prefix,
                                    limit=requested,
                                    collected_from=collected_from,
                                    collected_to=collected_to,
                                    include_legacy=include_legacy,
                                )
                            )
                    events.extend(shard_events)
                    events = self._sort_unique_events(events)[:requested]
                except (OSError, sqlite3.Error) as exc:
                    errors.append(f"shard:{path.name}:{exc.__class__.__name__}")
                    continue
        except (OSError, sqlite3.Error) as exc:
            errors.append(f"catalog:{exc.__class__.__name__}")
        self._last_query_errors = tuple(errors)
        return self._sort_unique_events(events)[safe_offset:requested]

    def query_events_for_entities(
        self,
        *,
        kind: str,
        entity_keys: Iterable[str],
        event_types: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read complete history for selected entities while opening each shard once."""

        keys = sorted(
            {str(entity_key).strip() for entity_key in entity_keys if str(entity_key).strip()}
        )
        types = sorted(
            {str(event_type).strip() for event_type in (event_types or ()) if str(event_type).strip()}
        )
        if not keys:
            return []

        events: list[dict[str, Any]] = []
        errors: list[str] = []
        include_legacy = self._kind_uses_shard_authority(kind)

        def read_database(path: Path, *, current: bool = False) -> None:
            try:
                with closing(self._connect_readonly(path)) as conn:
                    if current:
                        tables = (("history_outbox", False),)
                    else:
                        tables = (
                            ("history_events", include_legacy),
                            ("history_events_v2", include_legacy),
                        )
                    found = False
                    for table, allow_legacy in tables:
                        if not self._table_exists(conn, table):
                            continue
                        found = True
                        for start in range(0, len(keys), 400):
                            chunk = keys[start : start + 400]
                            if table == "history_events_v2":
                                events.extend(
                                    self._query_v2_events_for_entities(
                                        conn,
                                        kind=kind,
                                        entity_keys=chunk,
                                        event_types=types,
                                        include_legacy=allow_legacy,
                                    )
                                )
                            else:
                                rows = self._query_rows_for_entities(
                                    conn,
                                    table,
                                    kind=kind,
                                    entity_keys=chunk,
                                    event_types=types,
                                    include_legacy=allow_legacy,
                                )
                                events.extend(self._event_dict(dict(row)) for row in rows)
                    if not current and not found:
                        errors.append(f"shard:{path.name}:missing_schema")
            except (OSError, sqlite3.Error) as exc:
                prefix = "current" if current else f"shard:{path.name}"
                errors.append(f"{prefix}:{exc.__class__.__name__}")

        if self.database_path.is_file():
            read_database(self.database_path, current=True)

        catalog_path = self.history_root / "catalog.db"
        if catalog_path.is_file():
            try:
                with closing(self._connect_readonly(catalog_path)) as catalog:
                    if not self._table_exists(catalog, "history_catalog"):
                        errors.append("catalog:missing_schema")
                        self._last_query_errors = tuple(errors)
                        return self._sort_unique_events(events)
                    shards = catalog.execute(
                        "SELECT relative_path FROM history_catalog WHERE "
                        "status IN ('ACTIVE','CLOSED','ARCHIVED','OPEN','SEALING',"
                        "'SEALED','VERIFIED')"
                        + self._catalog_order_by(catalog, descending=True)
                    ).fetchall()
                for shard_row in shards:
                    relative_path = str(shard_row[0])
                    path = self._safe_shard_path(relative_path)
                    if path is None:
                        errors.append(f"shard:{relative_path}:invalid_path")
                    elif not path.is_file():
                        errors.append(f"shard:{path.name}:missing")
                    else:
                        read_database(path)
            except (OSError, sqlite3.Error) as exc:
                errors.append(f"catalog:{exc.__class__.__name__}")

        self._last_query_errors = tuple(errors)
        return self._sort_unique_events(events)

    def count_events(
        self,
        *,
        kind: str,
        entity_key: str | None = None,
        entity_prefix: str | None = None,
        collected_from: str | None = None,
        collected_to: str | None = None,
    ) -> int:
        """Count known outbox/shard events without materializing history rows."""

        total = 0
        errors: list[str] = []

        include_legacy = self._kind_uses_shard_authority(kind)

        def count_rows(
            conn: sqlite3.Connection, table: str, *, allow_legacy: bool
        ) -> int:
            # Copied legacy rows remain intentionally hidden until a future
            # per-table cutover can exclude their source rows. Otherwise an
            # old database would return the legacy row and its verified copy.
            clauses = ["kind = ?"]
            if not allow_legacy:
                clauses.append("event_type != 'legacy'")
            params: list[Any] = [kind]
            if entity_key is not None:
                clauses.append("entity_key = ?")
                params.append(entity_key)
            elif entity_prefix is not None:
                clauses.append("entity_key LIKE ?")
                params.append(f"{entity_prefix}%")
            if collected_from:
                clauses.append("collected_at >= ?")
                params.append(str(collected_from))
            if collected_to:
                clauses.append("collected_at <= ?")
                params.append(str(collected_to))
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM {table} WHERE " + " AND ".join(clauses),
                params,
            ).fetchone()
            return int(row["total"] if row is not None else 0)

        if self.database_path.is_file():
            try:
                with closing(self._connect_readonly(self.database_path)) as current:
                    if self._table_exists(current, "history_outbox"):
                        total += count_rows(
                            current, "history_outbox", allow_legacy=False
                        )
            except (OSError, sqlite3.Error) as exc:
                errors.append(f"current:{exc.__class__.__name__}")

        catalog_path = self.history_root / "catalog.db"
        if catalog_path.is_file():
            try:
                with closing(self._connect_readonly(catalog_path)) as catalog:
                    if not self._table_exists(catalog, "history_catalog"):
                        errors.append("catalog:missing_schema")
                        self._last_query_errors = tuple(errors)
                        return total
                    clauses = [
                        "status IN ('ACTIVE','CLOSED','ARCHIVED','OPEN','SEALING','SEALED','VERIFIED')"
                    ]
                    params: list[Any] = []
                    if collected_from:
                        clauses.append("period_end >= ?")
                        params.append(str(collected_from)[:7])
                    if collected_to:
                        clauses.append("period_start <= ?")
                        params.append(f"{str(collected_to)[:7]}-31")
                    shards = catalog.execute(
                        "SELECT relative_path FROM history_catalog WHERE "
                        + " AND ".join(clauses)
                        + self._catalog_order_by(catalog),
                        params,
                    ).fetchall()
                for shard_row in shards:
                    relative_path = str(shard_row[0])
                    path = self._safe_shard_path(relative_path)
                    if path is None:
                        errors.append(f"shard:{relative_path}:invalid_path")
                        continue
                    if not path.is_file():
                        errors.append(f"shard:{path.name}:missing")
                        continue
                    try:
                        with closing(self._connect_readonly(path)) as shard:
                            if self._table_exists(shard, "history_events"):
                                total += count_rows(
                                    shard,
                                    "history_events",
                                    allow_legacy=include_legacy,
                                )
                            if self._table_exists(shard, "history_events_v2"):
                                total += self._count_v2_events(
                                    shard,
                                    kind=kind,
                                    entity_key=entity_key,
                                    entity_prefix=entity_prefix,
                                    collected_from=collected_from,
                                    collected_to=collected_to,
                                    include_legacy=include_legacy,
                                )
                            if not self._table_exists(
                                shard, "history_events"
                            ) and not self._table_exists(shard, "history_events_v2"):
                                errors.append(f"shard:{path.name}:missing_schema")
                    except (OSError, sqlite3.Error) as exc:
                        errors.append(f"shard:{path.name}:{exc.__class__.__name__}")
            except (OSError, sqlite3.Error) as exc:
                errors.append(f"catalog:{exc.__class__.__name__}")
        self._last_query_errors = tuple(errors)
        return total

    def legacy_source_is_authoritative(self, source_table: str) -> bool:
        """Return whether ordinary readers should still include this legacy table."""

        source = self._validate_legacy_source(source_table)
        state = HistoryLegacyMigrationRepository(
            self.history_root / "catalog.db"
        ).effective_authority_state(source)
        return state not in SHARD_QUERY_AUTHORITY_STATES

    def filter_legacy_rows(
        self, source_table: str, rows: Iterable[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return list(rows) if self.legacy_source_is_authoritative(source_table) else []

    def _kind_uses_shard_authority(self, kind: str) -> bool:
        source = KIND_CANONICAL_LEGACY_SOURCE.get(str(kind or ""))
        return bool(source and not self.legacy_source_is_authoritative(source))

    def _safe_shard_path(self, relative_path: str) -> Path | None:
        """Resolve catalog paths without allowing reads outside the history root."""

        value = str(relative_path or "")
        if not re.fullmatch(r"devices-\d{4}-\d{2}(?:-\d{4})?\.db", value):
            return None
        root = self.history_root.resolve(strict=False)
        candidate = (self.history_root / value).resolve(strict=False)
        if not candidate.is_relative_to(root):
            return None
        return candidate

    def history_health(self) -> dict[str, object]:
        """Expose degraded shard reads without coupling history failures to backend readiness."""

        return {
            "status": "degraded" if self._last_query_errors else "ready",
            "errors": list(self._last_query_errors),
        }

    def migration_checkpoint(self, source_table: str) -> HistoryMigrationCheckpoint | None:
        """Read an explicit maintenance checkpoint; this never creates a catalog."""

        source = self._validate_legacy_source(source_table)
        catalog_path = self.history_root / "catalog.db"
        if not catalog_path.is_file():
            return None
        try:
            with closing(self._connect_readonly(catalog_path)) as catalog:
                if not self._table_exists(catalog, "history_migration_journal"):
                    return None
                row = catalog.execute(
                    "SELECT * FROM history_migration_journal WHERE source_table=?", (source,)
                ).fetchone()
        except (OSError, sqlite3.Error):
            return None
        return self._checkpoint_from_row(dict(row)) if row is not None else None

    def record_migration_checkpoint(
        self,
        source_table: str,
        *,
        last_source_id: int,
        rows_copied: int,
        rows_verified: int,
        status: str,
        rows_skipped: int = 0,
        last_error: str = "",
    ) -> HistoryMigrationCheckpoint:
        """Persist copy/verify progress only; legacy source deletion is deliberately absent."""

        source = self._validate_legacy_source(source_table)
        self.history_root.mkdir(parents=True, exist_ok=True)
        now = _local_now().isoformat(timespec="seconds")
        with closing(connect_sqlite(self.history_root / "catalog.db", foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            catalog.execute(
                """
                INSERT INTO history_migration_journal
                    (source_table, last_source_id, rows_copied, rows_verified, rows_skipped, rows_deleted, status, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(source_table) DO UPDATE SET
                    last_source_id=excluded.last_source_id,
                    rows_copied=excluded.rows_copied,
                    rows_verified=excluded.rows_verified,
                    rows_skipped=excluded.rows_skipped,
                    status=excluded.status,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    max(0, int(last_source_id)),
                    max(0, int(rows_copied)),
                    max(0, int(rows_verified)),
                    max(0, int(rows_skipped)),
                    str(status or "pending"),
                    str(last_error or "")[:1000],
                    now,
                ),
            )
            row = catalog.execute(
                "SELECT * FROM history_migration_journal WHERE source_table=?", (source,)
            ).fetchone()
            catalog.commit()
        return self._checkpoint_from_row(dict(row))

    def migrate_legacy_batch(
        self,
        source_table: str,
        *,
        limit: int = 100,
        unattended_active: bool = False,
    ) -> HistoryMigrationResult:
        """Copy and verify a bounded legacy batch without ever deleting its source.

        This is intentionally not called by startup or the background outbox
        drain. A future maintenance job must opt in after Backend READY and
        pass the persisted unattended state for every batch.
        """

        source = self._validate_legacy_source(source_table)
        if unattended_active:
            return HistoryMigrationResult(source_table=source, paused=True)
        if not self.database_path.is_file():
            return HistoryMigrationResult(source_table=source)
        checkpoint = self.migration_checkpoint(source)
        last_source_id = checkpoint.last_source_id if checkpoint else 0
        safe_limit = max(1, min(int(limit), 500))
        try:
            with closing(self._connect_readonly(self.database_path)) as current:
                if not self._table_exists(current, source):
                    raise ValueError(f"legacy history table is unavailable: {source}")
                rows = current.execute(
                    f"SELECT * FROM {source} WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (last_source_id, safe_limit + 1),
                ).fetchall()
        except (OSError, sqlite3.Error, ValueError) as exc:
            failed = self.record_migration_checkpoint(
                source,
                last_source_id=last_source_id,
                rows_copied=checkpoint.rows_copied if checkpoint else 0,
                rows_verified=checkpoint.rows_verified if checkpoint else 0,
                rows_skipped=checkpoint.rows_skipped if checkpoint else 0,
                status="error",
                last_error=exc.__class__.__name__,
            )
            return HistoryMigrationResult(
                source_table=source, degraded=True, checkpoint=failed
            )

        pending = len(rows) > safe_limit
        batch_rows = [dict(row) for row in rows[:safe_limit]]
        if not batch_rows:
            complete = self.record_migration_checkpoint(
                source,
                last_source_id=last_source_id,
                rows_copied=checkpoint.rows_copied if checkpoint else 0,
                rows_verified=checkpoint.rows_verified if checkpoint else 0,
                rows_skipped=checkpoint.rows_skipped if checkpoint else 0,
                status="complete",
            )
            return HistoryMigrationResult(source_table=source, checkpoint=complete)

        try:
            events: list[dict[str, Any]] = []
            skipped: list[tuple[int, str]] = []
            for row in batch_rows:
                try:
                    events.append(self._legacy_event(source, row))
                except ValueError as exc:
                    skipped.append((int(row["id"]), self._migration_skip_reason(exc)))
            batches: dict[str, list[dict[str, Any]]] = {}
            for event in events:
                batches.setdefault(_period(str(event["collected_at"])), []).append(event)
            for shard_events in batches.values():
                self._write_shard_batch(shard_events)
            if events:
                self._verify_shard_events(events)
            if skipped:
                self._record_migration_skips(source, skipped)
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            failed = self.record_migration_checkpoint(
                source,
                last_source_id=last_source_id,
                rows_copied=checkpoint.rows_copied if checkpoint else 0,
                rows_verified=checkpoint.rows_verified if checkpoint else 0,
                rows_skipped=checkpoint.rows_skipped if checkpoint else 0,
                status="error",
                last_error=exc.__class__.__name__,
            )
            return HistoryMigrationResult(
                source_table=source, pending=True, degraded=True, checkpoint=failed
            )

        copied_before = checkpoint.rows_copied if checkpoint else 0
        verified_before = checkpoint.rows_verified if checkpoint else 0
        skipped_before = checkpoint.rows_skipped if checkpoint else 0
        updated = self.record_migration_checkpoint(
            source,
            last_source_id=int(batch_rows[-1]["id"]),
            rows_copied=copied_before + len(events),
            rows_verified=verified_before + len(events),
            rows_skipped=skipped_before + len(skipped),
            status="pending" if pending else "complete",
        )
        return HistoryMigrationResult(
            source_table=source,
            copied=len(events),
            verified=len(events),
            skipped=len(skipped),
            pending=pending,
            checkpoint=updated,
        )

    @staticmethod
    def _event_dict(row: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(str(row.get("payload_json") or "{}"))
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return {**payload, "event_id": row.get("event_id"), "event_type": row.get("event_type"), "collected_at": row.get("collected_at")}

    @staticmethod
    def _legacy_event(source_table: str, row: dict[str, Any]) -> dict[str, Any]:
        spec = _LEGACY_SOURCE_SPECS[source_table]
        source_id = int(row.get("id") or 0)
        if source_id <= 0:
            raise ValueError(f"legacy history row has no stable id: {source_table}")
        entity_values = [str(row.get(field) or "").strip() for field in spec.entity_fields]
        if not all(entity_values):
            raise ValueError(
                f"legacy history row has no stable entity key: {source_table}:{source_id}"
            )
        collected_at = str(row.get("collected_at") or row.get("created_at") or "").strip()
        if _parse_time(collected_at) is None:
            raise ValueError(
                f"legacy history row has no valid collection time: {source_table}:{source_id}"
            )
        payload = dict(row)
        payload["legacy_source_table"] = source_table
        payload["legacy_source_id"] = source_id
        canonical_identity = HistoryStore._canonical_legacy_identity(
            source_table, row, collected_at=collected_at
        )
        return {
            "event_id": hashlib.sha256(canonical_identity.encode()).hexdigest(),
            "kind": spec.kind,
            "entity_key": ":".join(entity_values),
            "event_type": "legacy",
            "collected_at": collected_at,
            "payload_json": json.dumps(
                _json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            "created_at": str(row.get("created_at") or collected_at),
        }

    @staticmethod
    def _canonical_legacy_identity(
        source_table: str,
        row: dict[str, Any],
        *,
        collected_at: str,
    ) -> str:
        """Return the stable source-row identity for an authoritative legacy fact."""

        del collected_at
        return f"legacy|{source_table}|{int(row.get('id') or 0)}"

    def _verify_shard_events(self, events: list[dict[str, Any]]) -> None:
        """Confirm durable event identity before advancing the source checkpoint."""

        self._verify_shard_event_content(events)

    def _record_migration_skips(
        self, source_table: str, skipped: list[tuple[int, str]]
    ) -> None:
        """Journal rows that cannot be copied without inventing history values.

        The source remains untouched and queryable.  Recording the controlled
        reason lets a future operator repair or explicitly decide each row
        without a malformed legacy value permanently blocking later IDs.
        """

        now = _local_now().isoformat(timespec="seconds")
        self.history_root.mkdir(parents=True, exist_ok=True)
        with closing(connect_sqlite(self.history_root / "catalog.db", foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            catalog.executemany(
                """
                INSERT OR IGNORE INTO history_migration_skips
                    (source_table, source_id, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [(source_table, source_id, reason, now) for source_id, reason in skipped],
            )
            catalog.commit()

    @staticmethod
    def _migration_skip_reason(exc: ValueError) -> str:
        message = str(exc)
        if "stable entity key" in message:
            return "missing_entity_key"
        if "valid collection time" in message:
            return "missing_collection_time"
        return "invalid_legacy_row"

    @staticmethod
    def _sort_unique_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = {str(item["event_id"]): item for item in events}
        return sorted(
            unique.values(),
            key=lambda item: (
                str(item.get("collected_at") or ""),
                str(item.get("event_id") or ""),
            ),
            reverse=True,
        )

    @staticmethod
    def _pending_count_on(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM history_outbox").fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(
            str(row[1]) == column
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        )

    @classmethod
    def _catalog_order_by(
        cls,
        conn: sqlite3.Connection,
        *,
        descending: bool = False,
        include_period: bool = True,
    ) -> str:
        """Order old and current catalogs without mutating a read-only catalog."""

        direction = " DESC" if descending else ""
        columns = ["period_start"] if include_period else []
        if cls._column_exists(conn, "history_catalog", "segment"):
            columns.append("segment")
        columns.append("shard_id")
        return " ORDER BY " + ", ".join(
            f"{column}{direction}" for column in columns
        )

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        uri = f"{Path(path).resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @classmethod
    def _ensure_catalog(cls, conn: sqlite3.Connection) -> None:
        if not cls._table_exists(conn, "history_catalog") or not cls._table_exists(
            conn, "history_migration_journal"
        ):
            conn.executescript(CATALOG_SCHEMA)
            return
        if not cls._column_exists(conn, "history_migration_journal", "rows_skipped"):
            conn.execute(
                "ALTER TABLE history_migration_journal "
                "ADD COLUMN rows_skipped INTEGER NOT NULL DEFAULT 0"
            )
        if not cls._table_exists(conn, "history_migration_skips"):
            conn.execute(
                """
                CREATE TABLE history_migration_skips (
                    source_table TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(source_table, source_id)
                )
                """
            )
        catalog_columns = {
            "domain": "TEXT NOT NULL DEFAULT 'site_history'",
            "segment": "INTEGER NOT NULL DEFAULT 1",
            "size_bytes": "INTEGER NOT NULL DEFAULT 0",
            "sha256": "TEXT NOT NULL DEFAULT ''",
            "content_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "min_business_time": "TEXT NOT NULL DEFAULT ''",
            "max_business_time": "TEXT NOT NULL DEFAULT ''",
            "authority_revision": "INTEGER NOT NULL DEFAULT 1",
            "sealed_at": "TEXT",
        }
        for column, definition in catalog_columns.items():
            if not cls._column_exists(conn, "history_catalog", column):
                conn.execute(
                    f"ALTER TABLE history_catalog ADD COLUMN {column} {definition}"
                )

    @classmethod
    def _ensure_shard(cls, conn: sqlite3.Connection) -> None:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if user_version > STORAGE_SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"unsupported history storage schema version: {user_version}"
            )
        if cls._table_exists(conn, "history_storage_metadata"):
            versions = dict(
                conn.execute(
                    "SELECT key, value FROM history_storage_metadata "
                    "WHERE key IN ('storage_schema_version', 'payload_schema_version')"
                ).fetchall()
            )
            supported = {
                "storage_schema_version": STORAGE_SCHEMA_VERSION,
                "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
            }
            for key, maximum in supported.items():
                if key not in versions:
                    continue
                try:
                    current = int(versions[key])
                except (TypeError, ValueError) as exc:
                    raise sqlite3.DatabaseError(
                        f"invalid history storage metadata: {key}"
                    ) from exc
                if current > maximum:
                    raise sqlite3.DatabaseError(
                        f"unsupported history storage metadata: {key}={current}"
                    )
        conn.executescript(SHARD_SCHEMA_V2)
        conn.execute(
            "INSERT OR REPLACE INTO history_storage_metadata(key, value) VALUES (?, ?)",
            ("storage_schema_version", str(STORAGE_SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO history_storage_metadata(key, value) VALUES (?, ?)",
            ("payload_schema_version", str(PAYLOAD_SCHEMA_VERSION)),
        )
        conn.execute(f"PRAGMA user_version = {STORAGE_SCHEMA_VERSION}")

    @staticmethod
    def _event_id_bytes(event_id: str) -> bytes:
        value = str(event_id or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("history event_id must be a SHA-256 hex digest")
        return bytes.fromhex(value)

    @staticmethod
    def _event_id_text(event_id: Any) -> str:
        if isinstance(event_id, bytes):
            return event_id.hex()
        return str(event_id or "")

    @classmethod
    def _existing_event_ids(
        cls, conn: sqlite3.Connection, event_ids: list[str]
    ) -> set[str]:
        found: set[str] = set()
        unique = sorted(set(event_ids))
        for offset in range(0, len(unique), 500):
            chunk = unique[offset : offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            if cls._table_exists(conn, "history_events"):
                rows = conn.execute(
                    "SELECT event_id FROM history_events WHERE event_id IN ("
                    + placeholders
                    + ")",
                    chunk,
                ).fetchall()
                found.update(str(row[0]) for row in rows)
            if cls._table_exists(conn, "history_events_v2"):
                rows = conn.execute(
                    "SELECT event_id FROM history_events_v2 WHERE event_id IN ("
                    + placeholders
                    + ")",
                    [cls._event_id_bytes(value) for value in chunk],
                ).fetchall()
                found.update(cls._event_id_text(row[0]) for row in rows)
        return found

    @classmethod
    def _read_event_rows_by_id(
        cls, conn: sqlite3.Connection, event_ids: list[str]
    ) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        unique = sorted(set(event_ids))
        for offset in range(0, len(unique), 500):
            chunk = unique[offset : offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows: list[dict[str, Any]] = []
            if cls._table_exists(conn, "history_events"):
                rows.extend(
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM history_events WHERE event_id IN ("
                        + placeholders
                        + ")",
                        chunk,
                    ).fetchall()
                )
            if cls._table_exists(conn, "history_events_v2"):
                rows.extend(cls._read_v2_storage_rows(conn, chunk))
            for row in rows:
                event_id = str(row["event_id"])
                if event_id in found:
                    raise sqlite3.DatabaseError(
                        "duplicate history event identity within shard"
                    )
                found[event_id] = row
        return list(found.values())

    @staticmethod
    def _v2_provenance_sql(conn: sqlite3.Connection) -> tuple[str, str]:
        """Return a compatibility projection for optional legacy provenance."""

        if not HistoryStore._table_exists(conn, "history_event_provenance_v2"):
            return ", NULL AS legacy_source_table, NULL AS legacy_source_id", ""
        return (
            ", p.source_table AS legacy_source_table, p.source_id AS legacy_source_id",
            "LEFT JOIN history_event_provenance_v2 AS p ON p.event_id=e.event_id",
        )

    @staticmethod
    def _dictionary_id(
        conn: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        value_column: str,
        value: str,
    ) -> int:
        conn.execute(
            f"INSERT OR IGNORE INTO {table}({value_column}) VALUES (?)", (value,)
        )
        row = conn.execute(
            f"SELECT {id_column} FROM {table} WHERE {value_column}=?", (value,)
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError(f"history dictionary write failed: {table}")
        return int(row[0])

    @staticmethod
    def _entity_id(
        conn: sqlite3.Connection, *, kind_id: int, entity_key: str
    ) -> int:
        conn.execute(
            "INSERT OR IGNORE INTO history_entities_v2(kind_id, entity_key) VALUES (?, ?)",
            (kind_id, entity_key),
        )
        row = conn.execute(
            "SELECT entity_id FROM history_entities_v2 WHERE kind_id=? AND entity_key=?",
            (kind_id, entity_key),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("history entity dictionary write failed")
        return int(row[0])

    @staticmethod
    def _payload_schema_id(conn: sqlite3.Connection, *, fields_json: str) -> int:
        conn.execute(
            """
            INSERT OR IGNORE INTO history_payload_schemas_v2
                (payload_schema_version, fields_json)
            VALUES (?, ?)
            """,
            (PAYLOAD_SCHEMA_VERSION, fields_json),
        )
        row = conn.execute(
            """
            SELECT payload_schema_id FROM history_payload_schemas_v2
            WHERE payload_schema_version=? AND fields_json=?
            """,
            (PAYLOAD_SCHEMA_VERSION, fields_json),
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("history payload schema write failed")
        return int(row[0])

    @staticmethod
    def _lookup_v2_id(
        conn: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        value_column: str,
        value: str,
    ) -> int | None:
        row = conn.execute(
            f"SELECT {id_column} FROM {table} WHERE {value_column}=?", (value,)
        ).fetchone()
        return int(row[0]) if row is not None else None

    @staticmethod
    def _encode_payload_v2(payload: Any) -> tuple[str, int, bytes]:
        if isinstance(payload, dict):
            normalized = {
                str(key): _json_value(value)
                for key, value in payload.items()
                if str(key) not in _PAYLOAD_ENVELOPE_FIELDS
            }
        else:
            normalized = {"value": _json_value(payload)}
        fields = sorted(normalized)
        fields_json = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
        raw = json.dumps(
            [normalized[field] for field in fields],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        compressed = zlib.compress(raw, level=1)
        if len(compressed) + 4 < len(raw):
            return fields_json, PAYLOAD_CODEC_ZLIB_JSON, compressed
        return fields_json, PAYLOAD_CODEC_JSON, raw

    @staticmethod
    def _decode_payload_v2(row: dict[str, Any]) -> dict[str, Any]:
        schema_version = int(row.get("payload_schema_version") or 0)
        if schema_version != PAYLOAD_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported history payload schema version: {schema_version}"
            )
        encoded = bytes(row.get("payload") or b"")
        codec = int(row.get("payload_codec") or 0)
        if codec not in {PAYLOAD_CODEC_JSON, PAYLOAD_CODEC_ZLIB_JSON}:
            raise ValueError(f"unsupported history payload codec: {codec}")
        try:
            if codec == PAYLOAD_CODEC_ZLIB_JSON:
                encoded = zlib.decompress(encoded)
            values = json.loads(encoded.decode("utf-8"))
            fields = json.loads(str(row.get("fields_json") or "[]"))
        except (UnicodeDecodeError, json.JSONDecodeError, zlib.error) as exc:
            raise ValueError("invalid History Storage V2 payload") from exc
        if not isinstance(fields, list) or not isinstance(values, list) or len(fields) != len(values):
            raise ValueError("invalid History Storage V2 payload")
        return dict(zip((str(field) for field in fields), values, strict=True))

    @staticmethod
    def _query_rows(
        conn: sqlite3.Connection,
        table: str,
        *,
        kind: str,
        entity_key: str | None,
        entity_prefix: str | None,
        limit: int,
        collected_from: str | None,
        collected_to: str | None,
        include_legacy: bool = False,
    ) -> list[sqlite3.Row]:
        # A migration copy is durable verification data, not a new producer
        # event. Keep legacy readers authoritative until their explicit
        # source-table cutover exists, preventing duplicate history results.
        clauses = ["kind=?"]
        if not include_legacy:
            clauses.append("event_type != 'legacy'")
        params: list[Any] = [kind]
        if entity_key is not None:
            clauses.append("entity_key=?")
            params.append(entity_key)
        elif entity_prefix is not None:
            clauses.append("entity_key LIKE ?")
            params.append(f"{entity_prefix}%")
        if collected_from:
            clauses.append("collected_at >= ?")
            params.append(str(collected_from))
        if collected_to:
            clauses.append("collected_at <= ?")
            params.append(str(collected_to))
        params.append(limit)
        return conn.execute(
            "SELECT * FROM "
            + table
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY collected_at DESC, event_id DESC LIMIT ?",
            params,
        ).fetchall()

    @staticmethod
    def _query_rows_for_entities(
        conn: sqlite3.Connection,
        table: str,
        *,
        kind: str,
        entity_keys: list[str],
        event_types: list[str],
        include_legacy: bool = False,
    ) -> list[sqlite3.Row]:
        clauses = ["kind=?", f"entity_key IN ({','.join('?' for _ in entity_keys)})"]
        params: list[Any] = [kind, *entity_keys]
        if not include_legacy:
            clauses.append("event_type != 'legacy'")
        if event_types:
            clauses.append(f"event_type IN ({','.join('?' for _ in event_types)})")
            params.extend(event_types)
        return conn.execute(
            "SELECT * FROM "
            + table
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY collected_at DESC, event_id DESC",
            params,
        ).fetchall()

    @classmethod
    def _query_v2_events(
        cls,
        conn: sqlite3.Connection,
        *,
        kind: str,
        entity_key: str | None,
        entity_prefix: str | None,
        limit: int,
        collected_from: str | None,
        collected_to: str | None,
        include_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        kind_id = cls._lookup_v2_id(
            conn,
            table="history_kinds_v2",
            id_column="kind_id",
            value_column="name",
            value=kind,
        )
        if kind_id is None:
            return []
        clauses = ["e.kind_id=?"]
        params: list[Any] = [kind_id]
        if entity_key is not None:
            entity_row = conn.execute(
                "SELECT entity_id FROM history_entities_v2 "
                "WHERE kind_id=? AND entity_key=?",
                (kind_id, entity_key),
            ).fetchone()
            if entity_row is None:
                return []
            clauses.append("e.entity_id=?")
            params.append(int(entity_row[0]))
        elif entity_prefix is not None:
            clauses.append("n.entity_key LIKE ?")
            params.append(f"{entity_prefix}%")
        legacy_type_id = cls._lookup_v2_id(
            conn,
            table="history_event_types_v2",
            id_column="event_type_id",
            value_column="name",
            value="legacy",
        )
        if legacy_type_id is not None and not include_legacy:
            clauses.append("e.event_type_id != ?")
            params.append(legacy_type_id)
        if collected_from:
            clauses.append("e.collected_at >= ?")
            params.append(str(collected_from))
        if collected_to:
            clauses.append("e.collected_at <= ?")
            params.append(str(collected_to))
        params.append(limit)
        index_name = (
            "idx_history_events_v2_entity_time"
            if entity_key is not None
            else "idx_history_events_v2_kind_time"
        )
        provenance_select, provenance_join = cls._v2_provenance_sql(conn)
        rows = conn.execute(
            """
            SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
                   e.collected_at, e.payload_codec, e.payload, e.created_at,
                   s.payload_schema_version, s.fields_json
            """
            + provenance_select
            + """
            FROM history_events_v2 AS e INDEXED BY """
            + index_name
            + " "
            + """
            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
            JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
            JOIN history_payload_schemas_v2 AS s
              ON s.payload_schema_id=e.payload_schema_id
            """
            + provenance_join
            + """
            WHERE """
            + " AND ".join(clauses)
            + " ORDER BY e.collected_at DESC, e.event_id DESC LIMIT ?",
            params,
        ).fetchall()
        return [cls._event_dict_v2(dict(row)) for row in rows]

    @classmethod
    def _query_v2_events_for_entities(
        cls,
        conn: sqlite3.Connection,
        *,
        kind: str,
        entity_keys: list[str],
        event_types: list[str],
        include_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        kind_id = cls._lookup_v2_id(
            conn,
            table="history_kinds_v2",
            id_column="kind_id",
            value_column="name",
            value=kind,
        )
        if kind_id is None:
            return []
        clauses = ["e.kind_id=?", f"n.entity_key IN ({','.join('?' for _ in entity_keys)})"]
        params: list[Any] = [kind_id, *entity_keys]
        if not include_legacy:
            clauses.append("t.name != 'legacy'")
        if event_types:
            clauses.append(f"t.name IN ({','.join('?' for _ in event_types)})")
            params.extend(event_types)
        provenance_select, provenance_join = cls._v2_provenance_sql(conn)
        rows = conn.execute(
            """
            SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
                   e.collected_at, e.payload_codec, e.payload, e.created_at,
                   s.payload_schema_version, s.fields_json
            """
            + provenance_select
            + """
            FROM history_events_v2 AS e INDEXED BY idx_history_events_v2_kind_time
            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
            JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
            JOIN history_payload_schemas_v2 AS s
              ON s.payload_schema_id=e.payload_schema_id
            """
            + provenance_join
            + """
            WHERE """
            + " AND ".join(clauses)
            + " ORDER BY e.collected_at DESC, e.event_id DESC",
            params,
        ).fetchall()
        return [cls._event_dict_v2(dict(row)) for row in rows]

    @classmethod
    def _count_v2_events(
        cls,
        conn: sqlite3.Connection,
        *,
        kind: str,
        entity_key: str | None,
        entity_prefix: str | None,
        collected_from: str | None,
        collected_to: str | None,
        include_legacy: bool = False,
    ) -> int:
        kind_id = cls._lookup_v2_id(
            conn,
            table="history_kinds_v2",
            id_column="kind_id",
            value_column="name",
            value=kind,
        )
        if kind_id is None:
            return 0
        clauses = ["e.kind_id=?"]
        params: list[Any] = [kind_id]
        join_entity = entity_prefix is not None and entity_key is None
        if entity_key is not None:
            entity_row = conn.execute(
                "SELECT entity_id FROM history_entities_v2 "
                "WHERE kind_id=? AND entity_key=?",
                (kind_id, entity_key),
            ).fetchone()
            if entity_row is None:
                return 0
            clauses.append("e.entity_id=?")
            params.append(int(entity_row[0]))
        elif entity_prefix is not None:
            clauses.append("n.entity_key LIKE ?")
            params.append(f"{entity_prefix}%")
        legacy_type_id = cls._lookup_v2_id(
            conn,
            table="history_event_types_v2",
            id_column="event_type_id",
            value_column="name",
            value="legacy",
        )
        if legacy_type_id is not None and not include_legacy:
            clauses.append("e.event_type_id != ?")
            params.append(legacy_type_id)
        if collected_from:
            clauses.append("e.collected_at >= ?")
            params.append(str(collected_from))
        if collected_to:
            clauses.append("e.collected_at <= ?")
            params.append(str(collected_to))
        index_name = (
            "idx_history_events_v2_entity_time"
            if entity_key is not None
            else "idx_history_events_v2_kind_time"
        )
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM history_events_v2 AS e INDEXED BY """
            + index_name
            + " "
            + """
            """
            + (
                "JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id "
                if join_entity
                else ""
            )
            + "WHERE "
            + " AND ".join(clauses),
            params,
        ).fetchone()
        return int(row["total"] if row is not None else 0)

    @classmethod
    def _read_v2_storage_rows(
        cls, conn: sqlite3.Connection, event_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not event_ids:
            return []
        placeholders = ", ".join("?" for _ in event_ids)
        provenance_select, provenance_join = cls._v2_provenance_sql(conn)
        rows = conn.execute(
            """
            SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
                   e.collected_at, e.payload_codec, e.payload, e.created_at,
                   s.payload_schema_version, s.fields_json
            """
            + provenance_select
            + """
            FROM history_events_v2 AS e
            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
            JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
            JOIN history_payload_schemas_v2 AS s
              ON s.payload_schema_id=e.payload_schema_id
            """
            + provenance_join
            + """
            WHERE e.event_id IN ("""
            + placeholders
            + ")",
            [cls._event_id_bytes(value) for value in event_ids],
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            payload = cls._decode_payload_v2(item)
            payload["collected_at"] = item["collected_at"]
            if item.get("legacy_source_table") is not None:
                payload["legacy_source_table"] = item["legacy_source_table"]
                payload["legacy_source_id"] = int(item["legacy_source_id"])
            output.append(
                {
                    "event_id": cls._event_id_text(item["event_id"]),
                    "kind": item["kind"],
                    "entity_key": item["entity_key"],
                    "event_type": item["event_type"],
                    "collected_at": item["collected_at"],
                    "payload_json": json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "created_at": item["created_at"],
                }
            )
        return output

    @classmethod
    def _event_dict_v2(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = cls._decode_payload_v2(row)
        if row.get("legacy_source_table") is not None:
            payload["legacy_source_table"] = row["legacy_source_table"]
            payload["legacy_source_id"] = int(row["legacy_source_id"])
        result = {
            **payload,
            "event_id": cls._event_id_text(row.get("event_id")),
            "event_type": row.get("event_type"),
            "collected_at": row.get("collected_at"),
        }
        return result

    @staticmethod
    def _validate_legacy_source(source_table: str) -> str:
        source = str(source_table or "").strip()
        if source not in LEGACY_HISTORY_TABLES:
            raise ValueError(f"unsupported legacy history source: {source}")
        return source

    @staticmethod
    def _checkpoint_from_row(row: dict[str, Any]) -> HistoryMigrationCheckpoint:
        return HistoryMigrationCheckpoint(
            source_table=str(row["source_table"]),
            last_source_id=int(row.get("last_source_id") or 0),
            rows_copied=int(row.get("rows_copied") or 0),
            rows_verified=int(row.get("rows_verified") or 0),
            rows_skipped=int(row.get("rows_skipped") or 0),
            rows_deleted=int(row.get("rows_deleted") or 0),
            status=str(row.get("status") or "pending"),
            last_error=str(row.get("last_error") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


TASK_EVENT_HISTORY_KIND = "task_event"
TASK_RESULT_HISTORY_KIND = "task_result"


def verify_task_result_row(row: dict[str, Any]) -> dict[str, Any]:
    """Validate the immutable task-result authority before archive or read-through."""

    canonical = str(row.get("canonical_json") or "")
    encoded = canonical.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != str(row.get("sha256") or ""):
        raise sqlite3.DatabaseError("task result hash mismatch")
    if len(encoded) != int(row.get("byte_size") or -1):
        raise sqlite3.DatabaseError("task result byte size mismatch")
    expected_id = "tr-" + hashlib.sha256(
        (
            f"{row.get('task_id', '')}\0"
            f"{row.get('terminal_event_type', '')}\0{digest}"
        ).encode("utf-8")
    ).hexdigest()
    if expected_id != str(row.get("result_id") or ""):
        raise sqlite3.DatabaseError("task result deterministic identity mismatch")
    try:
        result = json.loads(canonical)
    except json.JSONDecodeError as exc:
        raise sqlite3.DatabaseError("task result canonical JSON is invalid") from exc
    if not isinstance(result, dict):
        raise sqlite3.DatabaseError("task result canonical JSON must be an object")
    return {**row, "result": result}


class TaskHistoryStore:
    """Task-domain adapter over the shared catalog and monthly shard owner."""

    def __init__(
        self,
        tasks_database: str | Path,
        *,
        site_id: str = "",
        history_root: str | Path | None = None,
        segment_max_bytes: int | None = None,
    ) -> None:
        database = Path(tasks_database)
        self.store = HistoryStore(
            database,
            site_id=site_id,
            history_root=Path(history_root) if history_root is not None else None,
            segment_max_bytes=segment_max_bytes,
        )

    @property
    def history_root(self) -> Path:
        return self.store.history_root

    @classmethod
    def event_archive_record(cls, row: dict[str, Any]) -> dict[str, Any]:
        task_id = str(row.get("task_id") or "").strip()
        source_event_id = str(row.get("event_id") or "").strip()
        event_type = str(row.get("event_type") or "").strip()
        event_time = str(row.get("event_time") or "").strip()
        if not task_id or not source_event_id or not event_type or _parse_time(event_time) is None:
            raise ValueError("task history event identity is incomplete")
        try:
            task_payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("task history event payload is invalid") from exc
        if not isinstance(task_payload, dict):
            raise ValueError("task history event payload must be an object")
        payload = {
            "sequence": int(row.get("sequence") or 0),
            "source_event_id": source_event_id,
            "task_id": task_id,
            "task_event_type": event_type,
            "event_time": event_time,
            "source": str(row.get("source") or "service"),
            "payload": task_payload,
        }
        canonical = cls.source_row_digest(payload)
        archive_id = hashlib.sha256(
            f"task-event\0{source_event_id}\0{canonical}".encode("utf-8")
        ).hexdigest()
        return {
            "event_id": archive_id,
            "kind": TASK_EVENT_HISTORY_KIND,
            "entity_key": task_id,
            "event_type": event_type,
            "collected_at": event_time,
            "payload_json": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "created_at": event_time,
        }

    @classmethod
    def result_archive_record(cls, row: dict[str, Any]) -> dict[str, Any]:
        row = verify_task_result_row(row)
        result_id = str(row.get("result_id") or "").strip()
        task_id = str(row.get("task_id") or "").strip()
        terminal_type = str(row.get("terminal_event_type") or "").strip()
        created_time = str(row.get("created_time") or "").strip()
        if not result_id or not task_id or not terminal_type or _parse_time(created_time) is None:
            raise ValueError("task result history identity is incomplete")
        payload = {
            "result_id": result_id,
            "task_id": task_id,
            "terminal_event_type": terminal_type,
            "canonical_json": str(row.get("canonical_json") or ""),
            "sha256": str(row.get("sha256") or ""),
            "byte_size": int(row.get("byte_size") or 0),
            "schema_version": int(row.get("schema_version") or 0),
            "created_time": created_time,
        }
        canonical = cls.source_row_digest(payload)
        archive_id = hashlib.sha256(
            f"task-result\0{result_id}\0{canonical}".encode("utf-8")
        ).hexdigest()
        return {
            "event_id": archive_id,
            "kind": TASK_RESULT_HISTORY_KIND,
            "entity_key": result_id,
            "event_type": terminal_type,
            "collected_at": created_time,
            "payload_json": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "created_at": created_time,
        }

    def archive_event_rows(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        return self.store.copy_verified_events(
            [self.event_archive_record(row) for row in rows]
        )

    def archive_result_rows(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        return self.store.copy_verified_events(
            [self.result_archive_record(row) for row in rows]
        )

    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = 2000,
    ) -> list[dict[str, Any]]:
        safe_limit = None if limit is None else max(1, min(int(limit), 10000))
        events = self.list_events_for_tasks([task_id]).get(str(task_id), [])
        filtered = [
            event
            for event in events
            if int(event.get("sequence") or 0) > max(0, int(after_sequence))
        ]
        return filtered if safe_limit is None else filtered[:safe_limit]

    def list_events_for_tasks(
        self,
        task_ids: Iterable[str],
        *,
        event_types: Iterable[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        ids = sorted(
            {str(task_id).strip() for task_id in task_ids if str(task_id).strip()}
        )
        grouped: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in ids}
        if not ids:
            return grouped
        events = self.store.query_events_for_entities(
            kind=TASK_EVENT_HISTORY_KIND,
            entity_keys=ids,
            event_types=event_types,
        )
        for event in events:
            sequence = int(event.get("sequence") or 0)
            source_event_id = str(event.get("source_event_id") or "")
            payload = event.get("payload")
            event_task_id = str(event.get("task_id") or "")
            if (
                event_task_id not in grouped
                or not source_event_id
                or not isinstance(payload, dict)
            ):
                continue
            grouped[event_task_id].append({
                "sequence": sequence,
                "event_id": source_event_id,
                "task_id": event_task_id,
                "event_type": str(event.get("task_event_type") or event.get("event_type") or ""),
                "event_time": str(event.get("event_time") or event.get("collected_at") or ""),
                "source": str(event.get("source") or "service"),
                "payload_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            })
        for event_task_id, rows in grouped.items():
            deduplicated = {str(row["event_id"]): row for row in rows}
            grouped[event_task_id] = sorted(
                deduplicated.values(),
                key=lambda row: (int(row["sequence"]), str(row["event_id"])),
            )
        return grouped

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        events = self.store.query_events(
            kind=TASK_RESULT_HISTORY_KIND,
            entity_key=str(result_id),
            limit=2,
        )
        if not events:
            return None
        row = events[0]
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
        if not required.issubset(row):
            raise sqlite3.DatabaseError("archived task result is incomplete")
        result = {key: row[key] for key in required}
        verify_task_result_row(result)
        return result

    def counts(self) -> dict[str, int]:
        return {
            "task_events": self.store.count_events(kind=TASK_EVENT_HISTORY_KIND),
            "task_results": self.store.count_events(kind=TASK_RESULT_HISTORY_KIND),
        }

    @staticmethod
    def source_row_digest(value: object) -> str:
        encoded = json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class HistoryRetentionPolicy:
    """Policy declaration; cleanup remains explicit and never runs at startup."""

    change_event_days: int | None = None
    heartbeat_days: int | None = None
    raw_days: int | None = None

    def cutoff_for(self, event_type: str, now: datetime | None = None) -> datetime | None:
        days = {
            "change": self.change_event_days,
            "heartbeat": self.heartbeat_days,
            "raw": self.raw_days,
        }.get(str(event_type))
        if days is None:
            return None
        return (now or _local_now()) - timedelta(days=max(0, int(days)))


__all__ = [
    "HistoryDrainResult",
    "HistoryMigrationCheckpoint",
    "HistoryRetentionPolicy",
    "HistoryStore",
    "TaskHistoryStore",
    "verify_task_result_row",
    "fingerprint",
]
