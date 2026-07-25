from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO


SCHEMA = """
CREATE TABLE IF NOT EXISTS ground_unattended_schema (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_unattended_profiles (
    site_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    schedule_start_time TEXT NOT NULL DEFAULT '07:00',
    schedule_end_time TEXT NOT NULL DEFAULT '23:00',
    timezone TEXT NOT NULL DEFAULT 'system',
    ac_poll_interval_seconds INTEGER NOT NULL DEFAULT 10,
    stationary_exclusion_minutes INTEGER NOT NULL DEFAULT 10,
    ac_stale_grace_seconds INTEGER NOT NULL DEFAULT 120,
    ac_ping_correlation_tolerance_seconds INTEGER NOT NULL DEFAULT 15,
    ap_switch_before_seconds INTEGER NOT NULL DEFAULT 5,
    ap_switch_after_seconds INTEGER NOT NULL DEFAULT 5,
    max_active_trains INTEGER NOT NULL DEFAULT 2,
    max_active_mrs INTEGER NOT NULL DEFAULT 4,
    max_starting_mrs INTEGER NOT NULL DEFAULT 2,
    max_finalizing_mrs INTEGER NOT NULL DEFAULT 2,
    fleet_ping_interval_ms INTEGER NOT NULL DEFAULT 1000,
    fleet_ping_timeout_ms INTEGER NOT NULL DEFAULT 4000,
    fleet_ping_packet_size INTEGER NOT NULL DEFAULT 64,
    fleet_ping_shard_size INTEGER NOT NULL DEFAULT 12,
    minimum_valid_collection_minutes INTEGER NOT NULL DEFAULT 10,
    preferred_collection_minutes INTEGER NOT NULL DEFAULT 20,
    maximum_collection_minutes INTEGER NOT NULL DEFAULT 30,
    start_jitter_seconds INTEGER NOT NULL DEFAULT 3,
    start_batch_size INTEGER NOT NULL DEFAULT 1,
    detail_retention_days INTEGER NOT NULL DEFAULT 30,
    summary_retention_days INTEGER NOT NULL DEFAULT 180,
    storage_warning_free_gb REAL NOT NULL DEFAULT 5.0,
    storage_critical_free_gb REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_unattended_priority_trains (
    site_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, train_id)
);

CREATE TABLE IF NOT EXISTS ground_unattended_runs (
    run_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    state TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    requested_action TEXT NOT NULL DEFAULT '',
    scheduled_start_at TEXT NOT NULL DEFAULT '',
    scheduled_end_at TEXT NOT NULL DEFAULT '',
    actual_started_at TEXT NOT NULL DEFAULT '',
    actual_ended_at TEXT NOT NULL DEFAULT '',
    ac_last_updated_at TEXT NOT NULL DEFAULT '',
    ac_freshness_status TEXT NOT NULL DEFAULT 'NO_DATA',
    ping_sample_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site_id, run_date)
);
CREATE INDEX IF NOT EXISTS idx_ground_runs_site_state
ON ground_unattended_runs(site_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_train_runs (
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    train_id TEXT NOT NULL,
    train_no TEXT NOT NULL DEFAULT '',
    train_name TEXT NOT NULL DEFAULT '',
    coverage_status TEXT NOT NULL DEFAULT 'NOT_SEEN',
    priority INTEGER NOT NULL DEFAULT 0,
    ping_eligible INTEGER NOT NULL DEFAULT 0,
    deep_collection_eligible INTEGER NOT NULL DEFAULT 0,
    eligibility_status TEXT NOT NULL DEFAULT 'AC_UNKNOWN',
    exclusion_reason TEXT NOT NULL DEFAULT '',
    current_ap_identity TEXT NOT NULL DEFAULT '',
    current_ap_name TEXT NOT NULL DEFAULT '',
    current_ap_mac TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    mileage TEXT NOT NULL DEFAULT '',
    rssi INTEGER,
    same_ap_since TEXT NOT NULL DEFAULT '',
    same_ap_duration_seconds INTEGER NOT NULL DEFAULT 0,
    ac_snapshot_id INTEGER,
    ac_received_at TEXT NOT NULL DEFAULT '',
    endpoints_json TEXT NOT NULL DEFAULT '[]',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    covered_rounds INTEGER NOT NULL DEFAULT 0,
    selection_reason TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    collection_started_at TEXT NOT NULL DEFAULT '',
    valid_duration_minutes REAL NOT NULL DEFAULT 0,
    operations_json TEXT NOT NULL DEFAULT '{}',
    sessions_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, run_id, train_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_train_runs_coverage
ON ground_unattended_train_runs(site_id, run_id, coverage_status, priority DESC, attempt_count);

CREATE TABLE IF NOT EXISTS ground_unattended_daily_queues (
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    candidate_train_ids_json TEXT NOT NULL,
    queue_order_json TEXT NOT NULL,
    PRIMARY KEY (site_id, run_id)
);

CREATE TABLE IF NOT EXISTS ground_unattended_ac_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    ac_device_id TEXT NOT NULL DEFAULT '',
    source_snapshot_id INTEGER,
    device_time TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    train_no TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    mr_position_code TEXT NOT NULL DEFAULT '',
    mr_online_status TEXT NOT NULL DEFAULT 'unknown',
    peer_ap_name TEXT NOT NULL DEFAULT '',
    peer_ap_mac TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    mileage TEXT NOT NULL DEFAULT '',
    rssi INTEGER,
    freshness_status TEXT NOT NULL DEFAULT 'no_data',
    raw_source_reference TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ground_ac_received
ON ground_unattended_ac_snapshots(site_id, run_id, received_at, train_id, mr_id);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_segments (
    segment_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    shard_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    target_count INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_ping_segments_run
ON ground_unattended_ping_segments(site_id, run_id, started_at);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    bucket_kind TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    bucket_end TEXT NOT NULL,
    target_ip TEXT NOT NULL DEFAULT '',
    train_id TEXT NOT NULL DEFAULT '',
    train_no TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    mr_position_code TEXT NOT NULL DEFAULT '',
    ac_snapshot_id INTEGER,
    ap_identity TEXT NOT NULL DEFAULT '',
    sent_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    loss_rate_percent REAL NOT NULL DEFAULT 0,
    min_rtt_ms REAL,
    avg_rtt_ms REAL,
    max_rtt_ms REAL,
    continuous_loss_max_count INTEGER NOT NULL DEFAULT 0,
    continuous_loss_max_seconds REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (site_id, run_id, bucket_kind, bucket_start, target_ip, ap_identity)
);
CREATE INDEX IF NOT EXISTS idx_ground_ping_summary_query
ON ground_unattended_ping_summaries(site_id, run_id, bucket_kind, train_id, mr_id, bucket_start DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_deep_operations (
    operation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    mr_id TEXT NOT NULL,
    mr_position_code TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'STARTING',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    stop_reason TEXT NOT NULL DEFAULT '',
    error_summary TEXT NOT NULL DEFAULT '',
    finalization_complete INTEGER NOT NULL DEFAULT 0,
    package_verified INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_deep_active
ON ground_unattended_deep_operations(site_id, run_id, state, train_id);

CREATE TABLE IF NOT EXISTS ground_unattended_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    train_id TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ground_events_timeline
ON ground_unattended_events(site_id, run_id, ts DESC, event_type);

CREATE TABLE IF NOT EXISTS ground_unattended_archives (
    archive_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    relative_path TEXT NOT NULL DEFAULT '',
    archive_status TEXT NOT NULL DEFAULT 'PENDING',
    archive_size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    manifest_sha256 TEXT NOT NULL DEFAULT '',
    retention_until TEXT NOT NULL DEFAULT '',
    active_cleanup_pending INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_archives_site_date
ON ground_unattended_archives(site_id, run_date DESC);
"""


