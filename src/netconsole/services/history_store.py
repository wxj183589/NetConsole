"""Bounded, change-aware history storage for site device databases.

The primary database remains authoritative for current state.  History events
are first committed to a small outbox in that same transaction and are later
drained into a month-partitioned shard.  This deliberately avoids a cross-file
SQLite transaction and keeps startup free of history scans or maintenance.
"""

from __future__ import annotations

import hashlib
import json
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

from netconsole.core.sqlite_utils import connect_sqlite

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
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    closed_at TEXT
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
    ) -> None:
        self.database_path = Path(database_path)
        self.site_id = str(site_id or self.database_path.parent.parent.name)
        self.history_root = Path(history_root or self.database_path.parent / "history")
        self.heartbeat_seconds = {**TELEMETRY_SAMPLING_SECONDS, **(heartbeat_seconds or {})}
        self._clock = clock
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
        shard_path = self.history_root / f"devices-{period}.db"
        catalog_path = self.history_root / "catalog.db"
        with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
            self._ensure_catalog(catalog)
            now = self._now().isoformat(timespec="seconds")
            relative_path = shard_path.name
            is_current_period = period == self._now().strftime("%Y-%m")
            catalog.execute(
                "UPDATE history_catalog SET status='CLOSED', closed_at=? "
                "WHERE status='ACTIVE' AND shard_id < ?",
                (now, period),
            )
            year, month = (int(part) for part in period.split("-", 1))
            last_day = monthrange(year, month)[1]
            catalog.execute(
                """
                INSERT INTO history_catalog
                    (shard_id, site_id, period_start, period_end, relative_path,
                     schema_version, status, created_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shard_id) DO UPDATE SET
                    relative_path=excluded.relative_path,
                    schema_version=MAX(history_catalog.schema_version, excluded.schema_version),
                    status=excluded.status,
                    closed_at=excluded.closed_at
                """,
                (
                    period,
                    self.site_id,
                    f"{period}-01",
                    f"{period}-{last_day:02d}",
                    relative_path,
                    STORAGE_SCHEMA_VERSION,
                    "ACTIVE" if is_current_period else "CLOSED",
                    now,
                    None if is_current_period else now,
                ),
            )
            catalog.commit()
        inserted = 0
        with closing(connect_sqlite(shard_path, foreign_keys=True)) as shard:
            self._ensure_shard(shard)
            existing = self._existing_event_ids(
                shard, [str(row["event_id"]) for row in rows]
            )
            kind_ids: dict[str, int] = {}
            entity_ids: dict[tuple[int, str], int] = {}
            event_type_ids: dict[str, int] = {}
            payload_schema_ids: dict[str, int] = {}
            for row in rows:
                event_id = str(row["event_id"])
                if event_id in existing:
                    continue
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
                inserted += max(0, cursor.rowcount)
            shard.commit()
        if inserted:
            with closing(connect_sqlite(catalog_path, foreign_keys=True)) as catalog:
                catalog.execute(
                    "UPDATE history_catalog SET row_count=row_count+1 WHERE shard_id=?",
                    (period,),
                )
                if inserted > 1:
                    catalog.execute(
                        "UPDATE history_catalog SET row_count=row_count+? WHERE shard_id=?",
                        (inserted - 1, period),
                    )
                catalog.commit()
        return inserted

    def copy_legacy_migration_events(
        self, events: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Write and durably verify an explicit COPY-only migration chunk."""

        inserted = 0
        batches: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if str(event.get("event_type") or "") != "legacy":
                raise ValueError("migration events must use event_type=legacy")
            batches.setdefault(_period(str(event["collected_at"])), []).append(event)
        for batch in batches.values():
            inserted += self._write_shard_batch(batch)
        if events:
            self._verify_shard_events(events)
        return inserted, len(events)

    def read_legacy_migration_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Read exact copied events for digest/sample verification."""

        found: dict[str, dict[str, Any]] = {}
        by_period: dict[str, list[str]] = {}
        for event in events:
            by_period.setdefault(_period(str(event["collected_at"])), []).append(
                str(event["event_id"])
            )
        for period, event_ids in by_period.items():
            event_ids = sorted(set(event_ids))
            shard_path = self.history_root / f"devices-{period}.db"
            with closing(self._connect_readonly(shard_path)) as shard:
                for offset in range(0, len(event_ids), 500):
                    chunk = event_ids[offset : offset + 500]
                    placeholders = ", ".join("?" for _ in chunk)
                    if self._table_exists(shard, "history_events"):
                        rows = shard.execute(
                            "SELECT * FROM history_events WHERE event_id IN ("
                            + placeholders
                            + ")",
                            chunk,
                        ).fetchall()
                        found.update((str(row["event_id"]), dict(row)) for row in rows)
                    if self._table_exists(shard, "history_events_v2"):
                        rows_v2 = self._read_v2_storage_rows(shard, chunk)
                        found.update((str(row["event_id"]), row) for row in rows_v2)
        return [found[str(event["event_id"])] for event in events if str(event["event_id"]) in found]

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
                clauses = ["status IN ('ACTIVE','CLOSED','ARCHIVED')"]
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
                    + " ORDER BY period_start DESC",
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
                                )
                            )
                    events.extend(shard_events)
                    events = self._sort_unique_events(events)[:requested]
                    # Catalog periods never overlap. Once one period itself
                    # supplies a complete page, older periods cannot affect it.
                    if len(shard_events) >= requested and len(events) >= requested:
                        break
                except (OSError, sqlite3.Error) as exc:
                    errors.append(f"shard:{path.name}:{exc.__class__.__name__}")
                    continue
        except (OSError, sqlite3.Error) as exc:
            errors.append(f"catalog:{exc.__class__.__name__}")
        self._last_query_errors = tuple(errors)
        return self._sort_unique_events(events)[safe_offset:requested]

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

        def count_rows(conn: sqlite3.Connection, table: str) -> int:
            # Copied legacy rows remain intentionally hidden until a future
            # per-table cutover can exclude their source rows. Otherwise an
            # old database would return the legacy row and its verified copy.
            clauses = ["kind = ?", "event_type != 'legacy'"]
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
                        total += count_rows(current, "history_outbox")
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
                    clauses = ["status IN ('ACTIVE','CLOSED','ARCHIVED')"]
                    params: list[Any] = []
                    if collected_from:
                        clauses.append("period_end >= ?")
                        params.append(str(collected_from)[:7])
                    if collected_to:
                        clauses.append("period_start <= ?")
                        params.append(f"{str(collected_to)[:7]}-31")
                    shards = catalog.execute(
                        "SELECT relative_path FROM history_catalog WHERE "
                        + " AND ".join(clauses),
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
                                total += count_rows(shard, "history_events")
                            if self._table_exists(shard, "history_events_v2"):
                                total += self._count_v2_events(
                                    shard,
                                    kind=kind,
                                    entity_key=entity_key,
                                    entity_prefix=entity_prefix,
                                    collected_from=collected_from,
                                    collected_to=collected_to,
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

    def _safe_shard_path(self, relative_path: str) -> Path | None:
        """Resolve catalog paths without allowing reads outside the history root."""

        value = str(relative_path or "")
        if not re.fullmatch(r"devices-\d{4}-\d{2}\.db", value):
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

        by_period: dict[str, list[str]] = {}
        for event in events:
            by_period.setdefault(_period(str(event["collected_at"])), []).append(
                str(event["event_id"])
            )
        for period, event_ids in by_period.items():
            shard_path = self.history_root / f"devices-{period}.db"
            with closing(self._connect_readonly(shard_path)) as shard:
                found = self._existing_event_ids(shard, event_ids)
            if found != set(event_ids):
                raise sqlite3.DatabaseError("legacy history shard verification failed")

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
    ) -> list[sqlite3.Row]:
        # A migration copy is durable verification data, not a new producer
        # event. Keep legacy readers authoritative until their explicit
        # source-table cutover exists, preventing duplicate history results.
        clauses = ["kind=?", "event_type != 'legacy'"]
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
        if legacy_type_id is not None:
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
        rows = conn.execute(
            """
            SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
                   e.collected_at, e.payload_codec, e.payload, e.created_at,
                   s.payload_schema_version, s.fields_json
            FROM history_events_v2 AS e INDEXED BY """
            + index_name
            + " "
            + """
            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
            JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
            JOIN history_payload_schemas_v2 AS s
              ON s.payload_schema_id=e.payload_schema_id
            WHERE """
            + " AND ".join(clauses)
            + " ORDER BY e.collected_at DESC, e.event_id DESC LIMIT ?",
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
        if legacy_type_id is not None:
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
        rows = conn.execute(
            """
            SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
                   e.collected_at, e.payload_codec, e.payload, e.created_at,
                   s.payload_schema_version, s.fields_json
            FROM history_events_v2 AS e
            JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
            JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
            JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
            JOIN history_payload_schemas_v2 AS s
              ON s.payload_schema_id=e.payload_schema_id
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
    "fingerprint",
]
