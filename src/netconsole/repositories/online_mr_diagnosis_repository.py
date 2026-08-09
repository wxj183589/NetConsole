from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.services.online_mr.parsed_database_contract import (
    PARSER_CAPABILITIES,
    PARSER_SCHEMA_VERSION,
    PARSER_VERSION,
)


OnlineMrDatabaseError = sqlite3.Error
ONLINE_MR_DIAGNOSIS_SCHEMA_VERSION = str(PARSER_SCHEMA_VERSION)

SCHEMA = """
CREATE TABLE IF NOT EXISTS main_link_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    collector_time TEXT,
    device_time TEXT,
    device_clock TEXT,
    time_source TEXT,
    radio INTEGER,
    link_state TEXT,
    peer_name TEXT,
    peer_mac TEXT,
    peer_mac_normalized TEXT,
    resolved_peer_name TEXT,
    peer_ap_mac TEXT,
    canonical_ap_mac TEXT,
    peer_radio_mac TEXT,
    identity_entity_id TEXT,
    identity_revision INTEGER DEFAULT 0,
    identity_index_status TEXT,
    identity_status TEXT,
    identity_source TEXT,
    identity_reason TEXT,
    matched_alias_type TEXT,
    matched_radio_id INTEGER,
    identity_match_rule TEXT,
    identity_match_confidence INTEGER,
    mr_rssi INTEGER,
    bssid TEXT,
    mesh_interface TEXT,
    belong_station TEXT,
    belong_section TEXT,
    belong_type TEXT,
    belonging_source TEXT,
    online_time TEXT
);
CREATE TABLE IF NOT EXISTS channel_busy_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    device_time TEXT,
    device_clock TEXT,
    time_source TEXT,
    radio INTEGER,
    ctl_channel INTEGER,
    bandwidth REAL,
    channel_band_raw TEXT,
    bandwidth_mhz REAL,
    record_interval INTEGER,
    row_index INTEGER,
    ctl_busy INTEGER,
    tx_busy INTEGER,
    rx_busy INTEGER
);
CREATE TABLE IF NOT EXISTS radio_statistics_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    collector_time TEXT,
    device_clock TEXT,
    time_source TEXT,
    radio INTEGER,
    metric_name TEXT,
    metric_value REAL,
    metric_unit TEXT
);
CREATE TABLE IF NOT EXISTS interface_rate_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    device_time TEXT,
    device_clock TEXT,
    time_source TEXT,
    interface_name TEXT,
    interface_normalized TEXT,
    direction TEXT,
    total_pps REAL,
    broadcast_pps REAL,
    multicast_pps REAL,
    usage_percent REAL
);
CREATE TABLE IF NOT EXISTS time_sync_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    collector_time TEXT NOT NULL,
    device_time TEXT NOT NULL,
    offset_ms REAL NOT NULL,
    source TEXT
);
CREATE TABLE IF NOT EXISTS fping_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    collector_time TEXT,
    local_time TEXT,
    device_aligned_time TEXT,
    clock_offset_ms REAL,
    offset_source TEXT,
    time_source TEXT,
    target_ip TEXT,
    target_name TEXT,
    seq INTEGER,
    success INTEGER,
    latency_ms REAL,
    loss_percent REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS fping_1s_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    bucket_time TEXT,
    local_bucket_time TEXT,
    device_bucket_time TEXT,
    clock_offset_ms REAL,
    target_ip TEXT,
    target_name TEXT,
    sent INTEGER,
    received INTEGER,
    lost INTEGER,
    loss_percent REAL,
    avg_latency_ms REAL,
    min_latency_ms REAL,
    max_latency_ms REAL,
    jitter_ms REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS iperf_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    device_id INTEGER,
    mode TEXT NOT NULL,
    protocol TEXT,
    server_ip TEXT,
    port INTEGER,
    direction TEXT,
    parallel INTEGER,
    target_bandwidth TEXT,
    started_at TEXT,
    ended_at TEXT,
    status TEXT,
    command_json TEXT
);
CREATE TABLE IF NOT EXISTS iperf_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    session_id TEXT,
    collector_time TEXT,
    interval_start_sec REAL,
    interval_end_sec REAL,
    interval_center_time TEXT,
    device_aligned_time TEXT,
    device_interval_center_time TEXT,
    clock_offset_ms REAL,
    offset_source TEXT,
    time_source TEXT,
    transfer_bytes REAL,
    bitrate_mbps REAL,
    retransmits INTEGER,
    cwnd TEXT,
    role TEXT,
    jitter_ms REAL,
    lost_packets INTEGER,
    total_packets INTEGER,
    loss_percent REAL,
    source_event_key TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS online_parse_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    raw_file TEXT,
    line_number INTEGER,
    issue_type TEXT,
    severity TEXT,
    message TEXT,
    raw_text TEXT
);
CREATE TABLE IF NOT EXISTS analysis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    collector_time TEXT,
    event_type TEXT,
    severity TEXT,
    summary_text TEXT,
    details_json TEXT DEFAULT '{}',
    raw_file TEXT,
    raw_line_start INTEGER,
    raw_line_end INTEGER
);
CREATE TABLE IF NOT EXISTS online_parse_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    parsed_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    raw_fingerprint TEXT NOT NULL,
    row_counts TEXT DEFAULT '{}',
    status TEXT NOT NULL,
    error_summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS online_identity_metadata (
    session_id TEXT PRIMARY KEY,
    identity_index_revision INTEGER DEFAULT 0,
    identity_index_status TEXT,
    identity_mapped_at TEXT,
    identity_mapping_status TEXT,
    identity_requested_count INTEGER DEFAULT 0,
    identity_distinct_count INTEGER DEFAULT 0,
    identity_matched_count INTEGER DEFAULT 0,
    identity_unresolved_count INTEGER DEFAULT 0,
    identity_ambiguous_count INTEGER DEFAULT 0,
    identity_invalid_count INTEGER DEFAULT 0,
    identity_updated_rows INTEGER DEFAULT 0,
    fact_fingerprint TEXT
);
CREATE TABLE IF NOT EXISTS switch_history_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    snapshot_collector_time TEXT,
    snapshot_device_clock TEXT,
    event_time_device TEXT,
    event_time_local TEXT,
    time_source TEXT,
    radio INTEGER,
    old_peer_name TEXT,
    old_peer_mac TEXT,
    old_rssi INTEGER,
    old_belong_station TEXT,
    old_belong_section TEXT,
    old_identity_entity_id TEXT,
    old_identity_revision INTEGER DEFAULT 0,
    old_identity_status TEXT,
    old_identity_source TEXT,
    old_identity_reason TEXT,
    old_matched_alias_type TEXT,
    old_matched_ap_name TEXT,
    old_matched_ap_mac TEXT,
    old_matched_radio_id INTEGER,
    old_identity_match_rule TEXT,
    old_identity_match_confidence INTEGER,
    new_peer_name TEXT,
    new_peer_mac TEXT,
    new_rssi INTEGER,
    new_belong_station TEXT,
    new_belong_section TEXT,
    new_identity_entity_id TEXT,
    new_identity_revision INTEGER DEFAULT 0,
    new_identity_status TEXT,
    new_identity_source TEXT,
    new_identity_reason TEXT,
    new_matched_alias_type TEXT,
    new_matched_ap_name TEXT,
    new_matched_ap_mac TEXT,
    new_matched_radio_id INTEGER,
    new_identity_match_rule TEXT,
    new_identity_match_confidence INTEGER,
    peer_quantity INTEGER,
    link_quantity INTEGER,
    switch_reason_code INTEGER,
    switch_reason_text TEXT,
    active_duration TEXT,
    UNIQUE(session_id, event_time_device, old_peer_mac, new_peer_mac, switch_reason_code)
);
CREATE TABLE IF NOT EXISTS switch_realtime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    device_time TEXT,
    time_source TEXT,
    device_name TEXT,
    old_peer_name TEXT,
    old_peer_mac TEXT,
    old_rssi INTEGER,
    old_belong_station TEXT,
    old_belong_section TEXT,
    old_identity_entity_id TEXT,
    old_identity_revision INTEGER DEFAULT 0,
    old_identity_status TEXT,
    old_identity_source TEXT,
    old_identity_reason TEXT,
    old_matched_alias_type TEXT,
    old_matched_ap_name TEXT,
    old_matched_ap_mac TEXT,
    old_matched_radio_id INTEGER,
    old_identity_match_rule TEXT,
    old_identity_match_confidence INTEGER,
    new_peer_name TEXT,
    new_peer_mac TEXT,
    new_rssi INTEGER,
    new_belong_station TEXT,
    new_belong_section TEXT,
    new_identity_entity_id TEXT,
    new_identity_revision INTEGER DEFAULT 0,
    new_identity_status TEXT,
    new_identity_source TEXT,
    new_identity_reason TEXT,
    new_matched_alias_type TEXT,
    new_matched_ap_name TEXT,
    new_matched_ap_mac TEXT,
    new_matched_radio_id INTEGER,
    new_identity_match_rule TEXT,
    new_identity_match_confidence INTEGER,
    peer_quantity INTEGER,
    link_quantity INTEGER,
    switch_reason_code INTEGER,
    switch_reason_text TEXT
);
CREATE TABLE IF NOT EXISTS active_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    radio INTEGER,
    active_peer_mac TEXT,
    start_time TEXT,
    end_time TEXT,
    sample_count INTEGER,
    avg_mr_rssi REAL,
    min_mr_rssi INTEGER,
    max_mr_rssi INTEGER,
    event_type TEXT,
    details_json TEXT
);
CREATE TABLE IF NOT EXISTS active_segment_metrics (
    segment_id INTEGER PRIMARY KEY,
    ping_sent INTEGER,
    ping_success INTEGER,
    ping_lost INTEGER,
    ping_loss_percent REAL,
    avg_latency_ms REAL,
    max_latency_ms REAL,
    iperf_sample_count INTEGER,
    avg_mbps REAL,
    min_mbps REAL,
    max_mbps REAL,
    p95_mbps REAL,
    total_retransmits INTEGER,
    avg_tx_busy REAL,
    max_tx_busy REAL,
    avg_rx_busy REAL,
    max_rx_busy REAL
);
CREATE INDEX IF NOT EXISTS idx_main_link_samples_time ON main_link_samples(collector_time);
CREATE INDEX IF NOT EXISTS idx_main_link_samples_active ON main_link_samples(link_state, collector_time);
CREATE INDEX IF NOT EXISTS idx_channel_busy_records_time ON channel_busy_records(device_time);
CREATE INDEX IF NOT EXISTS idx_interface_rate_samples_time ON interface_rate_samples(device_time);
CREATE INDEX IF NOT EXISTS idx_time_sync_samples_collector_time ON time_sync_samples(collector_time);
CREATE INDEX IF NOT EXISTS idx_fping_samples_time ON fping_samples(collector_time);
CREATE INDEX IF NOT EXISTS idx_fping_samples_device_time ON fping_samples(device_aligned_time);
CREATE INDEX IF NOT EXISTS idx_fping_1s_summary_time ON fping_1s_summary(bucket_time);
CREATE INDEX IF NOT EXISTS idx_fping_1s_summary_device_time ON fping_1s_summary(device_bucket_time);
CREATE INDEX IF NOT EXISTS idx_analysis_events_time ON analysis_events(collector_time);
CREATE INDEX IF NOT EXISTS idx_switch_history_events_time ON switch_history_events(event_time_local);
CREATE INDEX IF NOT EXISTS idx_switch_realtime_events_time ON switch_realtime_events(device_time);
CREATE TABLE IF NOT EXISTS online_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

IPERF_SCHEMA = """
CREATE TABLE IF NOT EXISTS iperf_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    device_id INTEGER,
    mode TEXT NOT NULL,
    protocol TEXT,
    server_ip TEXT,
    port INTEGER,
    direction TEXT,
    parallel INTEGER,
    target_bandwidth TEXT,
    started_at TEXT,
    ended_at TEXT,
    status TEXT,
    command_json TEXT
);
CREATE TABLE IF NOT EXISTS iperf_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    session_id TEXT,
    collector_time TEXT,
    interval_start_sec REAL,
    interval_end_sec REAL,
    interval_center_time TEXT,
    device_aligned_time TEXT,
    device_interval_center_time TEXT,
    clock_offset_ms REAL,
    offset_source TEXT,
    time_source TEXT,
    transfer_bytes REAL,
    bitrate_mbps REAL,
    retransmits INTEGER,
    cwnd TEXT,
    role TEXT,
    jitter_ms REAL,
    lost_packets INTEGER,
    total_packets INTEGER,
    loss_percent REAL,
    source_event_key TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_iperf_intervals_time ON iperf_intervals(interval_center_time);