_RUN_STATES_ACTIVE = {
    "STARTING",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "FINALIZING",
    "ARCHIVING",
    "ERROR",
}


class GroundUnattendedRepository:
    def __init__(self, db_path: Path, *, site_id: str) -> None:
        self.db_path = Path(db_path)
        self.site_id = str(site_id)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                """
                INSERT INTO ground_unattended_schema(key, value, updated_at)
                VALUES('schema_version', '1', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (_now(),),
            )

    def get_profile(self) -> GroundUnattendedProfileDTO:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_profiles WHERE site_id=?",
                (self.site_id,),
            ).fetchone()
        if row is None:
            profile = GroundUnattendedProfileDTO(site_id=self.site_id)
            payload = profile.model_dump(mode="json")
            fields = tuple(payload)
            values = [
                int(value) if isinstance(value, bool) else value
                for value in payload.values()
            ]
            with self._transaction() as conn:
                conn.execute(
                    f"INSERT INTO ground_unattended_profiles ({', '.join(fields)}) "
                    f"VALUES ({', '.join('?' for _ in fields)}) "
                    "ON CONFLICT(site_id) DO NOTHING",
                    values,
                )
                row = conn.execute(
                    "SELECT * FROM ground_unattended_profiles WHERE site_id=?",
                    (self.site_id,),
                ).fetchone()
            if row is None:
                raise RuntimeError("ground unattended profile was not created")
        return GroundUnattendedProfileDTO.model_validate(dict(row))

    def save_profile(
        self, profile: GroundUnattendedProfileDTO
    ) -> GroundUnattendedProfileDTO:
        if profile.site_id != self.site_id:
            raise ValueError("profile site_id mismatch")
        now = _now()
        payload = profile.model_copy(
            update={"created_at": profile.created_at or now, "updated_at": now}
        ).model_dump(mode="json")
        fields = tuple(payload)
        values = [
            int(value) if isinstance(value, bool) else value
            for value in payload.values()
        ]
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_profiles ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(site_id) DO UPDATE SET {updates}",
                values,
            )
        return GroundUnattendedProfileDTO.model_validate(payload)

    def list_priority_train_ids(self) -> set[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT train_id FROM ground_unattended_priority_trains WHERE site_id=? AND priority=1",
                (self.site_id,),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def set_priority(self, train_id: str, priority: bool) -> None:
        now = _now()
        with self._transaction() as conn:
            if priority:
                conn.execute(
                    """
                    INSERT INTO ground_unattended_priority_trains(site_id, train_id, priority, updated_at)
                    VALUES(?, ?, 1, ?)
                    ON CONFLICT(site_id, train_id) DO UPDATE SET priority=1, updated_at=excluded.updated_at
                    """,
                    (self.site_id, train_id, now),
                )
            else:
                conn.execute(
                    "DELETE FROM ground_unattended_priority_trains WHERE site_id=? AND train_id=?",
                    (self.site_id, train_id),
                )

    def create_or_get_run(
        self,
        *,
        run_id: str,
        run_date: str,
        scheduled_start_at: str,
        scheduled_end_at: str,
        state: str = "STARTING",
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_unattended_runs(
                    run_id, site_id, run_date, state, scheduled_start_at, scheduled_end_at,
                    actual_started_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, run_date) DO NOTHING
                """,
                (
                    run_id,
                    self.site_id,
                    run_date,
                    state,
                    scheduled_start_at,
                    scheduled_end_at,
                    now,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? AND run_date=?",
                (self.site_id, run_date),
            ).fetchone()
        if row is None:
            raise RuntimeError("ground unattended run was not created")
        return _decode_row(row)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? AND run_id=?",
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def get_active_run(self) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in _RUN_STATES_ACTIVE)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_runs WHERE site_id=? AND state IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT 1",
                (self.site_id, *sorted(_RUN_STATES_ACTIVE)),
            ).fetchone()
        return _decode_row(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? ORDER BY run_date DESC, updated_at DESC LIMIT 1",
                (self.site_id,),
            ).fetchone()
        return _decode_row(row) if row else None

    def update_run(self, run_id: str, **values: Any) -> None:
        allowed = {
            "state",
            "paused",
            "requested_action",
            "scheduled_start_at",
            "scheduled_end_at",
            "actual_started_at",
            "actual_ended_at",
            "ac_last_updated_at",
            "ac_freshness_status",
            "ping_sample_count",
            "summary_json",
            "error_code",
            "error_message",
        }
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            return
        payload["updated_at"] = _now()
        params = [
            json.dumps(value, ensure_ascii=False)
            if key == "summary_json" and not isinstance(value, str)
            else int(value)
            if isinstance(value, bool)
            else value
            for key, value in payload.items()
        ]
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE ground_unattended_runs SET {', '.join(f'{key}=?' for key in payload)} "
                "WHERE site_id=? AND run_id=?",
                (*params, self.site_id, run_id),
            )

    def upsert_train_state(
        self,
        run_id: str,
        run_date: str,
        values: dict[str, Any],
        *,
        ap_identity: str,
        same_ap_since: str,
    ) -> None:
        now = _now()
        priority = values.get("priority", False)
        endpoints = values.get("endpoints", [])
        row = {
            "site_id": self.site_id,
            "run_id": run_id,
            "run_date": run_date,
            "train_id": values["train_id"],
            "train_no": values.get("train_no", ""),
            "train_name": values.get("train_name", ""),
            "coverage_status": values.get("coverage_status", "NOT_SEEN"),
            "priority": int(bool(priority)),
            "ping_eligible": int(bool(values.get("ping_eligible"))),
            "deep_collection_eligible": int(
                bool(values.get("deep_collection_eligible"))
            ),
            "eligibility_status": values.get("eligibility_status", "AC_UNKNOWN"),
            "exclusion_reason": values.get("exclusion_reason", ""),
            "current_ap_identity": ap_identity,
            "current_ap_name": values.get("current_ap_name", ""),
            "current_ap_mac": values.get("current_ap_mac", ""),
            "station": values.get("station", ""),
            "section": values.get("section", ""),
            "mileage": values.get("mileage", ""),
            "rssi": values.get("rssi"),
            "same_ap_since": same_ap_since,
            "same_ap_duration_seconds": values.get("same_ap_duration_seconds", 0),
            "ac_snapshot_id": values.get("ac_snapshot_id"),
            "ac_received_at": values.get("ac_received_at", ""),
            "endpoints_json": json.dumps(endpoints, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "run_id", "train_id", "run_date", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_train_runs ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(site_id, run_id, train_id) DO UPDATE SET {updates}",
                tuple(row.values()),
            )

    def list_train_runs(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_train_runs WHERE site_id=? AND run_id=? "
                "ORDER BY priority DESC, train_no, train_id",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_train_run(self, run_id: str, train_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_train_runs WHERE site_id=? AND run_id=? AND train_id=?",
                (self.site_id, run_id, train_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def update_train_run(self, run_id: str, train_id: str, **values: Any) -> None:
        allowed = {
            "coverage_status",
            "priority",
            "attempt_count",
            "covered_rounds",
            "selection_reason",
            "failure_reason",
            "collection_started_at",
            "valid_duration_minutes",
            "operations_json",
            "sessions_json",
        }
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            return
        payload["updated_at"] = _now()
        params = []
        for key, value in payload.items():
            if key in {"operations_json", "sessions_json"} and not isinstance(
                value, str
            ):
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                value = int(value)
            params.append(value)
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE ground_unattended_train_runs SET {', '.join(f'{key}=?' for key in payload)} "
                "WHERE site_id=? AND run_id=? AND train_id=?",
                (*params, self.site_id, run_id, train_id),
            )

    def save_daily_queue(
        self,
        *,
        run_id: str,
        run_date: str,
        random_seed: int,
        candidate_train_ids: list[str],
        queue_order: list[str],
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_unattended_daily_queues(
                    site_id, run_id, run_date, random_seed, generated_at,
                    candidate_train_ids_json, queue_order_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, run_id) DO UPDATE SET
                    generated_at=excluded.generated_at,
                    candidate_train_ids_json=excluded.candidate_train_ids_json,
                    queue_order_json=excluded.queue_order_json
                """,
                (
                    self.site_id,
                    run_id,
                    run_date,
                    int(random_seed),
                    _now(),
                    json.dumps(candidate_train_ids, ensure_ascii=False),
                    json.dumps(queue_order, ensure_ascii=False),
                ),
            )

    def get_daily_queue(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_daily_queues WHERE site_id=? AND run_id=?",
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def insert_ac_rows(
        self, rows: Iterable[dict[str, Any]]
    ) -> dict[tuple[str, str], int]:
        ids: dict[tuple[str, str], int] = {}
        with self._transaction() as conn:
            for row in rows:
                fields = tuple(row)
                cursor = conn.execute(
                    f"INSERT INTO ground_unattended_ac_snapshots ({', '.join(fields)}) "
                    f"VALUES ({', '.join('?' for _ in fields)})",
                    tuple(row.values()),
                )
                ids[(str(row.get("train_id") or ""), str(row.get("mr_id") or ""))] = (
                    int(cursor.lastrowid)
                )
        return ids

    def latest_ac_snapshot(
        self, run_id: str, train_id: str = "", mr_id: str = ""
    ) -> dict[str, Any] | None:
        where = ["site_id=?", "run_id=?"]
        params: list[Any] = [self.site_id, run_id]
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if mr_id:
            where.append("mr_id=?")
            params.append(mr_id)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_ac_snapshots WHERE {' AND '.join(where)} "
                "ORDER BY received_at DESC, id DESC LIMIT 1",
                params,
            ).fetchone()
        return _decode_row(row) if row else None

    def upsert_ping_segment(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"segment_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_ping_segments ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(segment_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_open_ping_segments(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_ping_segments WHERE site_id=? AND run_id=? AND status='OPEN'",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def upsert_ping_summary(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field
            not in {
                "id",
                "site_id",
                "run_id",
                "bucket_kind",
                "bucket_start",
                "target_ip",
                "ap_identity",
            }
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_ping_summaries ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                "ON CONFLICT(site_id, run_id, bucket_kind, bucket_start, target_ip, ap_identity) "
                f"DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_ping_summaries(
        self, run_id: str, *, bucket_kind: str | None = "daily"
    ) -> list[dict[str, Any]]:
        where = "WHERE site_id=? AND run_id=?"
        params: list[Any] = [self.site_id, run_id]
        if bucket_kind:
            where += " AND bucket_kind=?"
            params.append(bucket_kind)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_ping_summaries "
                f"{where} ORDER BY bucket_start, train_no, mr_position_code",
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def save_deep_operation(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"operation_id", "started_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_deep_operations ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(operation_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_deep_operations(
        self, run_id: str, *, active_only: bool = False
    ) -> list[dict[str, Any]]:
        clause = (
            " AND state NOT IN ('COMPLETED','PARTIAL','FAILED')" if active_only else ""
        )
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_deep_operations WHERE site_id=? AND run_id=?"
                + clause
                + " ORDER BY started_at",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def add_event(
        self,
        *,
        run_id: str = "",
        event_type: str,
        title: str,
        message: str = "",
        severity: str = "info",
        train_id: str = "",
        mr_id: str = "",
        details: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ground_unattended_events(
                    site_id, run_id, ts, event_type, severity, train_id, mr_id,
                    title, message, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.site_id,
                    run_id,
                    ts or _now(),
                    event_type,
                    severity,
                    train_id,
                    mr_id,
                    title,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def list_events(
        self,
        run_id: str,
        *,
        train_id: str = "",
        event_type: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where = ["site_id=?", "run_id=?"]
        params: list[Any] = [self.site_id, run_id]
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if event_type:
            where.append("event_type=?")
            params.append(event_type)
        params.append(max(1, min(int(limit), 5000)))
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_events WHERE {' AND '.join(where)} "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def upsert_archive(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"archive_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_archives ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(archive_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_archives(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? ORDER BY a.run_date DESC
                """,
                (self.site_id,),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_archive(self, archive_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? AND a.archive_id=?
                """,
                (self.site_id, archive_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def get_archive_by_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? AND a.run_id=?
                """,
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def delete_archive_record(self, archive_id: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM ground_unattended_archives WHERE site_id=? AND archive_id=?",
                (self.site_id, archive_id),
            )

    def purge_run_details(self, run_id: str) -> None:
        with self._transaction() as conn:
            for table in (
                "ground_unattended_ac_snapshots",
                "ground_unattended_ping_segments",
                "ground_unattended_deep_operations",
                "ground_unattended_events",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
            conn.execute(
                "DELETE FROM ground_unattended_ping_summaries "
                "WHERE site_id=? AND run_id=? AND bucket_kind!='daily'",
                (self.site_id, run_id),
            )

    def delete_summaries_before(self, cutoff: str) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                DELETE FROM ground_unattended_ping_summaries
                WHERE site_id=? AND run_id IN (
                    SELECT run_id FROM ground_unattended_runs WHERE site_id=? AND run_date < ?
                )
                """,
                (self.site_id, self.site_id, cutoff),
            )
            old_runs = [
                str(row[0])
                for row in conn.execute(
                    "SELECT run_id FROM ground_unattended_runs WHERE site_id=? AND run_date < ?",
                    (self.site_id, cutoff),
                ).fetchall()
            ]
            for run_id in old_runs:
                conn.execute(
                    "DELETE FROM ground_unattended_train_runs WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
                conn.execute(
                    "DELETE FROM ground_unattended_daily_queues WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
                conn.execute(
                    "DELETE FROM ground_unattended_runs WHERE site_id=? AND run_id=? "
                    "AND NOT EXISTS(SELECT 1 FROM ground_unattended_archives WHERE site_id=? AND run_id=?)",
                    (self.site_id, run_id, self.site_id, run_id),
                )
            return int(cursor.rowcount)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _decode_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json"):
            value = result.pop(key)
            try:
                result[key.removesuffix("_json")] = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = (
                    {} if str(value).startswith("{") else []
                )
    for key in (
        "enabled",
        "paused",
        "priority",
        "ping_eligible",
        "deep_collection_eligible",
        "finalization_complete",
        "package_verified",
        "active_cleanup_pending",
    ):
        if key in result:
            result[key] = bool(result[key])
    return result


__all__ = ["GroundUnattendedRepository"]