CREATE INDEX IF NOT EXISTS idx_iperf_intervals_run ON iperf_intervals(run_id);
"""

RESET_TABLES = (
    "main_link_samples",
    "channel_busy_records",
    "radio_statistics_samples",
    "interface_rate_samples",
    "switch_history_events",
    "switch_realtime_events",
    "time_sync_samples",
    "fping_samples",
    "fping_1s_summary",
    "iperf_runs",
    "iperf_intervals",
    "analysis_events",
    "active_segments",
    "active_segment_metrics",
    "online_parse_issues",
    "online_parse_metadata",
    "online_identity_metadata",
)

REQUIRED_CACHE_TABLES = frozenset(
    {
        "main_link_samples",
        "channel_busy_records",
        "radio_statistics_samples",
        "switch_history_events",
        "switch_realtime_events",
        "interface_rate_samples",
        "time_sync_samples",
        "fping_samples",
        "fping_1s_summary",
        "active_segments",
    }
)

INSERT_SQL = {
    "time_sync_samples": """
        INSERT INTO time_sync_samples (
            session_id, collector_time, device_time, offset_ms, source
        ) VALUES (?, ?, ?, ?, ?)
    """,
    "main_link_samples": """
        INSERT INTO main_link_samples (
            session_id, collector_time, device_time, device_clock, time_source, radio, link_state,
            peer_name, peer_mac, peer_mac_normalized, resolved_peer_name, mr_rssi,
            peer_ap_mac, canonical_ap_mac, peer_radio_mac, identity_status, identity_source,
            identity_reason, identity_match_rule, identity_match_confidence, bssid, mesh_interface,
            belong_station, belong_section, belong_type, belonging_source, online_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "channel_busy_records": """
        INSERT INTO channel_busy_records (
            session_id, device_time, device_clock, time_source, radio, ctl_channel, bandwidth,
            channel_band_raw, bandwidth_mhz, record_interval, row_index, ctl_busy, tx_busy, rx_busy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "radio_statistics_samples": """
        INSERT INTO radio_statistics_samples (
            session_id, collector_time, device_clock, time_source, radio,
            metric_name, metric_value, metric_unit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "interface_rate_samples": """
        INSERT INTO interface_rate_samples (
            session_id, device_time, device_clock, time_source, interface_name, interface_normalized,
            direction, total_pps, broadcast_pps, multicast_pps, usage_percent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "switch_history_events": """
        INSERT OR IGNORE INTO switch_history_events (
            session_id, snapshot_collector_time, snapshot_device_clock, event_time_device,
            event_time_local, time_source, radio, old_peer_name, old_peer_mac, old_rssi,
            old_belong_station, old_belong_section, new_peer_name, new_peer_mac, new_rssi,
            new_belong_station, new_belong_section, peer_quantity, link_quantity,
            switch_reason_code, switch_reason_text, active_duration
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "analysis_events": """
        INSERT INTO analysis_events (
            session_id, collector_time, event_type, severity, summary_text,
            details_json, raw_file, raw_line_start, raw_line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
}


def _switch_identity_column_definitions() -> dict[str, str]:
    definitions: dict[str, str] = {}
    for prefix in ("old", "new"):
        definitions.update(
            {
                f"{prefix}_identity_entity_id": "TEXT",
                f"{prefix}_identity_revision": "INTEGER DEFAULT 0",
                f"{prefix}_identity_status": "TEXT",
                f"{prefix}_identity_source": "TEXT",
                f"{prefix}_identity_reason": "TEXT",
                f"{prefix}_matched_alias_type": "TEXT",
                f"{prefix}_matched_ap_name": "TEXT",
                f"{prefix}_matched_ap_mac": "TEXT",
                f"{prefix}_matched_radio_id": "INTEGER",
                f"{prefix}_identity_match_rule": "TEXT",
                f"{prefix}_identity_match_confidence": "INTEGER",
            }
        )
    return definitions


def _switch_identity_update_sql(table: str) -> str:
    if table not in {"switch_history_events", "switch_realtime_events"}:
        raise ValueError(f"不支持的 Online MR 切换表：{table}")
    assignments: list[str] = []
    for prefix in ("old", "new"):
        assignments.extend(
            (
                f"{prefix}_belong_station = ?",
                f"{prefix}_belong_section = ?",
                f"{prefix}_identity_entity_id = ?",
                f"{prefix}_identity_revision = ?",
                f"{prefix}_identity_status = ?",
                f"{prefix}_identity_source = ?",
                f"{prefix}_identity_reason = ?",
                f"{prefix}_matched_alias_type = ?",
                f"{prefix}_matched_ap_name = ?",
                f"{prefix}_matched_ap_mac = ?",
                f"{prefix}_matched_radio_id = ?",
                f"{prefix}_identity_match_rule = ?",
                f"{prefix}_identity_match_confidence = ?",
            )
        )
    return f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ? AND session_id = ?"


class OnlineMrDiagnosisRepository:
    """Online MR 会话分析库的 schema、事务和查询边界。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self, *, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=timeout)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.executescript(IPERF_SCHEMA)
            self._ensure_identity_columns(conn)
            conn.executemany(
                "INSERT OR REPLACE INTO online_schema_meta (key, value) VALUES (?, ?)",
                (
                    ("schema_version", ONLINE_MR_DIAGNOSIS_SCHEMA_VERSION),
                    ("parser_version", PARSER_VERSION),
                    ("capabilities", json.dumps(PARSER_CAPABILITIES, ensure_ascii=False)),
                ),
            )
            conn.execute(f"PRAGMA user_version={PARSER_SCHEMA_VERSION}")

    def discard_existing_database(self) -> None:
        for _ in range(3):
            try:
                self.db_path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.2)
        self.drop_all_tables()

    def drop_all_tables(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            tables = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                escaped = table.replace('"', '""')
                conn.execute(f'DROP TABLE IF EXISTS "{escaped}"')
            conn.commit()
            conn.execute("VACUUM")

    def reset_parsed_tables(self) -> None:
        with self._connect() as conn:
            existing_tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            for table in RESET_TABLES:
                if table in existing_tables:
                    conn.execute(f"DELETE FROM {table}")

    def cached_parse_metadata(
        self,
        session_id: str,
        parser_version: str,
        raw_fingerprint: str,
    ) -> tuple[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT row_counts, status
                FROM online_parse_metadata
                WHERE session_id = ? AND parser_version = ? AND raw_fingerprint = ?
                ORDER BY parsed_at DESC
                LIMIT 1
                """,
                (session_id, parser_version, raw_fingerprint),
            ).fetchone()
        if row is None:
            return None
        return str(row[0] or ""), str(row[1] or "")

    def parsed_health_snapshot(self, session_id: str) -> dict[str, object]:
        with self._connect() as conn:
            existing = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if not REQUIRED_CACHE_TABLES.issubset(existing):
                return {"required_tables_present": False}
            mesh_sample_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM main_link_samples WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            mesh_link_count = int(conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0])
            active_link_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM main_link_samples WHERE UPPER(link_state) LIKE 'ACTIVE%'"
                ).fetchone()[0]
            )
            distinct_time_count = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT collector_time) FROM main_link_samples WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            bad_segment = conn.execute(
                """
                SELECT active_peer_mac
                FROM active_segments
                WHERE active_peer_mac LIKE '%,%,%,%,%'
                LIMIT 1
                """
            ).fetchone()
        return {
            "required_tables_present": True,
            "mesh_sample_count": mesh_sample_count,
            "mesh_link_count": mesh_link_count,
            "active_link_count": active_link_count,
            "distinct_time_count": distinct_time_count,
            "has_bad_segment": bad_segment is not None,
        }

    def main_link_metadata(self, session_id: str) -> dict[str, object]:
        with self._connect() as conn:
            main_link = conn.execute(
                """
                SELECT COUNT(*), MIN(collector_time), MAX(collector_time)
                FROM main_link_samples
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            active_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM main_link_samples
                WHERE session_id = ? AND UPPER(link_state) LIKE 'ACTIVE%'
                """,
                (session_id,),
            ).fetchone()
        return {
            "main_link_sample_count": int(main_link[0] or 0),
            "active_link_count": int(active_count[0] or 0),
            "analysis_start": main_link[1] or "",
            "analysis_end": main_link[2] or "",
        }

    def replace_parse_metadata(self, values: tuple[object, ...]) -> None:
        session_id = str(values[0])
        with self._connect() as conn:
            conn.execute("DELETE FROM online_parse_metadata WHERE session_id = ?", (session_id,))
            conn.execute(
                """
                INSERT INTO online_parse_metadata (
                    session_id, parsed_at, parser_version, raw_fingerprint, row_counts, status, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def insert_rows(self, dataset: str, rows: Iterable[Sequence[object]]) -> None:
        try:
            statement = INSERT_SQL[dataset]
        except KeyError as exc:
            raise ValueError(f"不支持的 Online MR 分析数据集：{dataset}") from exc
        values = list(rows)
        if not values:
            return
        with self._connect() as conn:
            conn.executemany(statement, values)

    def load_identity_observations(self, session_id: str) -> dict[str, list[dict[str, object]]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            main_rows = conn.execute(
                """
                SELECT id, peer_name, peer_mac, peer_mac_normalized, bssid
                FROM main_link_samples
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
            switch_history_rows = conn.execute(
                """
                SELECT id, old_peer_name, old_peer_mac, new_peer_name, new_peer_mac
                FROM switch_history_events
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
            switch_realtime_rows = conn.execute(
                """
                SELECT id, old_peer_name, old_peer_mac, new_peer_name, new_peer_mac
                FROM switch_realtime_events
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        return {
            "main_link_samples": [dict(row) for row in main_rows],
            "switch_history_events": [dict(row) for row in switch_history_rows],
            "switch_realtime_events": [dict(row) for row in switch_realtime_rows],
        }

    def identity_fact_fingerprint(self, session_id: str) -> str:
        with self._connect() as conn:
            return self._identity_fact_fingerprint(conn, session_id)

    def apply_identity_projection(
        self,
        session_id: str,
        updates: Mapping[str, Sequence[Sequence[object]]],
        metadata: Mapping[str, object],
        *,
        expected_fact_fingerprint: str,
        matched_updated_rows: int,
    ) -> dict[str, object]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._identity_fact_fingerprint(conn, session_id)
            if before != expected_fact_fingerprint:
                raise RuntimeError("Online MR 原始事实已在身份映射前发生变化")

            statements = {
                "main_link_samples": """
                    UPDATE main_link_samples SET
                        resolved_peer_name = ?, peer_ap_mac = ?, canonical_ap_mac = ?,
                        peer_radio_mac = ?, identity_entity_id = ?, identity_revision = ?,
                        identity_index_status = ?, identity_status = ?, identity_source = ?,
                        identity_reason = ?, matched_alias_type = ?, matched_radio_id = ?,
                        identity_match_rule = ?, identity_match_confidence = ?,
                        belong_station = ?, belong_section = ?, belong_type = ?,
                        belonging_source = ?
                    WHERE id = ? AND session_id = ?
                """,
                "switch_history_events": _switch_identity_update_sql(
                    "switch_history_events"
                ),
                "switch_realtime_events": _switch_identity_update_sql(
                    "switch_realtime_events"
                ),
            }
            updated_rows = 0
            for dataset, statement in statements.items():
                values = list(updates.get(dataset, ()))
                if not values:
                    continue
                cursor = conn.executemany(statement, values)
                updated_rows += max(int(cursor.rowcount or 0), 0)

            if int(metadata.get("identity_matched_count") or 0) > 0 and matched_updated_rows <= 0:
                raise RuntimeError("Online MR 身份映射存在 matched 结果但没有写回任何事实行")

            after = self._identity_fact_fingerprint(conn, session_id)
            if after != before:
                raise RuntimeError("Online MR identity-only remap 改变了原始事实")

            mapped_at = str(metadata.get("identity_mapped_at") or "")
            conn.execute(
                """
                INSERT INTO online_identity_metadata (
                    session_id, identity_index_revision, identity_index_status,
                    identity_mapped_at, identity_mapping_status,
                    identity_requested_count, identity_distinct_count,
                    identity_matched_count, identity_unresolved_count,
                    identity_ambiguous_count, identity_invalid_count,
                    identity_updated_rows, fact_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    identity_index_revision = excluded.identity_index_revision,
                    identity_index_status = excluded.identity_index_status,
                    identity_mapped_at = excluded.identity_mapped_at,
                    identity_mapping_status = excluded.identity_mapping_status,
                    identity_requested_count = excluded.identity_requested_count,
                    identity_distinct_count = excluded.identity_distinct_count,
                    identity_matched_count = excluded.identity_matched_count,
                    identity_unresolved_count = excluded.identity_unresolved_count,
                    identity_ambiguous_count = excluded.identity_ambiguous_count,
                    identity_invalid_count = excluded.identity_invalid_count,
                    identity_updated_rows = excluded.identity_updated_rows,
                    fact_fingerprint = excluded.fact_fingerprint
                """,
                (
                    session_id,
                    int(metadata.get("identity_index_revision") or 0),
                    str(metadata.get("identity_index_status") or ""),
                    mapped_at,
                    str(metadata.get("identity_mapping_status") or ""),
                    int(metadata.get("identity_requested_count") or 0),
                    int(metadata.get("identity_distinct_count") or 0),
                    int(metadata.get("identity_matched_count") or 0),
                    int(metadata.get("identity_unresolved_count") or 0),
                    int(metadata.get("identity_ambiguous_count") or 0),
                    int(metadata.get("identity_invalid_count") or 0),
                    updated_rows,
                    after,
                ),
            )
            conn.commit()
        return {
            "updated_rows": updated_rows,
            "fact_fingerprint_before": before,
            "fact_fingerprint_after": after,
        }

    def replace_identity_failure_metadata(
        self,
        session_id: str,
        *,
        status: str,
        mapped_at: str,
        fact_fingerprint: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO online_identity_metadata (
                    session_id, identity_mapped_at, identity_mapping_status,
                    fact_fingerprint
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    identity_mapped_at = excluded.identity_mapped_at,
                    identity_mapping_status = excluded.identity_mapping_status,
                    fact_fingerprint = excluded.fact_fingerprint
                """,
                (session_id, mapped_at, status, fact_fingerprint),
            )

    def identity_metadata(self, session_id: str) -> dict[str, object]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM online_identity_metadata WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row is not None else {}

    @staticmethod
    def _identity_fact_fingerprint(
        conn: sqlite3.Connection,
        session_id: str,
    ) -> str:
        digest = hashlib.sha256()
        queries = (
            (
                "main_link_samples",
                """
                SELECT id, session_id, collector_time, device_time, device_clock,
                       time_source, radio, link_state, peer_name, peer_mac,
                       peer_mac_normalized, mr_rssi, bssid, mesh_interface, online_time
                FROM main_link_samples WHERE session_id = ? ORDER BY id
                """,
            ),
            (
                "switch_history_events",
                """
                SELECT id, session_id, snapshot_collector_time, snapshot_device_clock,
                       event_time_device, event_time_local, time_source, radio,
                       old_peer_name, old_peer_mac, old_rssi, new_peer_name,
                       new_peer_mac, new_rssi, peer_quantity, link_quantity,
                       switch_reason_code, switch_reason_text, active_duration
                FROM switch_history_events WHERE session_id = ? ORDER BY id
                """,
            ),
            (
                "switch_realtime_events",
                """
                SELECT id, session_id, device_time, time_source, device_name,
                       old_peer_name, old_peer_mac, old_rssi, new_peer_name,
                       new_peer_mac, new_rssi, peer_quantity, link_quantity,
                       switch_reason_code, switch_reason_text
                FROM switch_realtime_events WHERE session_id = ? ORDER BY id
                """,
            ),
        )
        for dataset, statement in queries:
            digest.update(dataset.encode("utf-8"))
            for row in conn.execute(statement, (session_id,)).fetchall():
                digest.update(
                    json.dumps(
                        list(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _ensure_identity_columns(conn: sqlite3.Connection) -> None:
        additions = {
            "main_link_samples": {
                "peer_ap_mac": "TEXT",
                "canonical_ap_mac": "TEXT",
                "peer_radio_mac": "TEXT",
                "identity_entity_id": "TEXT",
                "identity_revision": "INTEGER DEFAULT 0",
                "identity_index_status": "TEXT",
                "identity_status": "TEXT",
                "identity_source": "TEXT",
                "identity_reason": "TEXT",
                "matched_alias_type": "TEXT",
                "matched_radio_id": "INTEGER",
                "identity_match_rule": "TEXT",
                "identity_match_confidence": "INTEGER",
            },
            "switch_history_events": _switch_identity_column_definitions(),
            "switch_realtime_events": _switch_identity_column_definitions(),
        }
        for table, definitions in additions.items():
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in definitions.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def replace_switch_realtime_events(
        self,
        session_id: str,
        rows: Iterable[Sequence[object]],
    ) -> None:
        values = list(rows)
        with self._connect() as conn:
            conn.execute("DELETE FROM switch_realtime_events WHERE session_id = ?", (session_id,))
            if not values:
                return
            conn.executemany(
                """
                INSERT INTO switch_realtime_events (
                    session_id, device_time, time_source, device_name,
                    old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section,
                    new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section,
                    peer_quantity, link_quantity, switch_reason_code, switch_reason_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def insert_fping_sampling_rows(
        self,
        sample_rows: Iterable[Sequence[object]],
        summary_rows: Iterable[Sequence[object]],
    ) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO fping_samples (
                    session_id, collector_time, local_time, device_aligned_time, clock_offset_ms,
                    offset_source, time_source, target_ip, target_name, seq,
                    success, latency_ms, loss_percent, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                list(sample_rows),
            )
            conn.executemany(
                """
                INSERT INTO fping_1s_summary (
                    session_id, bucket_time, local_bucket_time, device_bucket_time, clock_offset_ms,
                    target_ip, target_name, sent, received, lost, loss_percent,
                    avg_latency_ms, min_latency_ms, max_latency_ms, jitter_ms, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                list(summary_rows),
            )

    def load_time_sync_rows(self, session_id: str) -> list[tuple[object, ...]]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT collector_time, device_time, offset_ms, COALESCE(source, 'mesh_link_display_clock')
                    FROM time_sync_samples
                    WHERE session_id = ?
                    ORDER BY collector_time ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
            except sqlite3.Error:
                return []
        return [tuple(row) for row in rows]

    def append_issue(
        self,
        session_id: str,
        raw_file: str,
        issue_type: str,
        severity: str,
        message: str,
        raw_text: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO online_parse_issues (session_id, raw_file, line_number, issue_type, severity, message, raw_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, raw_file, 0, issue_type, severity, message, raw_text),
            )

    def issue_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM online_parse_issues").fetchone()[0])

    def normal_fallback_metrics(self) -> dict[str, object]:
        metrics: dict[str, object] = {
            "active_peer_mac": "",
            "avg_mr_rssi": None,
            "min_mr_rssi": None,
            "max_mr_rssi": None,
            "ping_sent": 0,
            "ping_success": 0,
            "ping_lost": 0,
            "ping_loss_percent": None,
            "avg_latency_ms": None,
            "max_latency_ms": None,
            "iperf_sample_count": 0,
            "avg_mbps": None,
            "min_mbps": None,
            "max_mbps": None,
            "p95_mbps": None,
            "total_retransmits": None,
            "avg_tx_busy": None,
            "max_tx_busy": None,
            "avg_rx_busy": None,
            "max_rx_busy": None,
            "interface_rate": {},
            "ap_radio_statistics": {},
        }
        with self._connect() as conn:
            mesh = conn.execute(
                """
                SELECT peer_mac_normalized, peer_mac, AVG(mr_rssi), MIN(mr_rssi), MAX(mr_rssi)
                FROM main_link_samples
                WHERE UPPER(link_state) = 'ACTIVE'
                GROUP BY peer_mac_normalized, peer_mac
                ORDER BY COUNT(*) DESC
                LIMIT 1
                """
            ).fetchone()
            if mesh:
                metrics["active_peer_mac"] = mesh[0] or mesh[1] or ""
                metrics["avg_mr_rssi"] = mesh[2]
                metrics["min_mr_rssi"] = mesh[3]
                metrics["max_mr_rssi"] = mesh[4]
            ping_summary = conn.execute(
                """
                SELECT SUM(sent), SUM(received), SUM(sent - received), AVG(loss_percent), AVG(avg_latency_ms), MAX(max_latency_ms)
                FROM fping_1s_summary
                LIMIT 1
                """
            ).fetchone()
            if ping_summary:
                metrics["ping_sent"] = int(ping_summary[0] or 0)
                metrics["ping_success"] = int(ping_summary[1] or 0)
                metrics["ping_lost"] = int(ping_summary[2] or 0)
                metrics["ping_loss_percent"] = ping_summary[3]
                metrics["avg_latency_ms"] = ping_summary[4]
                metrics["max_latency_ms"] = ping_summary[5]
            else:
                ping = conn.execute(
                    "SELECT COUNT(*), SUM(success), AVG(latency_ms), MAX(latency_ms) FROM fping_samples"
                ).fetchone()
                sent = int(ping[0] or 0)
                success = int(ping[1] or 0)
                lost = sent - success
                metrics["ping_sent"] = sent
                metrics["ping_success"] = success
                metrics["ping_lost"] = lost
                metrics["ping_loss_percent"] = (lost / sent * 100.0) if sent else None
                metrics["avg_latency_ms"] = ping[2]
                metrics["max_latency_ms"] = ping[3]
            busy = conn.execute(
                "SELECT AVG(tx_busy), MAX(tx_busy), AVG(rx_busy), MAX(rx_busy) FROM channel_busy_records"
            ).fetchone()
            if busy:
                metrics["avg_tx_busy"] = busy[0]
                metrics["max_tx_busy"] = busy[1]
                metrics["avg_rx_busy"] = busy[2]
                metrics["max_rx_busy"] = busy[3]
            iperf = conn.execute(
                "SELECT COUNT(*), AVG(bitrate_mbps), MIN(bitrate_mbps), MAX(bitrate_mbps), SUM(retransmits) FROM iperf_intervals"
            ).fetchone()
            if iperf:
                metrics["iperf_sample_count"] = int(iperf[0] or 0)
                metrics["avg_mbps"] = iperf[1]
                metrics["min_mbps"] = iperf[2]
                metrics["max_mbps"] = iperf[3]
                metrics["p95_mbps"] = iperf[3]
                metrics["total_retransmits"] = iperf[4]
            interface = conn.execute(
                """
                SELECT direction, AVG(total_pps), MAX(total_pps)
                FROM interface_rate_samples
                WHERE direction IS NOT NULL
                GROUP BY direction
                """
            ).fetchall()
            metrics["interface_rate"] = {
                str(row[0]): {"avg_pps": row[1], "max_pps": row[2]} for row in interface
            }
            radio_stats = conn.execute(
                """
                SELECT metric_name, metric_value
                FROM radio_statistics_samples
                ORDER BY collector_time DESC
                LIMIT 50
                """
            ).fetchall()
            if radio_stats:
                metrics["ap_radio_statistics"] = {str(row[0]): row[1] for row in radio_stats}
        return metrics

    def insert_active_segment(
        self,
        segment_values: Sequence[object],
        metric_values: Sequence[object],
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO active_segments (
                    session_id, radio, active_peer_mac, start_time, end_time, sample_count,
                    avg_mr_rssi, min_mr_rssi, max_mr_rssi, event_type, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(segment_values),
            )
            segment_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT OR REPLACE INTO active_segment_metrics (
                    segment_id, ping_sent, ping_success, ping_lost, ping_loss_percent, avg_latency_ms,
                    max_latency_ms, iperf_sample_count, avg_mbps, min_mbps, max_mbps, p95_mbps,
                    total_retransmits, avg_tx_busy, max_tx_busy, avg_rx_busy, max_rx_busy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (segment_id, *metric_values),
            )
        return segment_id

    def load_main_link_rows(self, session_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT collector_time, radio, link_state, peer_mac, peer_mac_normalized, mr_rssi
                FROM main_link_samples
                WHERE session_id = ?
                ORDER BY collector_time ASC, radio ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_identity_shadow_rows(self, *, limit: int = 5000) -> list[dict[str, object]]:
        """Read bounded Online MR identity candidates without mutating the parsed database."""

        safe_limit = max(1, min(int(limit), 5000))
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(main_link_samples)").fetchall()
            }
            if not columns:
                return []
            select_fields = [
                "session_id",
                "radio",
                "peer_name",
                "peer_mac",
                "peer_mac_normalized",
                "resolved_peer_name",
                *(
                    column
                    if column in columns
                    else ("NULL AS " + column if column == "identity_match_confidence" else "'' AS " + column)
                    for column in (
                        "peer_ap_mac",
                        "canonical_ap_mac",
                        "peer_radio_mac",
                        "identity_status",
                        "identity_source",
                        "identity_reason",
                        "identity_match_rule",
                        "identity_match_confidence",
                    )
                ),
                "bssid",
                "mesh_interface",
                "belong_station",
                "belong_section",
                "belong_type",
                "belonging_source",
            ]
            rows = conn.execute(
                f"""
                SELECT DISTINCT {', '.join(select_fields)}
                FROM main_link_samples
                WHERE COALESCE(
                    NULLIF(peer_mac, ''), NULLIF(peer_mac_normalized, ''),
                    NULLIF(peer_name, ''), NULLIF(bssid, ''), ''
                ) <> ''
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_timeline_segments(
        self,
        session_id: str,
        segments: Iterable[dict[str, object]],
    ) -> int:
        values = list(segments)
        with self._connect() as conn:
            for segment in values:
                rssis = list(segment.get("rssis") or [])
                cursor = conn.execute(
                    """
                    INSERT INTO active_segments (
                        session_id, radio, active_peer_mac, start_time, end_time, sample_count,
                        avg_mr_rssi, min_mr_rssi, max_mr_rssi, event_type, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        segment.get("radio"),
                        segment.get("active_peer_mac"),
                        segment.get("start_time"),
                        segment.get("end_time"),
                        segment.get("sample_count", 0),
                        sum(rssis) / len(rssis) if rssis else None,
                        min(rssis) if rssis else None,
                        max(rssis) if rssis else None,
                        segment.get("event_type"),
                        "{}",
                    ),
                )
                self._insert_timeline_metrics(
                    conn,
                    int(cursor.lastrowid),
                    str(segment.get("start_time")),
                    str(segment.get("end_time")),
                )
        return len(values)

    @staticmethod
    def _insert_timeline_metrics(
        conn: sqlite3.Connection,
        segment_id: int,
        start_time: str,
        end_time: str,
    ) -> None:
        ping = conn.execute(
            """
            SELECT COUNT(*) sent, SUM(success) success, AVG(latency_ms) avg_latency, MAX(latency_ms) max_latency
            FROM fping_samples WHERE COALESCE(device_aligned_time, collector_time) >= ? AND COALESCE(device_aligned_time, collector_time) < ?
            """,
            (start_time, end_time),
        ).fetchone()
        iperf = conn.execute(
            """
            SELECT COUNT(*) sample_count, AVG(bitrate_mbps), MIN(bitrate_mbps), MAX(bitrate_mbps), SUM(retransmits)
            FROM iperf_intervals
            WHERE COALESCE(NULLIF(device_interval_center_time, ''), NULLIF(device_aligned_time, ''), interval_center_time, collector_time) >= ?
              AND COALESCE(NULLIF(device_interval_center_time, ''), NULLIF(device_aligned_time, ''), interval_center_time, collector_time) < ?
            """,
            (start_time, end_time),
        ).fetchone()
        busy = conn.execute(
            """
            SELECT AVG(tx_busy), MAX(tx_busy), AVG(rx_busy), MAX(rx_busy)
            FROM channel_busy_records
            WHERE device_time >= ? AND device_time < ?
            """,
            (start_time, end_time),
        ).fetchone()
        sent = int(ping[0] or 0)
        success = int(ping[1] or 0)
        lost = sent - success
        loss_percent = (lost / sent * 100) if sent else None
        avg_latency = ping[2]
        max_latency = ping[3]
        if sent == 0:
            ping_summary = conn.execute(
                """
                SELECT SUM(sent), SUM(received), AVG(loss_percent), AVG(avg_latency_ms), MAX(max_latency_ms)
                FROM fping_1s_summary
                WHERE COALESCE(device_bucket_time, bucket_time, local_bucket_time) >= ?
                  AND COALESCE(device_bucket_time, bucket_time, local_bucket_time) < ?
                LIMIT 1
                """,
                (start_time, end_time),
            ).fetchone()
            if ping_summary and ping_summary[0] is not None:
                sent = int(ping_summary[0] or 0)
                success = int(ping_summary[1] or 0)
                lost = max(sent - success, 0)
                loss_percent = ping_summary[2]
                avg_latency = ping_summary[3]
                max_latency = ping_summary[4]
        if not iperf or int(iperf[0] or 0) == 0:
            iperf = conn.execute(
                "SELECT COUNT(*) sample_count, AVG(bitrate_mbps), MIN(bitrate_mbps), MAX(bitrate_mbps), SUM(retransmits) FROM iperf_intervals"
            ).fetchone()
        if not busy or all(value is None for value in busy):
            busy = conn.execute(
                "SELECT AVG(tx_busy), MAX(tx_busy), AVG(rx_busy), MAX(rx_busy) FROM channel_busy_records"
            ).fetchone()
        conn.execute(
            """
            INSERT OR REPLACE INTO active_segment_metrics (
                segment_id, ping_sent, ping_success, ping_lost, ping_loss_percent, avg_latency_ms,
                max_latency_ms, iperf_sample_count, avg_mbps, min_mbps, max_mbps, p95_mbps,
                total_retransmits, avg_tx_busy, max_tx_busy, avg_rx_busy, max_rx_busy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment_id,
                sent,
                success,
                lost,
                loss_percent,
                avg_latency,
                max_latency,
                iperf[0],
                iperf[1],
                iperf[2],
                iperf[3],
                iperf[3],
                iperf[4],
                busy[0],
                busy[1],
                busy[2],
                busy[3],
            ),
        )

    def start_iperf_run(
        self,
        run_id: str,
        *,
        mode: str,
        command: list[str],
        log_file: Path,
        started_at: datetime,
        session_id: str,
        device_id: object,
        protocol: str = "",
        server_ip: str = "",
        port: int | None = None,
        direction: str = "",
        parallel: int | None = None,
        target_bandwidth: str | None = None,
    ) -> None:
        self._initialize_iperf_store()

        def operation() -> None:
            with closing(connect_sqlite(self.db_path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO iperf_runs (
                        run_id, session_id, device_id, mode, protocol, server_ip, port, direction, parallel,
                        target_bandwidth, started_at, status, command_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        session_id,
                        device_id,
                        mode,
                        protocol,
                        server_ip,
                        port,
                        direction,
                        parallel,
                        target_bandwidth,
                        started_at.isoformat(sep=" ", timespec="milliseconds"),
                        "RUNNING",
                        json.dumps(command, ensure_ascii=False),
                    ),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def append_iperf_interval(
        self,
        run_id: str,
        row: dict[str, object],
        session_id: str,
    ) -> None:
        def operation() -> None:
            with closing(connect_sqlite(self.db_path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO iperf_intervals (
                        run_id, session_id, collector_time, interval_start_sec, interval_end_sec, interval_center_time,
                        device_aligned_time, device_interval_center_time, clock_offset_ms, offset_source, time_source,
                        transfer_bytes, bitrate_mbps, retransmits, cwnd, role, jitter_ms, lost_packets,
                        total_packets, loss_percent, source_event_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, source_event_key) WHERE source_event_key <> '' DO NOTHING
                    """,
                    (
                        run_id,
                        session_id,
                        row.get("collector_time"),
                        row.get("interval_start_sec"),
                        row.get("interval_end_sec"),
                        row.get("interval_center_time"),
                        row.get("device_aligned_time"),
                        row.get("device_interval_center_time"),
                        row.get("clock_offset_ms"),
                        row.get("offset_source"),
                        row.get("time_source"),
                        row.get("transfer_bytes"),
                        row.get("bitrate_mbps"),
                        row.get("retransmits"),
                        row.get("cwnd"),
                        row.get("role"),
                        row.get("jitter_ms"),
                        row.get("lost_packets"),
                        row.get("total_packets"),
                        row.get("loss_percent"),
                        "",
                    ),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def finish_iperf_run(
        self,
        run_id: str,
        status: str,
        ended_at: datetime | None = None,
    ) -> None:
        def operation() -> None:
            with closing(connect_sqlite(self.db_path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE iperf_runs SET status = ?, ended_at = ? WHERE run_id = ?",
                    (
                        status,
                        (ended_at or datetime.now()).isoformat(sep=" ", timespec="milliseconds"),
                        run_id,
                    ),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def _initialize_iperf_store(self) -> None:
        def operation() -> None:
            with closing(connect_sqlite(self.db_path)) as conn:
                initialize_sqlite_wal(conn)
                conn.executescript(IPERF_SCHEMA)
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(iperf_intervals)").fetchall()
                }
                for column, definition in {
                    "device_aligned_time": "TEXT",
                    "device_interval_center_time": "TEXT",
                    "clock_offset_ms": "REAL",
                    "offset_source": "TEXT",
                    "time_source": "TEXT",
                }.items():
                    if column not in columns:
                        conn.execute(f"ALTER TABLE iperf_intervals ADD COLUMN {column} {definition}")
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(iperf_intervals)").fetchall()
                }
                if "source_event_key" not in columns:
                    conn.execute(
                        "ALTER TABLE iperf_intervals ADD COLUMN source_event_key TEXT NOT NULL DEFAULT ''"
                    )
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_iperf_intervals_source_event
                    ON iperf_intervals(run_id, source_event_key)
                    WHERE source_event_key <> ''
                    """
                )
                conn.commit()

        run_sqlite_with_retry(operation)


__all__ = ["OnlineMrDatabaseError", "OnlineMrDiagnosisRepository"]
