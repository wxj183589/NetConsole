from __future__ import annotations

import hashlib
import gc
import json
import sqlite3
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping

from netconsole.core import app_logger
from netconsole.core.sqlite_utils import configure_sqlite_connection, initialize_sqlite_wal
from netconsole.models.mesh_log_models import (
    EVENT_ACTIVE_SWITCH,
    EVENT_COUNTER_RESET,
    EVENT_MULTI_ACTIVE,
    EVENT_NO_ACTIVE,
    LINK_STATE_ACTIVE,
    LINK_STATE_STANDBY,
    MeshLogRecord,
    PAIRED_METRICS,
    MeshSwitchEvent,
    ParseIssue,
    format_mac_h3c,
    summarize_parse_issues,
)
from netconsole.models.mesh_analysis_params import MeshAnalysisParams, mesh_analysis_params_from_json, normalize_mesh_analysis_params
from netconsole.services.mesh_link_analyzer import MeshLinkAnalyzer
from netconsole.repositories.mesh_catalog_repository import dt_text
from netconsole.services.ap_identity.normalizers import (
    format_mac,
    normalize_mac,
    normalize_mac_key,
)
from netconsole.services.mesh_rssi_stats import calc_numeric_stats


SCHEMA_VERSION = "meshlog_compact_v3_tagged_samples"
SCHEMA_KEY = "schema_" + "version"
PARSER_VERSION = "meshlog_parser_v1"
DERIVED_ANALYSIS_VERSION = "6"
DERIVED_ANALYSIS_KEY = "derived_analysis_version"
MIN_NORMAL_ACTIVE_SAMPLE_COUNT = 3
_METRIC_COLUMNS = tuple(dict.fromkeys(column for _name, left, right in PAIRED_METRICS for column in (left, right)))
_METRIC_SELECT_COLUMNS = ", ".join(_METRIC_COLUMNS)
_MESH_LINK_CHART_COLUMNS = (
    "id, sample_id, source_file_id, session_id, sample_time, radio, link_state, link_count, peer_mac_raw, peer_mac_normalized, "
    "peer_mac AS peer_mac_display, "
    "peer_ap_name, peer_ap_mac, peer_site, peer_radio, peer_radio_label, peer_radio_mac, establish_time, "
    "local_signal_dbm, peer_signal_dbm, "
    "(SELECT s.timestamp_tag FROM samples s WHERE s.id = mesh_links.sample_id) AS timestamp_tag, "
    + _METRIC_SELECT_COLUMNS
)
_MESH_LINK_CHART_IDENTITY_COLUMNS = (
    "peer_identity_status",
    "peer_identity_source",
    "peer_identity_reason",
    "peer_match_rule",
    "peer_match_confidence",
)
_MESH_LINK_IDENTITY_PROJECTION_COLUMNS = {
    "peer_ap_name",
    "peer_ap_mac",
    "peer_site",
    "peer_section",
    "peer_location",
    "peer_direction",
    "peer_radio_id",
    "peer_radio",
    "peer_radio_label",
    "peer_radio_mac",
    "peer_match_rule",
    "peer_match_confidence",
    "peer_resolve_source",
    "peer_identity_status",
    "peer_identity_source",
    "peer_identity_reason",
}
_MESH_EVENT_CHART_COLUMNS = (
    "id, source_file_id, event_time, event_type, radio, from_peer_mac, to_peer_mac, "
    "previous_sample_time, current_sample_time, observed_window_ms, details_json"
)
_MESH_PERFORMANCE_INDEXES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "idx_mesh_links_source_radio_time_id",
        "mesh_links",
        ("source_file_id", "radio", "sample_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_mesh_links_source_radio_time_id "
        "ON mesh_links(source_file_id, radio, sample_time, id)",
    ),
    (
        "idx_mesh_links_source_time_radio_id",
        "mesh_links",
        ("source_file_id", "sample_time", "radio", "id"),
        "CREATE INDEX IF NOT EXISTS idx_mesh_links_source_time_radio_id "
        "ON mesh_links(source_file_id, sample_time, radio, id)",
    ),
    (
        "idx_mesh_links_source_state_radio_time_id",
        "mesh_links",
        ("source_file_id", "link_state", "radio", "sample_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_mesh_links_source_state_radio_time_id "
        "ON mesh_links(source_file_id, link_state, radio, sample_time, id)",
    ),
    (
        "idx_mesh_links_source_peer_radio_time_id",
        "mesh_links",
        ("source_file_id", "peer_mac_normalized", "radio", "sample_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_mesh_links_source_peer_radio_time_id "
        "ON mesh_links(source_file_id, peer_mac_normalized, radio, sample_time, id)",
    ),
    (
        "idx_active_points_source_radio_time_id",
        "active_points",
        ("source_file_id", "radio", "sample_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_active_points_source_radio_time_id "
        "ON active_points(source_file_id, radio, sample_time, id)",
    ),
    (
        "idx_switch_events_source_radio_time_id",
        "switch_events",
        ("source_file_id", "radio", "event_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_switch_events_source_radio_time_id "
        "ON switch_events(source_file_id, radio, event_time, id)",
    ),
    (
        "idx_active_segments_source_radio_start_id",
        "active_segments",
        ("source_file_id", "radio", "start_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_active_segments_source_radio_start_id "
        "ON active_segments(source_file_id, radio, start_time, id)",
    ),
    (
        "idx_switch_events_source_time_id",
        "switch_events",
        ("source_file_id", "event_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_switch_events_source_time_id "
        "ON switch_events(source_file_id, event_time, id)",
    ),
    (
        "idx_switch_events_source_type_time_id",
        "switch_events",
        ("source_file_id", "event_type", "event_time", "id"),
        "CREATE INDEX IF NOT EXISTS idx_switch_events_source_type_time_id "
        "ON switch_events(source_file_id, event_type, event_time, id)",
    ),
    (
        "idx_mesh_links_record_order",
        "mesh_links",
        ("source_file_order", "record_seq", "source_line_number", "id"),
        "CREATE INDEX IF NOT EXISTS idx_mesh_links_record_order "
        "ON mesh_links(source_file_order, record_seq, source_line_number, id)",
    ),
)


def _mesh_link_identity_columns(
    conn: sqlite3.Connection,
    *,
    table_alias: str = "",
) -> str:
    existing = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in conn.execute("PRAGMA table_info(mesh_links)").fetchall()
    }
    prefix = f"{table_alias}." if table_alias else ""
    return ", ".join(
        f"{prefix}{column} AS {column}"
        if column in existing
        else f"NULL AS {column}"
        for column in _MESH_LINK_CHART_IDENTITY_COLUMNS
    )


def _mesh_link_chart_columns(conn: sqlite3.Connection) -> str:
    return f"{_MESH_LINK_CHART_COLUMNS}, {_mesh_link_identity_columns(conn)}"


@dataclass(frozen=True)
class RowPosition:
    row_index: int
    page_no: int
    index_in_page: int
    link_id: int
    total: int = 0
    page_size: int = 1000


@dataclass(frozen=True)
class DeleteParsedDataResult:
    ok: bool
    source_file_id: str
    deleted_links: int = 0
    deleted_events: int = 0
    deleted_issues: int = 0
    deleted_caches: int = 0
    message: str = ""


class MeshSchemaRebuildRequired(RuntimeError):
    pass


class MeshIdentityRemapValidationError(RuntimeError):
    def __init__(self, code: str, details: dict[str, object]) -> None:
        self.code = code
        self.details = details
        fields = ", ".join(f"{key}={value}" for key, value in details.items())
        super().__init__(f"{code}: {fields}")


class _ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class _ReadOnlyConnection(_ManagedConnection):
    pass


def _read_only_uri(path: Path) -> str:
    """无 WAL 数据时使用 immutable URI，避免只读查询创建运行侧车。"""

    uri = f"{path.resolve().as_uri()}?mode=ro"
    wal_path = path.with_name(path.name + "-wal")
    if not wal_path.is_file() or wal_path.stat().st_size == 0:
        uri += "&immutable=1"
    return uri


class MeshMrRepository:
    def __init__(
        self,
        path: Path,
        *,
        read_only: bool = False,
        parsed_dir: Path | None = None,
        index_database: bool | None = None,
    ) -> None:
        self.path = path
        self.read_only = read_only
        self.parsed_dir = Path(parsed_dir) if parsed_dir is not None else self.path.parent / "parsed"
        self._index_database = index_database
        if read_only:
            if not self.path.is_file() or not self._is_compact_schema(self.path):
                raise MeshSchemaRebuildRequired("MESH 派生数据库不存在或版本不兼容")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        if self.path.exists() and not self._is_compact_schema(self.path):
            raise MeshSchemaRebuildRequired(
                "MESH 派生数据库版本不兼容，系统将自动修复。"
            )
        is_new_database = not self.path.exists()
        with self._connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_' || 'version', 'meshlog_compact_v3_tagged_samples');
                INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', 'meshlog_compact_v3_tagged_samples');
                CREATE TABLE IF NOT EXISTS source_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mr_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    archived_path TEXT NOT NULL,
                    parsed_db_path TEXT DEFAULT '',
                    parsed_db_size INTEGER DEFAULT 0,
                    db_schema_version TEXT DEFAULT '',
                    original_filename TEXT NOT NULL,
                    archived_filename TEXT NOT NULL,
                    stored_filename TEXT DEFAULT '',
                    sha256 TEXT NOT NULL UNIQUE,
                    raw_sha256 TEXT DEFAULT '',
                    content_sha256 TEXT DEFAULT '',
                    profile_id TEXT DEFAULT '',
                    linked_mr_id TEXT DEFAULT '',
                    file_size INTEGER NOT NULL,
                    file_mtime TEXT NULL,
                    imported_at TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    encoding TEXT DEFAULT '',
                    is_gzip INTEGER DEFAULT 0,
                    first_sample_time TEXT NULL,
                    last_sample_time TEXT NULL,
                    first_log_timestamp TEXT NULL,
                    last_log_timestamp TEXT NULL,
                    log_date TEXT NULL,
                    daily_sequence INTEGER NULL,
                    rename_status TEXT DEFAULT '',
                    rename_warning TEXT DEFAULT '',
                    source_status TEXT DEFAULT 'imported',
                    source_type TEXT DEFAULT 'manual_upload',
                    source_device_id TEXT DEFAULT '',
                    parse_task_id TEXT DEFAULT '',
                    lines_read INTEGER DEFAULT 0,
                    records_parsed INTEGER DEFAULT 0,
                    records_skipped INTEGER DEFAULT 0,
                    duplicate_records INTEGER DEFAULT 0,
                    issue_count INTEGER DEFAULT 0,
                    info_count INTEGER DEFAULT 0,
                    warning_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    issue_severity_version INTEGER DEFAULT 0,
                    error_message TEXT DEFAULT '',
                    file_exists INTEGER DEFAULT 1,
                    deleted_at TEXT DEFAULT '',
                    delete_error TEXT DEFAULT '',
                    file_status TEXT DEFAULT 'ok',
                    parsed_deleted_at TEXT DEFAULT '',
                    parsed_delete_error TEXT DEFAULT '',
                    source_file_order INTEGER DEFAULT 0,
                    analysis_params_json TEXT DEFAULT '',
                    identity_index_revision INTEGER DEFAULT 0,
                    identity_mapped_at TEXT DEFAULT '',
                    identity_mapping_status TEXT DEFAULT 'unknown',
                    raw_relative_path TEXT DEFAULT '',
                    parsed_relative_path TEXT DEFAULT '',
                    archive_sha256 TEXT DEFAULT '',
                    bundle_member_id TEXT DEFAULT '',
                    bundle_member_sha256 TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                    radio INTEGER NOT NULL,
                    sample_time TEXT NOT NULL,
                    device_time TEXT NULL,
                    sample_time_epoch_ms INTEGER NOT NULL,
                    timestamp_tag TEXT NOT NULL DEFAULT '',
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0,
                    raw_offset_start INTEGER DEFAULT 0,
                    raw_offset_end INTEGER DEFAULT 0,
                    UNIQUE(source_file_id, radio, sample_time, timestamp_tag)
                );
                CREATE TABLE IF NOT EXISTS mesh_sessions (
                    session_id TEXT PRIMARY KEY,
                    radio INTEGER NOT NULL,
                    peer_mac_normalized TEXT NULL,
                    peer_mac_raw TEXT NOT NULL,
                    establish_time TEXT NULL,
                    first_sample_time TEXT NOT NULL,
                    last_sample_time TEXT NOT NULL,
                    sample_count INTEGER DEFAULT 0,
                    active_sample_count INTEGER DEFAULT 0,
                    standby_sample_count INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS mesh_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                    source_file_order INTEGER NOT NULL,
                    record_seq INTEGER NOT NULL,
                    source_line_number INTEGER NOT NULL,
                    radio INTEGER NOT NULL,
                    sample_time TEXT NOT NULL,
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0,
                    raw_offset_start INTEGER DEFAULT 0,
                    raw_offset_end INTEGER DEFAULT 0,
                    link_state_raw TEXT NOT NULL,
                    link_state TEXT NOT NULL,
                    peer_mac_raw TEXT NOT NULL,
                    peer_mac_normalized TEXT NULL,
                    peer_mac TEXT DEFAULT '',
                    peer_ap_name TEXT DEFAULT '',
                    peer_ap_mac TEXT DEFAULT '',
                    peer_site TEXT DEFAULT '',
                    peer_section TEXT DEFAULT '',
                    peer_location TEXT DEFAULT '',
                    peer_direction TEXT DEFAULT '',
                    peer_radio_id INTEGER NULL,
                    peer_radio TEXT DEFAULT '',
                    peer_radio_label TEXT DEFAULT '',
                    peer_radio_mac TEXT DEFAULT '',
                    peer_match_rule TEXT DEFAULT '',
                    peer_match_confidence INTEGER DEFAULT 0,
                    peer_resolve_source TEXT DEFAULT 'unresolved',
                    peer_identity_status TEXT DEFAULT 'unresolved',
                    peer_identity_source TEXT DEFAULT '',
                    peer_identity_reason TEXT DEFAULT '',
                    establish_time TEXT NULL,
                    duration_text TEXT NOT NULL,
                    duration_seconds INTEGER NULL,
                    expected_duration_seconds INTEGER NULL,
                    duration_deviation_seconds INTEGER NULL,
                    link_count INTEGER NULL,
                    session_id TEXT NULL,
                    local_rssi_db INTEGER NULL,
                    peer_rssi_db INTEGER NULL,
                    local_cpu_percent INTEGER NULL,
                    peer_cpu_percent INTEGER NULL,
                    local_mem_percent INTEGER NULL,
                    peer_mem_percent INTEGER NULL,
                    local_tx_busy INTEGER NULL,
                    peer_tx_busy INTEGER NULL,
                    local_rx_busy INTEGER NULL,
                    peer_rx_busy INTEGER NULL,
                    local_rate_raw INTEGER NULL,
                    peer_rate_raw INTEGER NULL,
                    local_noise_raw INTEGER NULL,
                    peer_noise_raw INTEGER NULL,
                    local_tx_des_free_cnt INTEGER NULL,
                    peer_tx_des_free_cnt INTEGER NULL,
                    local_tx INTEGER NULL,
                    peer_tx INTEGER NULL,
                    local_rx INTEGER NULL,
                    peer_rx INTEGER NULL,
                    local_retry INTEGER NULL,
                    peer_retry INTEGER NULL,
                    local_err INTEGER NULL,
                    peer_err INTEGER NULL,
                    local_tx_garp INTEGER NULL,
                    peer_rx_garp INTEGER NULL,
                    local_tx_mul_join INTEGER NULL,
                    peer_rx_mul_join INTEGER NULL,
                    local_noise_dbm INTEGER NULL,
                    peer_noise_dbm INTEGER NULL,
                    local_signal_dbm INTEGER NULL,
                    peer_signal_dbm INTEGER NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS active_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link_id INTEGER NOT NULL UNIQUE REFERENCES mesh_links(id) ON DELETE CASCADE,
                    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                    session_id TEXT DEFAULT '',
                    sample_time TEXT NOT NULL,
                    device_time TEXT NULL,
                    radio INTEGER,
                    peer_mac_raw TEXT DEFAULT '',
                    peer_mac_normalized TEXT DEFAULT '',
                    peer_mac TEXT DEFAULT '',
                    peer_ap_name TEXT DEFAULT '',
                    peer_site TEXT DEFAULT '',
                    peer_section TEXT DEFAULT '',
                    peer_location TEXT DEFAULT '',
                    peer_direction TEXT DEFAULT '',
                    peer_radio TEXT DEFAULT '',
                    peer_radio_label TEXT DEFAULT '',
                    establish_time TEXT NULL,
                    duration_text TEXT DEFAULT '',
                    duration_seconds INTEGER NULL,
                    link_count INTEGER NULL,
                    local_rssi_db INTEGER NULL,
                    peer_rssi_db INTEGER NULL,
                    local_tx_busy INTEGER NULL,
                    peer_tx_busy INTEGER NULL,
                    local_rx_busy INTEGER NULL,
                    peer_rx_busy INTEGER NULL,
                    local_noise_dbm INTEGER NULL,
                    peer_noise_dbm INTEGER NULL,
                    local_signal_dbm INTEGER NULL,
                    peer_signal_dbm INTEGER NULL,
                    segment_id INTEGER NULL,
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0,
                    raw_offset_start INTEGER DEFAULT 0,
                    raw_offset_end INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS active_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    radio INTEGER,
                    peer_mac TEXT DEFAULT '',
                    peer_mac_normalized TEXT DEFAULT '',
                    peer_ap_name TEXT DEFAULT '',
                    belong_station TEXT DEFAULT '',
                    belong_section TEXT DEFAULT '',
                    belong_type TEXT DEFAULT '',
                    start_time TEXT,
                    end_time TEXT,
                    duration_sec REAL,
                    sample_count INTEGER,
                    avg_rssi REAL,
                    min_rssi INTEGER,
                    max_rssi INTEGER,
                    start_rssi INTEGER,
                    end_rssi INTEGER,
                    event_type TEXT DEFAULT 'stable',
                    source_file_id INTEGER NULL
                );
                CREATE TABLE IF NOT EXISTS switch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_time TEXT NULL,
                    radio INTEGER NOT NULL,
                    previous_sample_time TEXT NULL,
                    current_sample_time TEXT NULL,
                    observed_window_ms INTEGER NULL,
                    from_peer_mac TEXT NULL,
                    to_peer_mac TEXT NULL,
                    details_json TEXT NOT NULL,
                    source_file_id INTEGER NULL,
                    source_line_number INTEGER DEFAULT 0,
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS parse_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER NULL,
                    source_file TEXT NOT NULL,
                    line_number INTEGER NOT NULL,
                    severity TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    field_name TEXT DEFAULT '',
                    message TEXT NOT NULL,
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rssi_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_type TEXT,
                    scope_key TEXT,
                    sample_count INTEGER,
                    avg_rssi REAL,
                    min_rssi INTEGER,
                    max_rssi INTEGER,
                    p10_rssi REAL,
                    p50_rssi REAL,
                    p90_rssi REAL,
                    low_rssi_count INTEGER,
                    severe_low_rssi_count INTEGER
                );
                CREATE TABLE IF NOT EXISTS diagnosis_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TEXT,
                    severity TEXT,
                    category TEXT,
                    title TEXT,
                    detail TEXT,
                    evidence TEXT,
                    recommendation TEXT,
                    related_peer_mac TEXT,
                    related_sample_id INTEGER,
                    related_segment_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS mesh_peer_mapping (
                    peer_mac_normalized TEXT PRIMARY KEY,
                    peer_ap_name TEXT DEFAULT '',
                    peer_ap_mac TEXT DEFAULT '',
                    peer_radio_id INTEGER NULL,
                    peer_radio_label TEXT DEFAULT '',
                    peer_site TEXT DEFAULT '',
                    peer_section TEXT DEFAULT '',
                    peer_location TEXT DEFAULT '',
                    peer_direction TEXT DEFAULT '',
                    match_rule TEXT DEFAULT '',
                    match_confidence INTEGER DEFAULT 0,
                    identity_status TEXT DEFAULT 'unresolved',
                    identity_source TEXT DEFAULT '',
                    identity_reason TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mesh_peer_resolve_cache (
                    peer_mac TEXT PRIMARY KEY,
                    peer_ap_name TEXT DEFAULT '',
                    peer_site TEXT DEFAULT '',
                    peer_radio TEXT DEFAULT '',
                    peer_radio_mac TEXT DEFAULT '',
                    source TEXT DEFAULT 'unresolved',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_samples_time ON samples(sample_time);
                CREATE INDEX IF NOT EXISTS idx_links_sample ON mesh_links(sample_id);
                CREATE INDEX IF NOT EXISTS idx_links_time ON mesh_links(sample_time);
                CREATE INDEX IF NOT EXISTS idx_links_state_time ON mesh_links(link_state, sample_time);
                CREATE INDEX IF NOT EXISTS idx_links_peer_time ON mesh_links(peer_mac_normalized, sample_time);
                CREATE INDEX IF NOT EXISTS idx_sessions_peer ON mesh_sessions(radio, peer_mac_normalized);
                CREATE INDEX IF NOT EXISTS idx_active_time ON active_points(sample_time);
                CREATE INDEX IF NOT EXISTS idx_active_peer_time ON active_points(peer_mac_normalized, sample_time);
                CREATE INDEX IF NOT EXISTS idx_active_segment ON active_points(segment_id);
                CREATE INDEX IF NOT EXISTS idx_segments_time ON active_segments(start_time, end_time);
                CREATE INDEX IF NOT EXISTS idx_switch_time ON switch_events(event_time);
                CREATE INDEX IF NOT EXISTS idx_parse_issues_source_file ON parse_issues(source_file_id);
                CREATE INDEX IF NOT EXISTS idx_source_sha ON source_files(sha256);
                CREATE INDEX IF NOT EXISTS idx_mesh_peer_mapping_ap ON mesh_peer_mapping(peer_ap_name);
                CREATE INDEX IF NOT EXISTS idx_mesh_peer_mapping_site ON mesh_peer_mapping(peer_site);
                CREATE INDEX IF NOT EXISTS idx_mesh_peer_resolve_cache_ap ON mesh_peer_resolve_cache(peer_ap_name);
                CREATE INDEX IF NOT EXISTS idx_mesh_peer_resolve_cache_site ON mesh_peer_resolve_cache(peer_site);
                CREATE VIEW IF NOT EXISTS mesh_events AS SELECT * FROM switch_events;
                """
            )
            # CREATE IF NOT EXISTS statements above are idempotent.  Existing
            # compact databases still need additive compatibility migrations;
            # serialize that PRAGMA/ALTER sequence across processes.
            conn.execute("BEGIN IMMEDIATE")
            if is_new_database:
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('parser_version', ?)",
                    (PARSER_VERSION,),
                )
            for column in (
                "raw_relative_path",
                "parsed_relative_path",
                "archive_sha256",
                "bundle_member_id",
                "bundle_member_sha256",
                "stored_filename",
                "raw_sha256",
                "content_sha256",
                "profile_id",
                "linked_mr_id",
                "first_log_timestamp",
                "last_log_timestamp",
                "log_date",
                "rename_status",
                "rename_warning",
                "source_status",
                "source_device_id",
                "parse_task_id",
            ):
                self._ensure_column(conn, "source_files", column, "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "source_type", "TEXT DEFAULT 'manual_upload'")
            conn.execute(
                "UPDATE source_files SET source_type = 'manual_upload' "
                "WHERE COALESCE(source_type, '') = ''"
            )
            self._ensure_column(conn, "source_files", "daily_sequence", "INTEGER NULL")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_source_content_sha_unique
                ON source_files(content_sha256)
                WHERE COALESCE(content_sha256, '') != ''
                """
            )
            self._ensure_column(conn, "mesh_links", "peer_ap_name", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_ap_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_site", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_section", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_location", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_direction", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_id", "INTEGER NULL")
            self._ensure_column(conn, "mesh_links", "peer_radio", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_label", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_match_rule", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_match_confidence", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "mesh_links", "peer_resolve_source", "TEXT DEFAULT 'unresolved'")
            self._ensure_column(conn, "mesh_links", "peer_identity_status", "TEXT DEFAULT 'unresolved'")
            self._ensure_column(conn, "mesh_links", "peer_identity_source", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_identity_reason", "TEXT DEFAULT ''")
            self._ensure_column(conn, "active_points", "peer_section", "TEXT DEFAULT ''")
            self._ensure_column(conn, "active_points", "peer_location", "TEXT DEFAULT ''")
            self._ensure_column(conn, "active_points", "peer_direction", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_peer_mapping", "peer_section", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_peer_mapping", "peer_location", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_peer_mapping", "peer_direction", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_peer_mapping", "identity_status", "TEXT DEFAULT 'unresolved'")
            self._ensure_column(conn, "mesh_peer_mapping", "identity_source", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_peer_mapping", "identity_reason", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "source_file_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "mesh_links", "record_seq", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "file_exists", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "source_files", "deleted_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "delete_error", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "file_status", "TEXT DEFAULT 'ok'")
            self._ensure_column(conn, "source_files", "parsed_deleted_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "parsed_delete_error", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "source_file_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "parsed_db_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "parsed_db_size", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "db_schema_version", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "analysis_params_json", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "identity_index_revision", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "identity_mapped_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "source_files", "identity_mapping_status", "TEXT DEFAULT 'unknown'")
            self._ensure_column(conn, "source_files", "info_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "warning_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "error_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "source_files", "issue_severity_version", "INTEGER DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_peer_ap ON mesh_links(peer_ap_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_peer_site ON mesh_links(peer_site)")
            self._ensure_performance_indexes(conn)
            self._backfill_peer_columns(conn)
            if is_new_database:
                conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))
            self._update_meta_counts(conn)
        conn.close()

    @staticmethod
    def _is_compact_schema(path: Path) -> bool:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(_read_only_uri(path), uri=True, timeout=5)
            conn.execute("PRAGMA query_only = ON")
            row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (SCHEMA_KEY,)).fetchone()
            if row is not None:
                return str(row[0] or "") == SCHEMA_VERSION
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            return row is not None and str(row[0] or "") == SCHEMA_VERSION
        except sqlite3.Error:
            return False
        finally:
            if conn is not None:
                conn.close()

    def _is_index_database(self) -> bool:
        if self._index_database is not None:
            return self._index_database
        return self.path.name == "mesh.sqlite" and self.path.parent.name != "parsed"

    def _single_log_db_path(self, archived_path: Path, sha256: str) -> Path:
        parsed_dir = self.parsed_dir
        parsed_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_mesh_db_stem(archived_path.name)
        candidate = parsed_dir / f"{stem}.mesh.sqlite"
        if candidate.exists():
            candidate = parsed_dir / f"{stem}__{sha256[:8]}.mesh.sqlite"
        return candidate

    def _detail_db_path_for_source(self, source_file_id: int | str | None) -> Path | None:
        if not self._is_index_database() or source_file_id in (None, ""):
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT parsed_db_path FROM source_files WHERE id = ?", (int(source_file_id),)).fetchone()
        if row is None:
            return None
        value = str(row["parsed_db_path"] or "").strip().strip("'\"")
        return Path(value) if value else None

    def _detail_repo_for_source(self, source_file_id: int | str | None) -> MeshMrRepository | None:
        path = self._detail_db_path_for_source(source_file_id)
        if path is None or not path.exists():
            return None
        return MeshMrRepository(path)

    def _detail_repos(self) -> list[MeshMrRepository]:
        return [repo for _source_file_id, repo in self._detail_repo_items()]

    def _detail_repo_items(self) -> list[tuple[int, MeshMrRepository]]:
        if not self._is_index_database():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, parsed_db_path FROM source_files WHERE COALESCE(parsed_deleted_at, '') = '' ORDER BY source_file_order ASC, id ASC"
            ).fetchall()
        repos: list[tuple[int, MeshMrRepository]] = []
        for row in rows:
            path = Path(str(row["parsed_db_path"] or "").strip().strip("'\""))
            if path.exists():
                repos.append((int(row["id"]), MeshMrRepository(path)))
        return repos

    def has_sha256(self, sha256: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM source_files WHERE sha256 = ?", (sha256,)).fetchone() is not None

    def find_by_content_sha256(self, content_sha256: str, *, raw_sha256: str = "") -> dict[str, object] | None:
        content_value = str(content_sha256 or "").strip().casefold()
        raw_value = str(raw_sha256 or "").strip().casefold()
        with self._connect() as conn:
            row = None
            if content_value:
                row = conn.execute(
                    "SELECT * FROM source_files WHERE content_sha256 = ? LIMIT 1",
                    (content_value,),
                ).fetchone()
            if row is None and raw_value:
                row = conn.execute(
                    """
                    SELECT * FROM source_files
                    WHERE sha256 = ? OR raw_sha256 = ?
                    LIMIT 1
                    """,
                    (raw_value, raw_value),
                ).fetchone()
        return dict(row) if row else None

    def has_content_sha256(self, content_sha256: str, *, raw_sha256: str = "") -> bool:
        return self.find_by_content_sha256(content_sha256, raw_sha256=raw_sha256) is not None

    def update_source_fingerprints(
        self,
        source_file_id: int,
        *,
        raw_sha256: str,
        content_sha256: str,
        first_log_timestamp: datetime | None,
        last_log_timestamp: datetime | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE source_files
                SET raw_sha256 = ?, content_sha256 = ?,
                    first_log_timestamp = COALESCE(NULLIF(first_log_timestamp, ''), ?),
                    last_log_timestamp = COALESCE(NULLIF(last_log_timestamp, ''), ?),
                    log_date = COALESCE(NULLIF(log_date, ''), ?)
                WHERE id = ?
                """,
                (
                    raw_sha256,
                    content_sha256,
                    dt_text(first_log_timestamp),
                    dt_text(last_log_timestamp),
                    first_log_timestamp.date().isoformat() if first_log_timestamp else None,
                    int(source_file_id),
                ),
            )

    def insert_file_result(
        self,
        mr_id: str,
        original_path: Path,
        archived_path: Path,
        sha256: str,
        file_size: int,
        file_mtime: datetime | None,
        parser_version: str,
        parse_status: str,
        first_sample_time: datetime | None,
        last_sample_time: datetime | None,
        lines_read: int,
        records_parsed: int,
        records_skipped: int,
        duplicate_records: int,
        issue_count: int,
        error_message: str,
        records: list[MeshLogRecord],
        events: list[MeshSwitchEvent],
        issues: list[ParseIssue],
        analysis_params_json: str = "",
        *,
        raw_sha256: str = "",
        content_sha256: str = "",
        profile_id: str = "",
        linked_mr_id: str = "",
        first_log_timestamp: datetime | None = None,
        last_log_timestamp: datetime | None = None,
        log_date: str = "",
        daily_sequence: int | None = None,
        rename_status: str = "",
        rename_warning: str = "",
        source_status: str = "imported",
        source_type: str = "manual_upload",
        source_device_id: str = "",
        parse_task_id: str = "",
    ) -> int:
        issue_counts = summarize_parse_issues(issues)
        issue_count = issue_counts["total"]
        if not self._is_index_database():
            return self._insert_file_result_current_db(
                mr_id,
                original_path,
                archived_path,
                sha256,
                file_size,
                file_mtime,
                parser_version,
                parse_status,
                first_sample_time,
                last_sample_time,
                lines_read,
                records_parsed,
                records_skipped,
                duplicate_records,
                issue_count,
                error_message,
                records,
                events,
                issues,
                analysis_params_json,
                raw_sha256=raw_sha256,
                content_sha256=content_sha256,
                profile_id=profile_id,
                linked_mr_id=linked_mr_id,
                first_log_timestamp=first_log_timestamp,
                last_log_timestamp=last_log_timestamp,
                log_date=log_date,
                daily_sequence=daily_sequence,
                rename_status=rename_status,
                rename_warning=rename_warning,
                source_status=source_status,
                source_type=source_type,
                source_device_id=source_device_id,
                parse_task_id=parse_task_id,
            )

        detail_path = self._single_log_db_path(archived_path, sha256)
        if detail_path.exists():
            detail_path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = detail_path.with_name(detail_path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_files (
                    mr_id, original_path, archived_path, parsed_db_path, parsed_db_size, db_schema_version,
                    original_filename, archived_filename, sha256, file_size, file_mtime, imported_at,
                    stored_filename, raw_sha256, content_sha256, profile_id, linked_mr_id,
                    parser_version, parse_status, encoding, is_gzip, first_sample_time, last_sample_time,
                    first_log_timestamp, last_log_timestamp, log_date, daily_sequence,
                    rename_status, rename_warning, source_status, source_type, source_device_id, parse_task_id,
                    lines_read, records_parsed, records_skipped, duplicate_records, issue_count, error_message,
                    analysis_params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mr_id,
                    str(original_path),
                    str(archived_path),
                    str(detail_path),
                    0,
                    SCHEMA_VERSION,
                    original_path.name,
                    archived_path.name,
                    sha256,
                    file_size,
                    dt_text(file_mtime),
                    dt_text(datetime.now()),
                    archived_path.name,
                    raw_sha256 or sha256,
                    content_sha256 or sha256,
                    profile_id or mr_id,
                    linked_mr_id,
                    parser_version,
                    parse_status,
                    "",
                    1 if archived_path.name.lower().endswith(".gz") else 0,
                    dt_text(first_sample_time),
                    dt_text(last_sample_time),
                    dt_text(first_log_timestamp or first_sample_time),
                    dt_text(last_log_timestamp or last_sample_time),
                    log_date or ((first_log_timestamp or first_sample_time).date().isoformat() if first_log_timestamp or first_sample_time else None),
                    daily_sequence,
                    rename_status,
                    rename_warning,
                    source_status,
                    source_type,
                    source_device_id,
                    parse_task_id,
                    lines_read,
                    records_parsed,
                    records_skipped,
                    duplicate_records,
                    issue_count,
                    error_message,
                    analysis_params_json,
                ),
            )
            source_file_id = int(cursor.lastrowid)
            conn.execute(
                "UPDATE source_files SET info_count = ?, warning_count = ?, error_count = ?, issue_severity_version = 1 WHERE id = ?",
                (
                    issue_counts["info"],
                    issue_counts["warning"],
                    issue_counts["error"],
                    source_file_id,
                ),
            )
            file_order = min((int(record.source_file_order or 0) for record in records if int(record.source_file_order or 0) > 0), default=source_file_id)
            conn.execute("UPDATE source_files SET source_file_order = ? WHERE id = ?", (file_order, source_file_id))
            self._update_meta_counts(conn)

        detail_repo = MeshMrRepository(detail_path)
        detail_repo._insert_file_result_current_db(
            mr_id,
            original_path,
            archived_path,
            sha256,
            file_size,
            file_mtime,
            parser_version,
            parse_status,
            first_sample_time,
            last_sample_time,
            lines_read,
            records_parsed,
            records_skipped,
            duplicate_records,
            issue_count,
            error_message,
            records,
            events,
            issues,
            analysis_params_json,
            raw_sha256=raw_sha256,
            content_sha256=content_sha256,
            profile_id=profile_id,
            linked_mr_id=linked_mr_id,
            first_log_timestamp=first_log_timestamp,
            last_log_timestamp=last_log_timestamp,
            log_date=log_date,
            daily_sequence=daily_sequence,
            rename_status=rename_status,
            rename_warning=rename_warning,
            source_status=source_status,
            source_type=source_type,
            source_device_id=source_device_id,
            parse_task_id=parse_task_id,
        )
        detail_repo.rebuild_derived_analysis()
        parsed_size = detail_path.stat().st_size if detail_path.exists() else 0
        with self._connect() as conn:
            conn.execute(
                "UPDATE source_files SET parsed_db_size = ?, db_schema_version = ? WHERE id = ?",
                (parsed_size, SCHEMA_VERSION, source_file_id),
            )
            self._update_meta_counts(conn)
        return source_file_id

    def _insert_file_result_current_db(
        self,
        mr_id: str,
        original_path: Path,
        archived_path: Path,
        sha256: str,
        file_size: int,
        file_mtime: datetime | None,
        parser_version: str,
        parse_status: str,
        first_sample_time: datetime | None,
        last_sample_time: datetime | None,
        lines_read: int,
        records_parsed: int,
        records_skipped: int,
        duplicate_records: int,
        issue_count: int,
        error_message: str,
        records: list[MeshLogRecord],
        events: list[MeshSwitchEvent],
        issues: list[ParseIssue],
        analysis_params_json: str = "",
        *,
        raw_sha256: str = "",
        content_sha256: str = "",
        profile_id: str = "",
        linked_mr_id: str = "",
        first_log_timestamp: datetime | None = None,
        last_log_timestamp: datetime | None = None,
        log_date: str = "",
        daily_sequence: int | None = None,
        rename_status: str = "",
        rename_warning: str = "",
        source_status: str = "imported",
        source_type: str = "manual_upload",
        source_device_id: str = "",
        parse_task_id: str = "",
    ) -> int:
        issue_counts = summarize_parse_issues(issues)
        issue_count = issue_counts["total"]
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_files (
                    mr_id, original_path, archived_path, parsed_db_path, parsed_db_size, db_schema_version,
                    original_filename, archived_filename, sha256,
                    stored_filename, raw_sha256, content_sha256, profile_id, linked_mr_id,
                    file_size, file_mtime, imported_at, parser_version, parse_status, encoding, is_gzip,
                    first_sample_time, last_sample_time, lines_read, records_parsed, records_skipped,
                    first_log_timestamp, last_log_timestamp, log_date, daily_sequence,
                    rename_status, rename_warning, source_status, source_type, source_device_id, parse_task_id,
                    duplicate_records, issue_count, error_message, analysis_params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mr_id,
                    str(original_path),
                    str(archived_path),
                    "",
                    0,
                    SCHEMA_VERSION,
                    original_path.name,
                    archived_path.name,
                    sha256,
                    archived_path.name,
                    raw_sha256 or sha256,
                    content_sha256 or sha256,
                    profile_id or mr_id,
                    linked_mr_id,
                    file_size,
                    dt_text(file_mtime),
                    dt_text(datetime.now()),
                    parser_version,
                    parse_status,
                    "",
                    1 if archived_path.name.lower().endswith(".gz") else 0,
                    dt_text(first_sample_time),
                    dt_text(last_sample_time),
                    lines_read,
                    records_parsed,
                    records_skipped,
                    dt_text(first_log_timestamp or first_sample_time),
                    dt_text(last_log_timestamp or last_sample_time),
                    log_date or ((first_log_timestamp or first_sample_time).date().isoformat() if first_log_timestamp or first_sample_time else None),
                    daily_sequence,
                    rename_status,
                    rename_warning,
                    source_status,
                    source_type,
                    source_device_id,
                    parse_task_id,
                    duplicate_records,
                    issue_count,
                    error_message,
                    analysis_params_json,
                ),
            )
            source_file_id = int(cursor.lastrowid)
            conn.execute(
                "UPDATE source_files SET info_count = ?, warning_count = ?, error_count = ?, issue_severity_version = 1 WHERE id = ?",
                (
                    issue_counts["info"],
                    issue_counts["warning"],
                    issue_counts["error"],
                    source_file_id,
                ),
            )
            file_order = min((int(record.source_file_order or 0) for record in records if int(record.source_file_order or 0) > 0), default=source_file_id)
            conn.execute("UPDATE source_files SET source_file_order = ? WHERE id = ?", (file_order, source_file_id))
            sample_rows = {}
            for record in records:
                sample_rows[(source_file_id, record.radio, dt_text(record.sample_time) or "", record.timestamp_tag or "")] = (
                    source_file_id,
                    record.radio,
                    dt_text(record.sample_time),
                    None,
                    record.sample_time_epoch_ms or int(record.sample_time.timestamp() * 1000),
                    record.timestamp_tag or "",
                    record.raw_line_start or record.source_line_number,
                    record.raw_line_end or record.source_line_number,
                    record.raw_offset_start,
                    record.raw_offset_end,
                )
            conn.executemany(
                """
                INSERT OR IGNORE INTO samples(
                    source_file_id, radio, sample_time, device_time, sample_time_epoch_ms, timestamp_tag,
                    raw_line_start, raw_line_end, raw_offset_start, raw_offset_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                list(sample_rows.values()),
            )
            sample_ids: dict[tuple[int, int, str, str], int] = {}
            keys = list(sample_rows)
            for start in range(0, len(keys), 400):
                chunk = keys[start : start + 400]
                rows = conn.execute(
                    f"SELECT id, source_file_id, radio, sample_time, timestamp_tag FROM samples WHERE {' OR '.join('(source_file_id = ? AND radio = ? AND sample_time = ? AND timestamp_tag = ?)' for _ in chunk)}",
                    [value for key in chunk for value in key],
                ).fetchall()
                sample_ids.update(
                    {
                        (int(row["source_file_id"]), int(row["radio"]), row["sample_time"], row["timestamp_tag"]): int(row["id"])
                        for row in rows
                    }
                )
            link_rows = []
            for record in records:
                sample_time = dt_text(record.sample_time)
                record.sample_id = sample_ids.get((source_file_id, record.radio, sample_time, record.timestamp_tag or ""))
                record.source_file_id = source_file_id
                record.source_file_order = int(record.source_file_order or file_order)
                link_rows.append(
                    (
                        record.sample_id,
                        source_file_id,
                        record.source_file_order,
                        int(record.record_seq or record.source_line_number),
                        record.source_line_number,
                        record.radio,
                        sample_time,
                        record.raw_line_start or record.source_line_number,
                        record.raw_line_end or record.source_line_number,
                        record.raw_offset_start,
                        record.raw_offset_end,
                        record.link_state_raw,
                        record.link_state,
                        record.peer_mac_raw,
                        normalize_mac_key(record.peer_mac_normalized),
                        record.peer_mac_normalized or "",
                        "",
                        "",
                        "",
                        None,
                        "",
                        "",
                        "",
                        "",
                        "unresolved",
                        dt_text(record.establish_time),
                        record.duration_text,
                        record.duration_seconds,
                        record.expected_duration_seconds,
                        record.duration_deviation_seconds,
                        record.link_count,
                        record.session_id,
                        *[record.metrics.get(column) for column in _METRIC_COLUMNS],
                        record.local_noise_dbm,
                        record.peer_noise_dbm,
                        record.local_signal_dbm,
                        record.peer_signal_dbm,
                        f"{source_file_id}:{record.duplicate_hash}",
                    )
                )
            if link_rows:
                placeholders = ", ".join("?" for _ in range(len(link_rows[0])))
                conn.executemany(
                    f"""
                INSERT OR IGNORE INTO mesh_links (
                    sample_id, source_file_id, source_file_order, record_seq, source_line_number, radio, sample_time,
                    raw_line_start, raw_line_end, raw_offset_start, raw_offset_end,
                    link_state_raw, link_state, peer_mac_raw, peer_mac_normalized,
                    peer_mac, peer_ap_name, peer_ap_mac, peer_site, peer_radio_id, peer_radio, peer_radio_label, peer_match_rule,
                    peer_radio_mac, peer_resolve_source, establish_time,
                    duration_text, duration_seconds, expected_duration_seconds, duration_deviation_seconds,
                    link_count, session_id, local_rssi_db, peer_rssi_db, local_cpu_percent, peer_cpu_percent,
                    local_mem_percent, peer_mem_percent, local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy,
                    local_rate_raw, peer_rate_raw, local_noise_raw, peer_noise_raw, local_tx_des_free_cnt, peer_tx_des_free_cnt,
                    local_tx, peer_tx, local_rx, peer_rx, local_retry, peer_retry, local_err, peer_err,
                    local_tx_garp, peer_rx_garp, local_tx_mul_join, peer_rx_mul_join, local_noise_dbm, peer_noise_dbm,
                    local_signal_dbm, peer_signal_dbm, record_fingerprint
                ) VALUES ({placeholders})
                """,
                    link_rows,
                )
            self._insert_issues(conn, source_file_id, issues)
            return source_file_id

    def list_source_files(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM source_files ORDER BY COALESCE(first_sample_time, imported_at) ASC, id ASC").fetchall()
        return [self._source_file_row_status(dict(row)) for row in rows]

    def query_source_files(self, limit: int, offset: int) -> tuple[int, list[dict[str, object]]]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] or 0)
            rows = conn.execute(
                """
                SELECT * FROM source_files
                ORDER BY COALESCE(first_sample_time, imported_at) ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
        return total, [self._source_file_row_status(dict(row)) for row in rows]

    def _source_file_row_status(self, data: dict[str, object]) -> dict[str, object]:
        deleted = bool(str(data.get("deleted_at") or ""))
        parsed_deleted = bool(str(data.get("parsed_deleted_at") or ""))
        file_status = str(data.get("file_status") or "").strip()
        exists = bool(int(data.get("file_exists") or 0)) and not deleted
        if str(data.get("delete_error") or ""):
            data["file_status"] = "delete_failed"
        elif deleted and parsed_deleted:
            data["file_status"] = "all_deleted"
        elif parsed_deleted or file_status == "parsed_deleted":
            data["file_status"] = "parsed_deleted"
        elif deleted or file_status == "deleted":
            data["file_status"] = "deleted"
        elif exists:
            data["file_status"] = "ok"
        else:
            data["file_status"] = "missing"
        data["file_exists"] = 1 if exists else 0
        return data

    def get_source_file(self, source_file_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
        return dict(row) if row else None

    def update_source_provenance(
        self,
        source_file_id: int,
        *,
        raw_relative_path: str,
        parsed_relative_path: str,
        archive_sha256: str = "",
        bundle_member_id: str = "",
        bundle_member_sha256: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE source_files
                SET raw_relative_path = ?, parsed_relative_path = ?, archive_sha256 = ?,
                    bundle_member_id = ?, bundle_member_sha256 = ?
                WHERE id = ?
                """,
                (
                    raw_relative_path,
                    parsed_relative_path,
                    archive_sha256,
                    bundle_member_id,
                    bundle_member_sha256,
                    int(source_file_id),
                ),
            )

    def mark_source_file_deleted(self, source_file_id: int, deleted_at: datetime | None = None) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT parsed_deleted_at FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
            status = "all_deleted" if row and str(row["parsed_deleted_at"] or "") else "deleted"
            conn.execute(
                "UPDATE source_files SET file_exists = 0, deleted_at = ?, delete_error = '', file_status = ? WHERE id = ?",
                (dt_text(deleted_at or datetime.now()), status, source_file_id),
            )

    def mark_source_file_missing(self, source_file_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE source_files SET file_exists = 0, file_status = 'missing' WHERE id = ?", (source_file_id,))

    def mark_source_file_delete_failed(self, source_file_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE source_files SET delete_error = ?, file_status = 'delete_failed' WHERE id = ?", (str(error), source_file_id))

    def count_parsed_data_by_source_file(self, source_file_id: int | str) -> dict[str, int]:
        if source_file_id in (None, ""):
            return {"links": 0, "events": 0, "issues": 0, "caches": 0}
        if self._is_index_database():
            repo = self._detail_repo_for_source(source_file_id)
            return repo.count_parsed_data_by_source_file(1) if repo else {"links": 0, "events": 0, "issues": 0, "caches": 0}
        value = int(source_file_id)
        with self._connect() as conn:
            links = int(conn.execute("SELECT COUNT(*) AS count FROM mesh_links WHERE source_file_id = ?", (value,)).fetchone()["count"])
            events = int(conn.execute("SELECT COUNT(*) AS count FROM switch_events WHERE source_file_id = ?", (value,)).fetchone()["count"])
            issues = int(conn.execute("SELECT COUNT(*) AS count FROM parse_issues WHERE source_file_id = ?", (value,)).fetchone()["count"])
        return {"links": links, "events": events, "issues": issues, "caches": 0}

    def delete_parsed_data_by_source_file(self, source_file_id: int | str) -> DeleteParsedDataResult:
        if source_file_id in (None, ""):
            return DeleteParsedDataResult(False, "", message="source_file_id 为空，拒绝删除解析数据")
        value = int(source_file_id)
        if self._is_index_database():
            now = dt_text(datetime.now()) or ""
            with self._connect() as conn:
                row = conn.execute("SELECT parsed_db_path, deleted_at FROM source_files WHERE id = ?", (value,)).fetchone()
                if row is None:
                    return DeleteParsedDataResult(False, str(value), message="源文件记录不存在，无法删除解析数据")
                status = "all_deleted" if str(row["deleted_at"] or "") else "parsed_deleted"
                parsed_db_path = Path(str(row["parsed_db_path"] or "").strip().strip("'\""))
                counts = {"links": 0, "events": 0, "issues": 0, "caches": 0}
                if parsed_db_path.exists():
                    detail_conn: sqlite3.Connection | None = None
                    try:
                        detail_conn = sqlite3.connect(parsed_db_path)
                        counts = {
                            "links": int(detail_conn.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0]),
                            "events": int(detail_conn.execute("SELECT COUNT(*) FROM switch_events").fetchone()[0]),
                            "issues": int(detail_conn.execute("SELECT COUNT(*) FROM parse_issues").fetchone()[0]),
                            "caches": 0,
                        }
                    finally:
                        if detail_conn is not None:
                            detail_conn.close()
                try:
                    gc.collect()
                    if parsed_db_path.exists():
                        parsed_db_path.unlink()
                    for suffix in ("-wal", "-shm"):
                        sidecar = parsed_db_path.with_name(parsed_db_path.name + suffix)
                        if sidecar.exists():
                            sidecar.unlink()
                    conn.execute(
                        """
                        UPDATE source_files
                        SET file_status = ?, parsed_deleted_at = ?, parsed_delete_error = '', parsed_db_size = 0
                        WHERE id = ?
                        """,
                        (status, now, value),
                    )
                    self._update_meta_counts(conn)
                except Exception as exc:
                    conn.execute(
                        "UPDATE source_files SET parsed_delete_error = ?, file_status = 'delete_failed' WHERE id = ?",
                        (str(exc), value),
                    )
                    return DeleteParsedDataResult(False, str(value), message=str(exc))
            return DeleteParsedDataResult(True, str(value), deleted_links=counts["links"], deleted_events=counts["events"], deleted_issues=counts["issues"], message="解析数据已删除")
        counts = self.count_parsed_data_by_source_file(value)
        now = dt_text(datetime.now()) or ""
        with self._connect() as conn:
            row = conn.execute("SELECT deleted_at FROM source_files WHERE id = ?", (value,)).fetchone()
            if row is None:
                return DeleteParsedDataResult(False, str(value), message="源文件记录不存在，无法删除解析数据")
            status = "all_deleted" if str(row["deleted_at"] or "") else "parsed_deleted"
            try:
                conn.execute("BEGIN")
                conn.execute("DELETE FROM mesh_links WHERE source_file_id = ?", (value,))
                conn.execute("DELETE FROM switch_events WHERE source_file_id = ?", (value,))
                conn.execute("DELETE FROM parse_issues WHERE source_file_id = ?", (value,))
                conn.execute(
                    """
                    DELETE FROM samples
                    WHERE source_file_id = ?
                      AND NOT EXISTS (SELECT 1 FROM mesh_links WHERE mesh_links.sample_id = samples.id)
                    """,
                    (value,),
                )
                conn.execute("DELETE FROM mesh_sessions")
                conn.execute("DELETE FROM switch_events")
                conn.execute("DELETE FROM active_points")
                conn.execute("DELETE FROM active_segments")
                conn.execute("DELETE FROM rssi_stats")
                conn.execute("DELETE FROM diagnosis_events")
                self._rebuild_sessions_and_deltas(conn, None, None, 1000)
                self._rebuild_active_events(conn, None, None, 1000)
                self._rebuild_active_points_segments_stats(conn, None)
                conn.execute(
                    """
                    UPDATE source_files
                    SET file_status = ?,
                        parsed_deleted_at = ?,
                        parsed_delete_error = ''
                    WHERE id = ?
                    """,
                    (status, now, value),
                )
                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK")
                conn.execute(
                    "UPDATE source_files SET parsed_delete_error = ?, file_status = 'delete_failed' WHERE id = ?",
                    (str(exc), value),
                )
                return DeleteParsedDataResult(False, str(value), message=str(exc))
        return DeleteParsedDataResult(
            True,
            str(value),
            deleted_links=counts["links"],
            deleted_events=counts["events"],
            deleted_issues=counts["issues"],
            deleted_caches=counts["caches"],
            message="解析数据已删除",
        )

    def query_links(self, limit: int, offset: int, filters: dict[str, object] | None = None) -> tuple[int, list[dict[str, object]]]:
        filters = filters or {}
        if self._is_index_database():
            source_file_id = filters.get("source_file_id")
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return 0, []
                delegated = dict(filters)
                delegated.pop("source_file_id", None)
                total, rows = repo.query_links(limit, offset, delegated)
                for row in rows:
                    row["source_file_id"] = int(source_file_id)
                return total, rows
            total = 0
            combined: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                repo_total, repo_rows = repo.query_links(limit + offset, 0, filters)
                total += repo_total
                for row in repo_rows:
                    row["source_file_id"] = source_id
                combined.extend(repo_rows)
            combined.sort(key=lambda row: (int(row.get("source_file_order") or 0), int(row.get("record_seq") or 0), int(row.get("source_line_number") or 0), int(row.get("id") or 0)))
            return total, combined[offset : offset + limit]
        clauses: list[str] = []
        values: list[object] = []
        if filters.get("source_file_id") not in (None, ""):
            clauses.append("ml.source_file_id = ?")
            values.append(int(filters["source_file_id"]))
        if filters.get("radio") is not None:
            clauses.append("ml.radio = ?")
            values.append(filters["radio"])
        if filters.get("state"):
            clauses.append("ml.link_state = ?")
            values.append(filters["state"])
        if filters.get("peer"):
            clauses.append("(ml.peer_mac_normalized LIKE ? OR ml.peer_mac_raw LIKE ? OR ml.peer_mac LIKE ? OR ml.peer_ap_name LIKE ? OR ml.peer_site LIKE ?)")
            raw_peer = str(filters["peer"])
            normalized_peer = "".join(character for character in raw_peer.lower() if character in "0123456789abcdef")
            peer = f"%{raw_peer}%"
            values.extend([f"%{normalized_peer or raw_peer}%", peer, peer, peer, peer])
        if filters.get("keyword"):
            clauses.append("(ml.peer_mac_raw LIKE ? OR ml.peer_ap_name LIKE ? OR ml.peer_site LIKE ? OR ml.link_state_raw LIKE ? OR ml.duration_text LIKE ?)")
            keyword = f"%{filters['keyword']}%"
            values.extend([keyword, keyword, keyword, keyword, keyword])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM mesh_links ml{where}", values).fetchone()["count"]
            rows = conn.execute(
                f"""
                SELECT ml.*, s.timestamp_tag, sf.archived_filename, sf.archived_path
                FROM mesh_links ml
                LEFT JOIN samples s ON s.id = ml.sample_id
                LEFT JOIN source_files sf ON sf.id = ml.source_file_id
                {where}
                ORDER BY ml.source_file_order ASC, ml.record_seq ASC, ml.source_line_number ASC, ml.id ASC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        result: list[dict[str, object]] = []
        group_indexes: dict[tuple[object, object, object], int] = {}
        for row in rows:
            data = _with_synthetic_payload(row)
            key = (data.get("source_file_id"), data.get("sample_id"), data.get("radio"))
            if key not in group_indexes:
                group_indexes[key] = len(group_indexes)
            data["sample_group_index"] = group_indexes[key]
            result.append(data)
        return int(total), result

    def count_link_details(self, filters: dict[str, object] | None = None) -> int:
        filters = dict(filters or {})
        if self._is_index_database():
            source_file_id = filters.get("source_file_id")
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return 0
                filters.pop("source_file_id", None)
                return repo.count_link_details(filters)
            total = 0
            for _source_id, repo in self._detail_repo_items():
                total += repo.count_link_details(filters)
            return total
        total, _rows = self.query_links(1, 0, filters)
        return int(total)

    def iter_link_details(self, filters: dict[str, object] | None = None, batch_size: int = 2000):
        filters = dict(filters or {})
        batch_size = max(1, int(batch_size or 2000))
        if self._is_index_database():
            source_file_id = filters.get("source_file_id")
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return
                filters.pop("source_file_id", None)
                for row in repo.iter_link_details(filters, batch_size):
                    row["source_file_id"] = int(source_file_id)
                    yield row
                return
            for source_id, repo in self._detail_repo_items():
                for row in repo.iter_link_details(filters, batch_size):
                    row["source_file_id"] = source_id
                    yield row
            return
        cursor_order: tuple[int, int, int, int] | None = None
        group_indexes: dict[tuple[object, object, object], int] = {}
        while True:
            clauses, values = self._link_filter_clauses(filters)
            if cursor_order is not None:
                source_order, record_seq, source_line_number, link_id = cursor_order
                clauses.append(
                    "("
                    "ml.source_file_order > ? OR "
                    "(ml.source_file_order = ? AND ml.record_seq > ?) OR "
                    "(ml.source_file_order = ? AND ml.record_seq = ? AND ml.source_line_number > ?) OR "
                    "(ml.source_file_order = ? AND ml.record_seq = ? AND ml.source_line_number = ? AND ml.id > ?)"
                    ")"
                )
                values.extend([
                    source_order,
                    source_order,
                    record_seq,
                    source_order,
                    record_seq,
                    source_line_number,
                    source_order,
                    record_seq,
                    source_line_number,
                    link_id,
                ])
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT ml.*, s.timestamp_tag, sf.archived_filename, sf.archived_path
                    FROM mesh_links ml
                    LEFT JOIN samples s ON s.id = ml.sample_id
                    LEFT JOIN source_files sf ON sf.id = ml.source_file_id
                    {where}
                    ORDER BY ml.source_file_order ASC, ml.record_seq ASC, ml.source_line_number ASC, ml.id ASC
                    LIMIT ?
                    """,
                    [*values, batch_size],
                ).fetchall()
            if not rows:
                break
            for row in rows:
                data = _with_synthetic_payload(row)
                key = (data.get("source_file_id"), data.get("sample_id"), data.get("radio"))
                if key not in group_indexes:
                    group_indexes[key] = len(group_indexes)
                data["sample_group_index"] = group_indexes[key]
                yield data
            if len(rows) < batch_size:
                break
            last_row = rows[-1]
            cursor_order = (
                int(last_row["source_file_order"] or 0),
                int(last_row["record_seq"] or 0),
                int(last_row["source_line_number"] or 0),
                int(last_row["id"] or 0),
            )

    def find_sample_row_position(
        self,
        session_id: str,
        sample_time: str,
        peer_mac: str | None,
        radio: str | int | None,
        state: str | None,
        filters: dict[str, object] | None = None,
        page_size: int = 1000,
    ) -> RowPosition | None:
        target = self._find_target_link_id(session_id, sample_time, peer_mac, radio, state)
        for candidate in (
            (session_id, sample_time, peer_mac, radio, None),
            (session_id, sample_time, peer_mac, None, state),
            (session_id, sample_time, peer_mac, None, None),
            (session_id, sample_time, None, radio, state),
            (session_id, sample_time, None, None, None),
            ("", sample_time, peer_mac, radio, state),
            ("", sample_time, peer_mac, None, None),
        ):
            if target is not None:
                break
            target = self._find_target_link_id(*candidate)
        if target is None:
            return None
        clauses, values = self._link_filter_clauses(filters or {})
        target_clause = "ml.id = ?"
        before_clause = "(ml.sample_time < ? OR (ml.sample_time = ? AND ml.radio < ?) OR (ml.sample_time = ? AND ml.radio = ? AND ml.id < ?))"
        with self._connect() as conn:
            target_row = conn.execute("SELECT sample_time, radio, id FROM mesh_links WHERE id = ?", (target,)).fetchone()
            if target_row is None:
                return None
            filtered_target = conn.execute(
                f"SELECT 1 FROM mesh_links ml{' WHERE ' + ' AND '.join([*clauses, target_clause]) if clauses else ' WHERE ' + target_clause}",
                [*values, target],
            ).fetchone()
            if filtered_target is None:
                return None
            total = int(conn.execute(f"SELECT COUNT(*) AS count FROM mesh_links ml{' WHERE ' + ' AND '.join(clauses) if clauses else ''}", values).fetchone()["count"])
            before_values = [
                target_row["sample_time"],
                target_row["sample_time"],
                target_row["radio"],
                target_row["sample_time"],
                target_row["radio"],
                target_row["id"],
            ]
            where = " WHERE " + " AND ".join([*clauses, before_clause]) if clauses else " WHERE " + before_clause
            row_index = int(conn.execute(f"SELECT COUNT(*) AS count FROM mesh_links ml{where}", [*values, *before_values]).fetchone()["count"])
        effective_page_size = max(1, int(page_size or 1000))
        return RowPosition(row_index=row_index, page_no=row_index // effective_page_size + 1, index_in_page=row_index % effective_page_size, link_id=int(target), total=total, page_size=effective_page_size)

    def find_link_detail_row_position(
        self,
        session_id: str,
        sample_time: str,
        peer_mac: str | None,
        radio: str | int | None,
        state: str | None,
        page_size: int,
        filters: dict[str, object] | None = None,
    ) -> RowPosition | None:
        return self.find_sample_row_position(session_id, sample_time, peer_mac, radio, state, filters, page_size)

    def _find_target_link_id(self, session_id: str, sample_time: str, peer_mac: str | None, radio: str | int | None, state: str | None) -> int | None:
        clauses = ["sample_time = ?"]
        values: list[object] = [sample_time]
        if session_id:
            clauses.append("session_id = ?")
            values.append(session_id)
        if peer_mac:
            peer = _canonical_mac(peer_mac)
            clauses.append("(peer_mac_normalized = ? OR peer_mac = ? OR peer_mac_raw = ?)")
            values.extend([peer, peer, peer_mac])
        if radio not in (None, ""):
            try:
                clauses.append("radio = ?")
                values.append(int(radio))
            except (TypeError, ValueError):
                pass
        if state:
            clauses.append("link_state = ?")
            values.append(str(state).upper())
        with self._connect() as conn:
            row = conn.execute(f"SELECT id FROM mesh_links WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT 1", values).fetchone()
        return int(row["id"]) if row else None

    def _link_filter_clauses(self, filters: dict[str, object]) -> tuple[list[str], list[object]]:
        clauses: list[str] = []
        values: list[object] = []
        if filters.get("source_file_id") not in (None, ""):
            clauses.append("ml.source_file_id = ?")
            values.append(int(filters["source_file_id"]))
        if filters.get("radio") is not None:
            clauses.append("ml.radio = ?")
            values.append(filters["radio"])
        if filters.get("state"):
            clauses.append("ml.link_state = ?")
            values.append(filters["state"])
        if filters.get("peer"):
            clauses.append("(ml.peer_mac_normalized LIKE ? OR ml.peer_mac_raw LIKE ? OR ml.peer_mac LIKE ? OR ml.peer_ap_name LIKE ? OR ml.peer_site LIKE ?)")
            raw_peer = str(filters["peer"])
            normalized_peer = "".join(character for character in raw_peer.lower() if character in "0123456789abcdef")
            peer = f"%{raw_peer}%"
            values.extend([f"%{normalized_peer or raw_peer}%", peer, peer, peer, peer])
        if filters.get("keyword"):
            clauses.append("(ml.peer_mac_raw LIKE ? OR ml.peer_ap_name LIKE ? OR ml.peer_site LIKE ? OR ml.link_state_raw LIKE ? OR ml.duration_text LIKE ?)")
            keyword = f"%{filters['keyword']}%"
            values.extend([keyword, keyword, keyword, keyword, keyword])
        return clauses, values

    def query_events(self, limit: int, offset: int, source_file_id: int | str | None = None) -> tuple[int, list[dict[str, object]]]:
        if self._is_index_database():
            detail_items = self._detail_repo_items()
            if not detail_items and source_file_id in (None, ""):
                pass
            else:
                if source_file_id not in (None, ""):
                    repo = self._detail_repo_for_source(source_file_id)
                    if repo is None:
                        return 0, []
                    total, rows = repo.query_events(limit, offset, None)
                    for row in rows:
                        row["source_file_id"] = int(source_file_id)
                    return total, rows
                total = 0
                combined: list[dict[str, object]] = []
                for source_id, repo in detail_items:
                    repo_total, repo_rows = repo.query_events(limit + offset, 0, None)
                    total += repo_total
                    for row in repo_rows:
                        row["source_file_id"] = source_id
                    combined.extend(repo_rows)
                combined.sort(key=lambda row: (str(row.get("event_time") or ""), int(row.get("id") or 0)))
                return total, combined[offset : offset + limit]
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("source_file_id = ?")
            values.append(int(source_file_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM switch_events{where}", values).fetchone()["count"]
            rows = conn.execute(f"SELECT * FROM switch_events{where} ORDER BY event_time ASC, id ASC LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        return int(total), [dict(row) for row in rows]

    def query_issues(self, limit: int, offset: int, source_file_id: int | str | None = None) -> tuple[int, list[dict[str, object]]]:
        if self._is_index_database():
            detail_items = self._detail_repo_items()
            if not detail_items and source_file_id in (None, ""):
                pass
            else:
                if source_file_id not in (None, ""):
                    repo = self._detail_repo_for_source(source_file_id)
                    if repo is None:
                        return 0, []
                    total, rows = repo.query_issues(limit, offset, None)
                    for row in rows:
                        row["source_file_id"] = int(source_file_id)
                    return total, rows
                total = 0
                combined: list[dict[str, object]] = []
                for source_id, repo in detail_items:
                    repo_total, repo_rows = repo.query_issues(limit + offset, 0, None)
                    total += repo_total
                    for row in repo_rows:
                        row["source_file_id"] = source_id
                    combined.extend(repo_rows)
                combined.sort(key=lambda row: (str(row.get("source_file") or ""), int(row.get("line_number") or 0), int(row.get("id") or 0)))
                return total, combined[offset : offset + limit]
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("source_file_id = ?")
            values.append(int(source_file_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM parse_issues{where}", values).fetchone()["count"]
            rows = conn.execute(f"SELECT * FROM parse_issues{where} ORDER BY source_file ASC, line_number ASC, id ASC LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        return int(total), [dict(row) for row in rows]

    def get_link_by_id(self, link_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mesh_links WHERE id = ?", (link_id,)).fetchone()
        return dict(row) if row else None

    def query_peer_context_segment(self, anchor_link_id: int) -> dict[str, object]:
        if self._is_index_database():
            for repo in self._detail_repos():
                payload = repo.query_peer_context_segment(anchor_link_id)
                if payload.get("anchor") is not None:
                    return payload
            return _segment_payload(None, [], None, None)
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id)
        if anchor is None or start_time is None or end_time is None:
            return _segment_payload(anchor, [], interval, gap)
        clauses = ["peer_mac_normalized = ?", "radio = ?"]
        values: list[object] = [anchor.get("peer_mac_normalized"), anchor.get("radio")]
        if anchor.get("session_id"):
            clauses.append("session_id = ?")
            values.append(anchor.get("session_id"))
        clauses.append("sample_time >= ?")
        clauses.append("sample_time <= ?")
        values.extend([start_time, end_time])
        with self._connect() as conn:
            rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"SELECT * FROM mesh_links WHERE {' AND '.join(clauses)} ORDER BY sample_time ASC, id ASC",
                    values,
                ).fetchall()
            ]
        return _segment_payload(anchor, rows, interval, gap)

    def query_run_context_segment(self, anchor_link_id: int) -> dict[str, object]:
        if self._is_index_database():
            for repo in self._detail_repos():
                payload = repo.query_run_context_segment(anchor_link_id)
                if payload.get("anchor") is not None:
                    return payload
            payload = _segment_payload(None, [], None, None)
            payload["events"] = []
            return payload
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id)
        if anchor is None or start_time is None or end_time is None:
            payload = _segment_payload(None, [], None, None)
            payload["events"] = []
            return payload
        with self._connect() as conn:
            chart_columns = _mesh_link_chart_columns(conn)
            rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"""
                    SELECT {chart_columns}
                    FROM mesh_links
                    WHERE radio = ? AND sample_time >= ? AND sample_time <= ? AND (? IS NULL OR session_id = ?)
                    ORDER BY sample_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time, anchor.get("session_id"), anchor.get("session_id")),
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT {_MESH_EVENT_CHART_COLUMNS}
                    FROM switch_events
                    WHERE radio = ? AND (? IS NULL OR event_time >= ?) AND (? IS NULL OR event_time <= ?)
                    ORDER BY event_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, start_time, end_time, end_time),
                ).fetchall()
            ]
        payload = _segment_payload(anchor, rows, interval, gap)
        payload["events"] = events
        return payload

    def query_peer_chart_segments(self, anchor_link_id: int, source_file_id: int | str | None = None) -> dict[str, object]:
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                return repo.query_peer_chart_segments(anchor_link_id, None) if repo else {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
            return _empty_peer_chart_payload("index database peer chart requires source_file_id because mesh_links.id is local to each parsed database")
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id, source_file_id=source_file_id)
        if anchor is None or start_time is None or end_time is None:
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, [], interval, gap), "run_segment": _segment_payload(anchor, [], interval, gap)}
        return self._query_peer_chart_segments_in_range(anchor, start_time, end_time, interval, gap, partial=False, full_loading=False, source_file_id=source_file_id)

    @staticmethod
    def _budgeted_event_rows(
        conn: sqlite3.Connection,
        *,
        where: str,
        values: list[object],
        max_events: int,
    ) -> tuple[list[dict[str, object]], int]:
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM switch_events {where}", values).fetchone()[0]
            or 0
        )
        if total == 0 or max_events <= 0:
            return [], total
        if total <= max_events:
            rows = conn.execute(
                f"""
                SELECT {_MESH_EVENT_CHART_COLUMNS}
                FROM switch_events
                {where}
                ORDER BY radio ASC, event_time ASC, id ASC
                """,
                values,
            ).fetchall()
            return [dict(row) for row in rows], total
        stride = max(1, (total + max_events - 1) // max_events)
        rows = conn.execute(
            f"""
            WITH ordered AS (
                SELECT {_MESH_EVENT_CHART_COLUMNS},
                       ROW_NUMBER() OVER (ORDER BY radio ASC, event_time ASC, id ASC) AS row_no,
                       COUNT(*) OVER () AS total_rows
                FROM switch_events
                {where}
            )
            SELECT {_MESH_EVENT_CHART_COLUMNS}
            FROM ordered
            WHERE row_no = 1 OR row_no = total_rows OR ((row_no - 1) % ?) = 0
            ORDER BY radio ASC, event_time ASC, id ASC
            LIMIT ?
            """,
            (*values, stride, max_events),
        ).fetchall()
        return [dict(row) for row in rows], total

    @staticmethod
    def _budgeted_chart_rows(
        conn: sqlite3.Connection,
        *,
        chart_columns: str,
        where: str,
        values: list[object],
        order_by: str,
        max_rows: int,
        event_times: Iterable[str] = (),
        critical_sample_ids: Iterable[int] = (),
        critical_frame_row_limit: int = 32,
        frame_count: int = 0,
        max_frames: int = 0,
        known_totals: Mapping[str, object] | None = None,
    ) -> tuple[list[sqlite3.Row], dict[str, int | bool]]:
        aggregate: Mapping[str, object]
        if known_totals is not None:
            aggregate = known_totals
        else:
            aggregate = conn.execute(
                f"""
                SELECT COUNT(*) AS total_rows,
                       COUNT(DISTINCT sample_id) AS total_frames,
                       SUM(CASE WHEN link_state = ? THEN 1 ELSE 0 END) AS active_rows,
                       SUM(CASE WHEN link_state = ? THEN 1 ELSE 0 END) AS standby_rows,
                       MIN(id) AS min_id,
                       MAX(id) AS max_id,
                       MIN(sample_id) AS min_sample_id,
                       MAX(sample_id) AS max_sample_id
                FROM mesh_links
                {where}
                """,
                (LINK_STATE_ACTIVE, LINK_STATE_STANDBY, *values),
            ).fetchone()
        total_rows = int(aggregate["total_rows"] or 0)
        totals: dict[str, int | bool] = {
            "total_rows": total_rows,
            "total_frames": int(aggregate["total_frames"] or 0),
            "active_rows": int(aggregate["active_rows"] or 0),
            "standby_rows": int(aggregate["standby_rows"] or 0),
            "repository_downsampled": (
                total_rows > max_rows or (frame_count > 0 and max_frames > 0 and frame_count > max_frames)
            ),
        }
        if total_rows == 0 or max_rows <= 0:
            return [], totals
        preserve_frames = frame_count > 0 and max_frames > 0
        if total_rows <= max_rows and not (preserve_frames and frame_count > max_frames):
            return (
                conn.execute(
                    f"SELECT {chart_columns} FROM mesh_links {where} ORDER BY {order_by}",
                    values,
                ).fetchall(),
                totals,
            )

        normalized_event_times = sorted({str(value) for value in event_times if str(value)})
        normalized_critical_sample_ids = sorted({int(value) for value in critical_sample_ids})
        event_time_cte = (
            "VALUES " + ", ".join("(?)" for _ in normalized_event_times)
            if normalized_event_times
            else "SELECT NULL WHERE 0"
        )
        event_match = (
            "sample_time IN (SELECT value FROM event_times)"
            if normalized_event_times
            else "0"
        )
        critical_sample_match = (
            "sample_id IN (" + ", ".join(str(value) for value in normalized_critical_sample_ids) + ")"
            if normalized_critical_sample_ids
            else "0"
        )
        stride = max(
            1,
            (
                (frame_count + max_frames - 1) // max_frames
                if preserve_frames
                else (total_rows + max_rows - 1) // max_rows
            ),
        )
        min_id = int(aggregate["min_id"] or 0)
        max_id = int(aggregate["max_id"] or min_id)
        min_sample_id = int(aggregate["min_sample_id"] or 0)
        max_sample_id = int(aggregate["max_sample_id"] or min_sample_id)
        if preserve_frames:
            frame_condition = (
                "(sample_id = ? OR sample_id = ? OR ((sample_id - ?) % ?) = 0 "
                f"OR {event_match} OR {critical_sample_match})"
            )
            sampled_where = (
                f"{where} AND {frame_condition}"
                if where
                else f"WHERE {frame_condition}"
            )
            selected_ids_sql = f"""
            WITH event_times(value) AS ({event_time_cte}),
            sampled AS (
                SELECT id, sample_id, sample_time, link_state,
                       CASE
                            WHEN sample_id = {min_sample_id} OR sample_id = {max_sample_id} THEN 0
                            WHEN {event_match} OR {critical_sample_match} THEN 1
                           ELSE 2
                       END AS priority
                FROM mesh_links
                {sampled_where}
            ),
            ranked AS (
                SELECT id, sample_time, priority,
                       ROW_NUMBER() OVER (
                           PARTITION BY sample_id
                           ORDER BY CASE WHEN link_state = '{LINK_STATE_ACTIVE}' THEN 0 ELSE 1 END, id
                       ) AS frame_row_no
                FROM sampled
            )
            SELECT id
            FROM ranked
            WHERE frame_row_no <= ?
            ORDER BY priority ASC, sample_time ASC, id ASC
            LIMIT ?
            """
            parameters_list: list[object] = [
                *normalized_event_times,
                *values,
                min_sample_id,
                max_sample_id,
                min_sample_id,
                stride,
                max(1, critical_frame_row_limit),
                max_rows,
            ]
        else:
            row_stride = max(1, (max_id - min_id + 1 + max_rows - 1) // max_rows)
            row_condition = (
                "(id = ? OR id = ? OR ((id - ?) % ?) = 0 "
                f"OR {event_match})"
            )
            sampled_where = (
                f"{where} AND {row_condition}"
                if where
                else f"WHERE {row_condition}"
            )
            selected_ids_sql = f"""
            WITH event_times(value) AS ({event_time_cte}),
            candidates AS (
                SELECT id, sample_time,
                       CASE
                           WHEN id = {min_id} OR id = {max_id} THEN 0
                           WHEN {event_match} THEN 1
                           ELSE 2
                       END AS priority
                FROM mesh_links
                {sampled_where}
            )
            SELECT id
            FROM candidates
            ORDER BY priority ASC, sample_time ASC, id ASC
            LIMIT ?
            """
            parameters_list = [
                *normalized_event_times,
                *values,
                min_id,
                max_id,
                min_id,
                row_stride,
                max_rows,
            ]
        parameters = tuple(parameters_list)
        rows = conn.execute(
            f"""
            SELECT {chart_columns}
            FROM mesh_links
            WHERE id IN ({selected_ids_sql})
            ORDER BY {order_by}
            """,
            parameters,
        ).fetchall()
        totals["returned_rows"] = len(rows)
        return rows, totals

    @staticmethod
    def _trackside_boundary_sample_ids(
        conn: sqlite3.Connection,
        *,
        where: str,
        values: list[object],
        series_identity: str,
        display_gap_seconds: float,
    ) -> tuple[set[int], set[int]]:
        """Find first/last frames for every AP/Radio visit without loading link rows."""
        identity_where = (
            f"{where} AND {series_identity} IS NOT NULL"
            if where
            else f"WHERE {series_identity} IS NOT NULL"
        )
        rows = conn.execute(
            f"""
            WITH frame_series AS (
                SELECT source_file_id, radio, sample_id, sample_time,
                       {series_identity} AS series_key,
                       DENSE_RANK() OVER (
                           PARTITION BY source_file_id, radio
                           ORDER BY sample_time, sample_id
                       ) AS frame_no
                FROM mesh_links
                {identity_where}
                GROUP BY source_file_id, radio, sample_id, sample_time, series_key
            ), ordered AS (
                SELECT sample_id, sample_time, frame_no,
                       LAG(sample_id) OVER series_order AS previous_sample_id,
                       LAG(sample_time) OVER series_order AS previous_sample_time,
                       LAG(frame_no) OVER series_order AS previous_frame_no,
                       LEAD(frame_no) OVER series_order AS next_frame_no
                FROM frame_series
                WINDOW series_order AS (
                    PARTITION BY source_file_id, radio, series_key
                    ORDER BY frame_no, sample_id
                )
            )
            SELECT sample_id, sample_time, frame_no, previous_sample_id,
                   previous_sample_time, previous_frame_no
            FROM ordered
            WHERE previous_frame_no IS NULL
               OR frame_no > previous_frame_no + 1
               OR next_frame_no IS NULL
               OR next_frame_no > frame_no + 1
               OR (julianday(sample_time) - julianday(previous_sample_time)) * 86400.0 > ?
            """,
            (*values, display_gap_seconds),
        ).fetchall()
        boundary_ids = {
            int(value)
            for row in rows
            for value in (row["sample_id"], row["previous_sample_id"])
            if value is not None
        }
        break_ids = {
            int(row["sample_id"])
            for row in rows
            if row["previous_sample_time"] is not None
            and (
                (
                    row["previous_frame_no"] is not None
                    and int(row["frame_no"]) > int(row["previous_frame_no"]) + 1
                )
                or (
                    _seconds_between(
                        str(row["previous_sample_time"]),
                        str(row["sample_time"]),
                    )
                    > display_gap_seconds
                )
            )
        }
        return boundary_ids, break_ids

    def query_active_link_chart_segments(
        self,
        source_file_id: int | str | None = None,
        radio: int | None = None,
        time_from: str = "",
        time_to: str = "",
        max_rows: int = 50_000,
        max_events: int = 256,
    ) -> dict[str, object]:
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
                payload = repo.query_active_link_chart_segments(
                    None,
                    radio,
                    time_from,
                    time_to,
                    max_rows=max_rows,
                    max_events=max_events,
                )
                for segment_key in ("peer_segment", "run_segment"):
                    segment = payload.get(segment_key)
                    if isinstance(segment, dict):
                        for row in segment.get("rows") or []:
                            row["source_file_id"] = int(source_file_id)
                if isinstance(payload.get("anchor"), dict):
                    payload["anchor"]["source_file_id"] = int(source_file_id)
                return payload
            rows: list[dict[str, object]] = []
            events: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                payload = repo.query_active_link_chart_segments(
                    None,
                    radio,
                    time_from,
                    time_to,
                    max_rows=max_rows,
                    max_events=max_events,
                )
                run = dict(payload.get("run_segment") or {})
                detail_rows = list(run.get("rows") or [])
                for row in detail_rows:
                    row["source_file_id"] = source_id
                rows.extend(detail_rows)
                detail_events = list(run.get("events") or [])
                for row in detail_events:
                    row["source_file_id"] = source_id
                events.extend(detail_events)
            rows.sort(key=lambda row: (str(row.get("sample_time") or ""), int(row.get("radio") or 0), int(row.get("id") or 0)))
            interval, gap = _interval_and_threshold([str(row.get("sample_time") or "") for row in rows if row.get("sample_time")])
            anchor = rows[0] if rows else None
            run_segment = _segment_payload(anchor, rows, interval, gap)
            active_count = len([row for row in rows if row.get("link_state") == LINK_STATE_ACTIVE])
            peer_segment = _segment_payload(anchor, [], interval, gap)
            for segment in (peer_segment, run_segment):
                segment["partial"] = False
                segment["full_loading"] = False
                segment["full_active_payload"] = True
                segment["query_active_count"] = active_count
            run_segment["events"] = events
            return {"anchor": anchor, "peer_segment": peer_segment, "run_segment": run_segment}
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("radio = ?")
            values.append(int(radio))
        if time_from:
            clauses.append("sample_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("sample_time <= ?")
            values.append(time_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        event_clauses: list[str] = []
        event_values: list[object] = []
        if source_file_id not in (None, ""):
            event_clauses.append("source_file_id = ?")
            event_values.append(int(source_file_id))
        if radio is not None:
            event_clauses.append("radio = ?")
            event_values.append(int(radio))
        if time_from:
            event_clauses.append("event_time >= ?")
            event_values.append(time_from)
        if time_to:
            event_clauses.append("event_time <= ?")
            event_values.append(time_to)
        events_where = f"WHERE {' AND '.join(event_clauses)}" if event_clauses else ""
        with self._connect() as conn:
            chart_columns = _mesh_link_chart_columns(conn)
            events, total_events = self._budgeted_event_rows(
                conn,
                where=events_where,
                values=event_values,
                max_events=max(0, int(max_events)),
            )
            event_times = {
                str(value)
                for event in events
                for value in (
                    event.get("previous_sample_time"),
                    event.get("current_sample_time"),
                    event.get("event_time"),
                )
                if value
            }
            raw_rows, query_totals = self._budgeted_chart_rows(
                conn,
                chart_columns=chart_columns,
                where=where,
                values=values,
                order_by="radio ASC, sample_time ASC, id ASC",
                max_rows=max(2, int(max_rows)),
                event_times=event_times,
            )
            rows = [
                _with_synthetic_payload(row)
                for row in raw_rows
            ]
        active_rows = [row for row in rows if row.get("link_state") == LINK_STATE_ACTIVE]
        standby_rows = [row for row in rows if row.get("link_state") == LINK_STATE_STANDBY]
        active_count = len(active_rows)
        matched_backup_count = _count_exact_backup_matches(active_rows, standby_rows)
        app_logger.log_info(
            "MESH_ACTIVE_PATH_BACKUP_QUERY_DONE",
            f"active_count={active_count}, standby_count={len(standby_rows)}, matched_backup_count={matched_backup_count}",
        )
        rows = sorted(
            rows,
            key=lambda row: (
                str(row.get("sample_time") or ""),
                str(row.get("timestamp_tag") or ""),
                int(row.get("radio") or 0),
                str(row.get("link_state") or ""),
                int(row.get("id") or 0),
            ),
        )
        anchor = next((row for row in rows if row.get("link_state") == LINK_STATE_ACTIVE), rows[0] if rows else None)
        interval, gap = _interval_and_threshold([str(row.get("sample_time") or "") for row in rows if row.get("sample_time")])
        run_segment = _segment_payload(anchor, rows, interval, gap)
        run_segment.update(query_totals)
        run_segment["returned_rows"] = len(rows)
        run_segment["total_events"] = total_events
        run_segment["returned_events"] = len(events)
        run_segment["repository_row_budget"] = max(2, int(max_rows))
        run_segment["repository_event_budget"] = max(0, int(max_events))
        peer_segment = _segment_payload(anchor, [], interval, gap)
        for segment in (peer_segment, run_segment):
            segment["partial"] = False
            segment["full_loading"] = False
            segment["full_active_payload"] = True
            segment["query_active_count"] = active_count
        run_segment["events"] = events
        return {"anchor": anchor, "peer_segment": peer_segment, "run_segment": run_segment}

    def query_active_rssi_line(
        self,
        source_file_id: int | str | None = None,
        radio: int | None = None,
        time_from: str = "",
        time_to: str = "",
    ) -> dict[str, object]:
        if self._is_index_database():
            repo = self._detail_repo_for_source(source_file_id) if source_file_id not in (None, "") else None
            return repo.query_active_rssi_line(None, radio, time_from, time_to) if repo else {"rows": []}
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("s.source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("s.radio = ?")
            values.append(int(radio))
        if time_from:
            clauses.append("s.sample_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("s.sample_time <= ?")
            values.append(time_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT s.id AS sample_id, s.sample_time, s.timestamp_tag, s.radio,
                           ml.id AS active_link_id,
                           ml.local_rssi_db AS local_rssi
                    FROM samples s
                    LEFT JOIN mesh_links ml
                      ON ml.sample_id = s.id
                     AND ml.link_state = ?
                     AND COALESCE(ml.link_count, 1) > 0
                    {where}
                    ORDER BY s.sample_time, s.timestamp_tag, s.radio, s.id, ml.id
                    """,
                    (LINK_STATE_ACTIVE, *values),
                ).fetchall()
            ]
        timestamps = [
            str(group[0].get("sample_time") or "")
            for group in _group_rows_by_value(rows, "sample_id")
            if group and group[0].get("sample_time")
        ]
        interval, gap = _interval_and_threshold(timestamps)
        return {
            "rows": rows,
            "estimated_interval_seconds": interval,
            "continuity_gap_seconds": gap,
        }

    def query_trackside_link_chart_segment(
        self,
        source_file_id: int | str | None = None,
        radio: int | None = None,
        time_from: str = "",
        time_to: str = "",
        max_rows: int = 50_000,
        max_frames: int = 2_000,
        max_series: int = 256,
        max_events: int = 256,
    ) -> dict[str, object]:
        """只读轨旁链路 RSSI 标量行，不构造未消费的 synthetic metric payload。"""
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return {"run_segment": _segment_payload(None, [], None, None)}
                payload = repo.query_trackside_link_chart_segment(
                    None,
                    radio,
                    time_from,
                    time_to,
                    max_rows=max_rows,
                    max_frames=max_frames,
                    max_series=max_series,
                    max_events=max_events,
                )
                segment = dict(payload.get("run_segment") or {})
                for row in segment.get("rows") or []:
                    row["source_file_id"] = int(source_file_id)
                return {"run_segment": segment}
            rows: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                payload = repo.query_trackside_link_chart_segment(
                    None,
                    radio,
                    time_from,
                    time_to,
                    max_rows=max_rows,
                    max_frames=max_frames,
                    max_series=max_series,
                    max_events=max_events,
                )
                detail_rows = list(dict(payload.get("run_segment") or {}).get("rows") or [])
                for row in detail_rows:
                    row["source_file_id"] = source_id
                rows.extend(detail_rows)
            rows.sort(
                key=lambda row: (
                    str(row.get("sample_time") or ""),
                    str(row.get("timestamp_tag") or ""),
                    int(row.get("radio") or 0),
                    int(row.get("id") or 0),
                )
            )
        else:
            clauses: list[str] = []
            values: list[object] = []
            if source_file_id not in (None, ""):
                clauses.append("source_file_id = ?")
                values.append(int(source_file_id))
            if radio is not None:
                clauses.append("radio = ?")
                values.append(int(radio))
            if time_from:
                clauses.append("sample_time >= ?")
                values.append(time_from)
            if time_to:
                clauses.append("sample_time <= ?")
                values.append(time_to)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._connect() as conn:
                chart_columns = _mesh_link_chart_columns(conn)
                series_identity = (
                    "COALESCE(NULLIF(peer_radio_mac, ''), NULLIF(peer_ap_mac, ''), "
                    "NULLIF(peer_mac_normalized, ''), NULLIF(peer_mac, ''), "
                    "NULLIF(peer_mac_raw, ''), NULLIF(lower(trim(peer_ap_name)), ''))"
                )
                series_key = f"({series_identity} || ':' || COALESCE(CAST(radio AS TEXT), ''))"
                source_totals = conn.execute(
                    f"""
                    SELECT COUNT(*) AS total_rows,
                           COUNT(DISTINCT sample_id) AS total_frames,
                           SUM(CASE WHEN link_state = ? THEN 1 ELSE 0 END) AS active_rows,
                           SUM(CASE WHEN link_state = ? THEN 1 ELSE 0 END) AS standby_rows,
                           SUM(CASE WHEN link_count = 2 THEN 1 ELSE 0 END) AS triangle_rows,
                           COUNT(DISTINCT {series_key}) AS total_series,
                           MIN(id) AS min_id,
                           MAX(id) AS max_id,
                           MIN(sample_id) AS min_sample_id,
                           MAX(sample_id) AS max_sample_id
                    FROM mesh_links
                    {where}
                    """,
                    (LINK_STATE_ACTIVE, LINK_STATE_STANDBY, *values),
                ).fetchone()
                total_series = int(source_totals["total_series"] or 0)
                selected_series: list[str] = []
                bounded_series = max(1, int(max_series))
                if total_series > bounded_series:
                    series_where = (
                        f"{where} AND {series_identity} IS NOT NULL"
                        if where
                        else f"WHERE {series_identity} IS NOT NULL"
                    )
                    selected_series = [
                        str(row["series_key"])
                        for row in conn.execute(
                            f"""
                            SELECT {series_key} AS series_key
                            FROM mesh_links
                            {series_where}
                            GROUP BY series_key
                            ORDER BY MAX(CASE WHEN link_state = ? THEN 1 ELSE 0 END) DESC,
                                     MIN(sample_time) ASC,
                                     series_key ASC
                            LIMIT ?
                            """,
                            (*values, LINK_STATE_ACTIVE, bounded_series),
                        ).fetchall()
                    ]
                    placeholders = ", ".join("?" for _ in selected_series)
                    clauses.append(f"{series_key} IN ({placeholders})")
                    values.extend(selected_series)
                    where = f"WHERE {' AND '.join(clauses)}"

                event_clauses: list[str] = []
                event_values: list[object] = []
                if source_file_id not in (None, ""):
                    event_clauses.append("source_file_id = ?")
                    event_values.append(int(source_file_id))
                if radio is not None:
                    event_clauses.append("radio = ?")
                    event_values.append(int(radio))
                if time_from:
                    event_clauses.append("event_time >= ?")
                    event_values.append(time_from)
                if time_to:
                    event_clauses.append("event_time <= ?")
                    event_values.append(time_to)
                events_where = (
                    f"WHERE {' AND '.join(event_clauses)}" if event_clauses else ""
                )
                event_rows, total_events = self._budgeted_event_rows(
                    conn,
                    where=events_where,
                    values=event_values,
                    max_events=max(0, int(max_events)),
                )
                event_times = {
                    str(value)
                    for event in event_rows
                    for value in (
                        event.get("previous_sample_time"),
                        event.get("current_sample_time"),
                        event.get("event_time"),
                    )
                    if value
                }
                total_frames = int(source_totals["total_frames"] or 0)
                selected_series_count = len(selected_series) or total_series or 1
                bounded_rows = max(2, int(max_rows))
                requested_frames = max(2, int(max_frames))
                repository_frame_budget = min(
                    requested_frames,
                    max(2, bounded_rows // max(2, selected_series_count * 2)),
                )
                source_row_count = int(source_totals["total_rows"] or 0)
                # Apply the frame sampler at the row budget boundary as well.
                # Waiting for a second full budget lets a 50k source materialize
                # every row while a 200k source is already downsampled, causing
                # a large response-size discontinuity around the threshold.
                # Wide-series sources stay on the service sampler so every
                # AP/Radio keeps its run boundaries before response fitting.
                apply_repository_frame_budget = (
                    source_row_count >= bounded_rows
                    and total_series <= max(32, bounded_series // 4)
                )
                critical_sample_ids: set[int] = set()
                display_break_sample_ids: set[int] = set()
                source_interval: float | None = None
                source_gap: float | None = None
                if apply_repository_frame_budget:
                    ordered_source_times = [
                        str(row["sample_time"])
                        for row in conn.execute(
                            f"""
                            SELECT sample_time
                            FROM mesh_links
                            {where}
                            GROUP BY source_file_id, radio, sample_id, sample_time
                            ORDER BY sample_time, sample_id
                            """,
                            values,
                        ).fetchall()
                        if row["sample_time"]
                    ]
                    source_interval, source_gap = _interval_and_threshold(ordered_source_times)
                    display_gap_seconds = max(
                        float(source_gap or 0.0) * 10.0,
                        float(source_interval or 0.0) * 20.0,
                        60.0,
                    )
                    critical_sample_ids, display_break_sample_ids = self._trackside_boundary_sample_ids(
                        conn,
                        where=where,
                        values=values,
                        series_identity=series_identity,
                        display_gap_seconds=display_gap_seconds,
                    )
                query_row_budget = bounded_rows if apply_repository_frame_budget else max(
                    bounded_rows,
                    source_row_count,
                )
                raw_rows, query_totals = self._budgeted_chart_rows(
                    conn,
                    chart_columns=chart_columns,
                    where=where,
                    values=values,
                    order_by="sample_time ASC, radio ASC, id ASC",
                    max_rows=query_row_budget,
                    event_times=event_times,
                    critical_sample_ids=critical_sample_ids,
                    critical_frame_row_limit=bounded_series * 2,
                    frame_count=total_frames if apply_repository_frame_budget else 0,
                    max_frames=repository_frame_budget if apply_repository_frame_budget else 0,
                    known_totals=source_totals if not selected_series else None,
                )
                rows = [
                    dict(row)
                    for row in raw_rows
                ]
                for row in rows:
                    if int(row.get("sample_id") or row.get("id") or 0) in display_break_sample_ids:
                        row["_trackside_break_before"] = True
        ordered_times = list(
            dict.fromkeys(str(row.get("sample_time") or "") for row in rows if row.get("sample_time"))
        )
        interval, gap = _interval_and_threshold(ordered_times)
        if not self._is_index_database() and source_interval is not None:
            interval = source_interval
            gap = source_gap
        anchor = next(
            (row for row in rows if row.get("link_state") == LINK_STATE_ACTIVE),
            rows[0] if rows else None,
        )
        run_segment = _segment_payload(anchor, rows, interval, gap)
        if not self._is_index_database():
            run_segment.update(query_totals)
            run_segment.update(
                {
                    "source_total_rows": int(source_totals["total_rows"] or 0),
                    "source_active_rows": int(source_totals["active_rows"] or 0),
                    "source_standby_rows": int(source_totals["standby_rows"] or 0),
                    "source_triangle_rows": int(source_totals["triangle_rows"] or 0),
                    "source_total_frames": int(source_totals["total_frames"] or 0),
                    "source_total_series": total_series,
                    "returned_rows": len(rows),
                    "returned_events": len(event_rows),
                    "total_events": total_events,
                    "repository_row_budget": max(2, int(max_rows)),
                    "repository_frame_budget": repository_frame_budget,
                    "repository_series_budget": bounded_series,
                    "repository_event_budget": max(0, int(max_events)),
                    "repository_downsampled": bool(
                        int(source_totals["total_rows"] or 0) > len(rows)
                        or total_series > bounded_series
                        or (
                            apply_repository_frame_budget
                            and total_frames > repository_frame_budget
                        )
                    ),
                }
            )
        return {"run_segment": run_segment}

    def _query_active_path_backup_rows(self, conn: sqlite3.Connection, active_rows: list[dict[str, object]]) -> list[dict[str, object]]:
        if not active_rows:
            return []
        source_ids = sorted({int(row.get("source_file_id")) for row in active_rows if row.get("source_file_id") not in (None, "")})
        times = [str(row.get("sample_time") or "") for row in active_rows if row.get("sample_time")]
        if not source_ids or not times:
            app_logger.log_warning(
                "MESH_ACTIVE_PATH_BACKUP_QUERY_DONE",
                f"active_count={len(active_rows)}, standby_count=0, matched_backup_count=0, reason=missing_source_or_time",
            )
            return []
        start_time, end_time = _expand_time_range(min(times), max(times), 1.0)
        placeholders = ",".join("?" for _ in source_ids)
        app_logger.log_info(
            "MESH_ACTIVE_PATH_BACKUP_QUERY_START",
            f"active_count={len(active_rows)}, source_count={len(source_ids)}, start_time={start_time}, end_time={end_time}",
        )
        chart_columns = _mesh_link_chart_columns(conn)
        return [
            _with_synthetic_payload(row)
            for row in conn.execute(
                f"""
                SELECT {chart_columns}
                FROM mesh_links
                WHERE link_state = ?
                  AND source_file_id IN ({placeholders})
                  AND sample_time >= ?
                  AND sample_time <= ?
                ORDER BY source_file_id ASC, sample_time ASC, radio ASC, peer_mac_normalized ASC, id ASC
                """,
                (LINK_STATE_STANDBY, *source_ids, start_time, end_time),
            ).fetchall()
        ]

    def query_active_link_build_order(
        self,
        source_file_id: int | str | None = None,
        radio: int | None = None,
        analysis_params: MeshAnalysisParams | dict[str, object] | str | None = None,
        fallback_analysis_params: MeshAnalysisParams | dict[str, object] | str | None = None,
    ) -> list[dict[str, object]]:
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                rows = repo.query_active_link_build_order(None, radio, analysis_params, fallback_analysis_params) if repo else []
                for row in rows:
                    row["source_file_id"] = int(source_file_id)
                return rows
            rows: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                detail_rows = repo.query_active_link_build_order(None, radio, analysis_params, fallback_analysis_params)
                for row in detail_rows:
                    row["source_file_id"] = source_id
                rows.extend(detail_rows)
            for index, row in enumerate(rows, start=1):
                row["sequence"] = index
            return rows
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("ap.source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("ap.radio = ?")
            values.append(int(radio))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            identity_columns = _mesh_link_identity_columns(
                conn,
                table_alias="ml",
            )
            link_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(mesh_links)").fetchall()
            }
            active_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(active_points)").fetchall()
            }

            def optional_location_column(column: str) -> str:
                candidates: list[str] = []
                if column in link_columns:
                    candidates.append(f"NULLIF(ml.{column}, '')")
                if column in active_columns:
                    candidates.append(f"NULLIF(ap.{column}, '')")
                return (
                    f"COALESCE({', '.join(candidates)}, '') AS {column}"
                    if candidates
                    else f"'' AS {column}"
                )

            rows = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT ap.id, ap.link_id, ap.source_file_id, ap.radio, ap.sample_time,
                           ap.peer_mac_raw, ap.peer_mac_normalized, ap.peer_mac,
                           ap.peer_ap_name, ap.peer_site, ap.peer_radio, ap.peer_radio_label,
                           ml.peer_ap_mac, ml.peer_radio_mac,
                           {optional_location_column("peer_section")},
                           {optional_location_column("peer_location")},
                           {optional_location_column("peer_direction")},
                           {identity_columns},
                           ap.duration_text, ap.duration_seconds,
                           ap.local_rssi_db, ap.peer_rssi_db,
                           ap.local_tx_busy, ap.peer_tx_busy, ap.local_rx_busy, ap.peer_rx_busy,
                           sf.archived_filename AS source_file,
                           sf.analysis_params_json AS analysis_params_json
                    FROM active_points ap
                    LEFT JOIN source_files sf ON sf.id = ap.source_file_id
                    LEFT JOIN mesh_links ml ON ml.id = ap.link_id
                    {where}
                    ORDER BY ap.source_file_id ASC, ap.radio ASC, ap.sample_time ASC, ap.id ASC
                    """,
                    values,
                ).fetchall()
            ]
        return _active_build_order_rows_from_points(rows, analysis_params, fallback_analysis_params)

    def query_peer_chart_initial_segments(self, anchor_link_id: int, visible_samples: int = 300, margin_samples: int = 60, source_file_id: int | str | None = None) -> dict[str, object]:
        if self._is_index_database() and source_file_id not in (None, ""):
            repo = self._detail_repo_for_source(source_file_id)
            return repo.query_peer_chart_initial_segments(anchor_link_id, visible_samples, margin_samples, None) if repo else {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
        if self._is_index_database():
            return _empty_peer_chart_payload("index database peer chart initial query requires source_file_id because mesh_links.id is local to each parsed database")
        with self._connect() as conn:
            chart_columns = _mesh_link_chart_columns(conn)
            anchor_row = conn.execute(f"SELECT {chart_columns} FROM mesh_links WHERE id = ?", (anchor_link_id,)).fetchone()
            if anchor_row is None:
                return {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
            anchor = _with_synthetic_payload(anchor_row)
            effective_source_file_id = int(source_file_id) if source_file_id not in (None, "") else anchor.get("source_file_id")
            radio = int(anchor.get("radio") or 0)
            session_id = anchor.get("session_id")
            anchor_time = str(anchor.get("sample_time") or "")
            interval, gap = self._estimate_local_interval(conn, radio, anchor_time)
            radius = max(1, int(visible_samples or 300) // 2 + int(margin_samples or 60))
            before = [
                str(row["sample_time"])
                for row in conn.execute(
                    """
                    SELECT DISTINCT sample_time
                    FROM mesh_links
                    WHERE radio = ? AND sample_time <= ? AND (? IS NULL OR session_id = ?) AND (? IS NULL OR source_file_id = ?)
                    ORDER BY sample_time DESC
                    LIMIT ?
                    """,
                    (radio, anchor_time, session_id, session_id, effective_source_file_id, effective_source_file_id, radius + 1),
                ).fetchall()
            ]
            after = [
                str(row["sample_time"])
                for row in conn.execute(
                    """
                    SELECT DISTINCT sample_time
                    FROM mesh_links
                    WHERE radio = ? AND sample_time > ? AND (? IS NULL OR session_id = ?) AND (? IS NULL OR source_file_id = ?)
                    ORDER BY sample_time ASC
                    LIMIT ?
                    """,
                    (radio, anchor_time, session_id, session_id, effective_source_file_id, effective_source_file_id, radius),
                ).fetchall()
            ]
        times = sorted(set(before + after))
        if not times:
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, [], interval, gap), "run_segment": _segment_payload(anchor, [], interval, gap)}
        return self._query_peer_chart_segments_in_range(anchor, times[0], times[-1], interval, gap, partial=True, full_loading=True, source_file_id=source_file_id)

    def query_peer_chart_segments_in_range(
        self,
        anchor_link_id: int,
        start_time: str,
        end_time: str,
        source_file_id: int | str | None = None,
    ) -> dict[str, object]:
        if self._is_index_database():
            if source_file_id in (None, ""):
                return _empty_peer_chart_payload(
                    "index database peer chart range query requires source_file_id because mesh_links.id is local to each parsed database"
                )
            repo = self._detail_repo_for_source(source_file_id)
            return repo.query_peer_chart_segments_in_range(anchor_link_id, start_time, end_time) if repo else _empty_peer_chart_payload("source file not found")
        anchor, _run_start, _run_end, interval, gap = self._locate_run_segment(
            anchor_link_id,
            source_file_id=source_file_id,
        )
        if anchor is None:
            return _empty_peer_chart_payload("anchor link not found")
        return self._query_peer_chart_segments_in_range(
            anchor,
            start_time,
            end_time,
            interval,
            gap,
            partial=True,
            full_loading=False,
            source_file_id=source_file_id,
        )

    def _query_peer_chart_segments_in_range(
        self,
        anchor: dict[str, object],
        start_time: str,
        end_time: str,
        interval: float | None,
        gap: float | None,
        partial: bool,
        full_loading: bool,
        source_file_id: int | str | None = None,
    ) -> dict[str, object]:
        peer_clauses = ["peer_mac_normalized = ?", "radio = ?", "sample_time >= ?", "sample_time <= ?"]
        peer_values: list[object] = [anchor.get("peer_mac_normalized"), anchor.get("radio"), start_time, end_time]
        if anchor.get("session_id"):
            peer_clauses.insert(2, "session_id = ?")
            peer_values.insert(2, anchor.get("session_id"))
        effective_source_file_id = int(source_file_id) if source_file_id not in (None, "") else None
        if effective_source_file_id is not None:
            peer_clauses.append("source_file_id = ?")
            peer_values.append(effective_source_file_id)
        app_logger.log_info(
            "MESH_PEER_CHART_CONTEXT_QUERY_START",
            (
                f"anchor_link_id={anchor.get('id')}, source_file_id={effective_source_file_id or ''}, "
                f"radio={anchor.get('radio')}, start_time={start_time}, end_time={end_time}"
            ),
        )
        with self._connect() as conn:
            chart_columns = _mesh_link_chart_columns(conn)
            peer_rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"SELECT {chart_columns} FROM mesh_links WHERE {' AND '.join(peer_clauses)} ORDER BY sample_time ASC, id ASC",
                    peer_values,
                ).fetchall()
            ]
            run_rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"""
                    SELECT {chart_columns}
                    FROM mesh_links
                    WHERE radio = ? AND sample_time >= ? AND sample_time <= ? AND (? IS NULL OR source_file_id = ?)
                    ORDER BY sample_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time, effective_source_file_id, effective_source_file_id),
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT {_MESH_EVENT_CHART_COLUMNS}
                    FROM switch_events
                    WHERE radio = ? AND event_time >= ? AND event_time <= ? AND (? IS NULL OR source_file_id = ?)
                    ORDER BY event_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time, effective_source_file_id, effective_source_file_id),
                ).fetchall()
            ]
        active_context = [row for row in run_rows if row.get("link_state") == LINK_STATE_ACTIVE]
        standby_context = [row for row in run_rows if row.get("link_state") == LINK_STATE_STANDBY]
        app_logger.log_info(
            "MESH_PEER_CHART_CONTEXT_QUERY_DONE",
            (
                f"selected_points={len(peer_rows)}, active_context_count={len(active_context)}, "
                f"standby_context_count={len(standby_context)}, "
                f"matched_backup_count={_count_exact_backup_matches(active_context, standby_context)}"
            ),
        )
        peer_segment = _segment_payload(anchor, peer_rows, interval, gap)
        run_segment = _segment_payload(anchor, run_rows, interval, gap)
        peer_segment["partial"] = partial
        peer_segment["full_loading"] = full_loading
        run_segment["partial"] = partial
        run_segment["full_loading"] = full_loading
        run_segment["events"] = events
        return {"anchor": anchor, "peer_segment": peer_segment, "run_segment": run_segment}

    def query_active_timeline(self, anchor_link_id: int) -> dict[str, object]:
        run = self.query_run_context_segment(anchor_link_id)
        rows = list(run.get("rows") or [])
        by_time: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            by_time[str(row.get("sample_time"))].append(row)
        active_by_time: dict[str, dict[str, object]] = {}
        anomalies: list[dict[str, object]] = []
        for sample_time, sample_rows in by_time.items():
            active_rows = [row for row in sample_rows if row.get("link_state") == LINK_STATE_ACTIVE]
            if len(active_rows) == 1:
                active_by_time[sample_time] = active_rows[0]
            else:
                anomalies.append({"sample_time": sample_time, "active_count": len(active_rows)})
        ordered_active = sorted(active_by_time.items(), key=lambda item: item[0])
        next_peer_by_time: dict[str, str | None] = {}
        future_peer: str | None = None
        for sample_time, active in reversed(ordered_active):
            peer = str(active.get("peer_mac_normalized") or active.get("peer_mac_raw") or "")
            next_peer_by_time[sample_time] = future_peer if future_peer and future_peer != peer else None
            if peer and peer != future_peer:
                future_peer = peer
        timeline: list[dict[str, object]] = []
        for sample_time, active in ordered_active:
            next_peer = next_peer_by_time.get(sample_time)
            next_row = None
            if next_peer:
                next_row = next((row for row in by_time.get(sample_time, []) if (row.get("peer_mac_normalized") or row.get("peer_mac_raw")) == next_peer), None)
            timeline.append({"sample_time": sample_time, "active": active, "next_active": next_row})
        return {"anchor": run.get("anchor"), "rows": timeline, "events": run.get("events", []), "anomalies": anomalies}

    def _locate_run_segment(self, anchor_link_id: int, batch_size: int = 1000, source_file_id: int | str | None = None) -> tuple[dict[str, object] | None, str | None, str | None, float | None, float | None]:
        with self._connect() as conn:
            chart_columns = _mesh_link_chart_columns(conn)
            anchor_row = conn.execute(f"SELECT {chart_columns} FROM mesh_links WHERE id = ?", (anchor_link_id,)).fetchone()
            if anchor_row is None:
                return None, None, None, None, None
            anchor = _with_synthetic_payload(anchor_row)
            radio = anchor["radio"]
            anchor_time = anchor["sample_time"]
            effective_source_file_id = int(source_file_id) if source_file_id not in (None, "") else None
            interval, gap = self._estimate_local_interval(conn, radio, anchor_time, effective_source_file_id)
            start_time = self._scan_segment_boundary(conn, radio, anchor_time, gap, "backward", batch_size, effective_source_file_id)
            end_time = self._scan_segment_boundary(conn, radio, anchor_time, gap, "forward", batch_size, effective_source_file_id)
        return anchor, start_time, end_time, interval, gap

    def _estimate_local_interval(self, conn: sqlite3.Connection, radio: int, anchor_time: str, source_file_id: int | None = None) -> tuple[float, float]:
        before = [
            row["sample_time"]
            for row in conn.execute(
                """
                SELECT DISTINCT sample_time
                FROM mesh_links
                WHERE radio = ? AND sample_time <= ? AND (? IS NULL OR source_file_id = ?)
                ORDER BY sample_time DESC
                LIMIT 21
                """,
                (radio, anchor_time, source_file_id, source_file_id),
            ).fetchall()
        ]
        after = [
            row["sample_time"]
            for row in conn.execute(
                """
                SELECT DISTINCT sample_time
                FROM mesh_links
                WHERE radio = ? AND sample_time >= ? AND (? IS NULL OR source_file_id = ?)
                ORDER BY sample_time ASC
                LIMIT 21
                """,
                (radio, anchor_time, source_file_id, source_file_id),
            ).fetchall()
        ]
        interval, gap = _interval_and_threshold(sorted(set(before + after)))
        return interval or 1.0, gap

    def _scan_segment_boundary(self, conn: sqlite3.Connection, radio: int, anchor_time: str, gap_seconds: float, direction: str, batch_size: int, source_file_id: int | None = None) -> str:
        current = anchor_time
        boundary = anchor_time
        operator = "<" if direction == "backward" else ">"
        order = "DESC" if direction == "backward" else "ASC"
        while True:
            rows = [
                row["sample_time"]
                for row in conn.execute(
                    f"""
                    SELECT DISTINCT sample_time
                    FROM mesh_links
                    WHERE radio = ? AND sample_time {operator} ? AND (? IS NULL OR source_file_id = ?)
                    ORDER BY sample_time {order}
                    LIMIT ?
                    """,
                    (radio, current, source_file_id, source_file_id, batch_size),
                ).fetchall()
            ]
            if not rows:
                return boundary
            for sample_time in rows:
                delta = _seconds_between(sample_time, current) if direction == "backward" else _seconds_between(current, sample_time)
                if delta > gap_seconds:
                    return boundary
                boundary = sample_time
                current = sample_time
            if len(rows) < batch_size:
                return boundary

    def query_peer_series(
        self,
        peer_mac_normalized: str,
        radio: int | None = None,
        session_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        source_file_id: int | str | None = None,
    ) -> list[dict[str, object]]:
        if self._is_index_database() and source_file_id not in (None, ""):
            repo = self._detail_repo_for_source(source_file_id)
            return repo.query_peer_series(peer_mac_normalized, radio, session_id, start_time, end_time, None) if repo else []
        clauses = ["peer_mac_normalized = ?"]
        values: list[object] = [peer_mac_normalized]
        if source_file_id not in (None, ""):
            clauses.append("source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("radio = ?")
            values.append(radio)
        if session_id:
            clauses.append("session_id = ?")
            values.append(session_id)
        if start_time:
            clauses.append("sample_time >= ?")
            values.append(start_time)
        if end_time:
            clauses.append("sample_time <= ?")
            values.append(end_time)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT sample_time, radio, peer_mac_normalized, peer_mac_raw, session_id, link_state,
                       establish_time, duration_seconds, expected_duration_seconds, duration_deviation_seconds,
                       local_signal_dbm, peer_signal_dbm, {_METRIC_SELECT_COLUMNS}, link_count,
                       peer_ap_name, peer_site, peer_radio_label, peer_radio, peer_radio_mac, peer_resolve_source
                FROM mesh_links
                WHERE {where}
                ORDER BY sample_time ASC, id ASC
                """,
                values,
            ).fetchall()
        return [_with_synthetic_payload(row) for row in rows]

    def rebuild_derived_analysis(self, should_cancel=None, progress=None, batch_size: int = 1000) -> None:
        if self._is_index_database():
            with self._connect() as conn:
                rows = conn.execute("SELECT id, parsed_db_path FROM source_files WHERE COALESCE(parsed_db_path, '') != ''").fetchall()
            for row in rows:
                if should_cancel and should_cancel():
                    return
                path = Path(str(row["parsed_db_path"] or ""))
                if not path.exists():
                    continue
                repo = MeshMrRepository(path)
                repo.rebuild_derived_analysis(should_cancel=should_cancel, progress=progress, batch_size=batch_size)
                size = path.stat().st_size if path.exists() else 0
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE source_files SET parsed_db_size = ?, db_schema_version = ? WHERE id = ?",
                        (size, SCHEMA_VERSION, int(row["id"])),
                    )
                    conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))
                    self._update_meta_counts(conn)
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM mesh_sessions")
            conn.execute("DELETE FROM switch_events")
            conn.execute("DELETE FROM active_points")
            conn.execute("DELETE FROM active_segments")
            conn.execute("DELETE FROM rssi_stats")
            conn.execute("DELETE FROM diagnosis_events")
            self._rebuild_sessions_and_deltas(conn, should_cancel, progress, batch_size)
            self._rebuild_active_events(conn, should_cancel, progress, batch_size)
            self._rebuild_active_points_segments_stats(conn, should_cancel)
            if should_cancel is None or not should_cancel():
                conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))
                self._update_meta_counts(conn)

    def needs_derived_analysis_rebuild(self) -> bool:
        if self._is_index_database():
            for repo in self._detail_repos():
                if repo.needs_derived_analysis_rebuild():
                    return True
            return False
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (DERIVED_ANALYSIS_KEY,)).fetchone()
        except sqlite3.Error:
            raise MeshSchemaRebuildRequired(
                "MESH 派生数据库无法读取，系统将自动修复。"
            )
        finally:
            if conn is not None:
                conn.close()
        if row is None:
            return True
        try:
            return int(row["value"]) < int(DERIVED_ANALYSIS_VERSION)
        except (TypeError, ValueError):
            return True

    def mark_derived_analysis_outdated(self) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, "0"))

    def summary(self) -> dict[str, object]:
        if self._is_index_database():
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        MIN(first_sample_time) AS earliest_sample_time,
                        MAX(last_sample_time) AS latest_sample_time,
                        COUNT(*) AS source_file_count,
                        COALESCE(SUM(records_parsed), 0) AS link_record_count,
                        COALESCE(SUM(records_parsed), 0) AS sample_count,
                        0 AS session_count,
                        0 AS event_count,
                        MAX(imported_at) AS last_import_at
                    FROM source_files
                    """
                ).fetchone()
            return dict(row)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    MIN(sample_time) AS earliest_sample_time,
                    MAX(sample_time) AS latest_sample_time,
                    (SELECT COUNT(*) FROM source_files) AS source_file_count,
                    COUNT(DISTINCT sample_id) AS sample_count,
                    COUNT(*) AS link_record_count,
                    COUNT(DISTINCT session_id) AS session_count,
                    (SELECT COUNT(*) FROM switch_events) AS event_count,
                    (SELECT MAX(imported_at) FROM source_files) AS last_import_at
                FROM mesh_links
                """
            ).fetchone()
        return dict(row)

    def export_rows(self, table: str) -> list[dict[str, object]]:
        if table not in {"mesh_links", "switch_events", "mesh_events", "mesh_sessions", "parse_issues", "source_files", "mesh_peer_mapping", "mesh_peer_resolve_cache", "active_points", "active_segments", "rssi_stats", "diagnosis_events"}:
            raise ValueError(f"Unsupported export table: {table}")
        if self._is_index_database() and table != "source_files":
            rows: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                detail_rows = repo.export_rows(table)
                for row in detail_rows:
                    if "source_file_id" in row:
                        row["source_file_id"] = source_id
                rows.extend(detail_rows)
            return rows
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if table in {"mesh_links", "active_points"}:
            return [_with_synthetic_payload(row) for row in rows]
        return [dict(row) for row in rows]

    def distinct_peer_macs(self) -> list[str]:
        if self._is_index_database():
            values = set()
            for repo in self._detail_repos():
                values.update(repo.distinct_peer_macs())
            return sorted(values)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT peer_mac_normalized
                FROM mesh_links
                WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
                ORDER BY peer_mac_normalized
                """
            ).fetchall()
        return [str(row["peer_mac_normalized"]) for row in rows]

    def upsert_peer_mappings(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        now = dt_text(datetime.now()) or ""
        values = [
            (
                normalize_mac_key(row.get("peer_mac_normalized")),
                row.get("peer_ap_name") or "",
                normalize_mac(row.get("peer_ap_mac")) or "",
                row.get("peer_radio_id"),
                row.get("peer_radio_label") or "",
                normalize_mac(row.get("peer_radio_mac")) or "",
                row.get("peer_site") or "",
                row.get("peer_section") or row.get("belong_section") or "",
                row.get("peer_location") or "",
                row.get("peer_direction") or row.get("line_side") or "",
                row.get("match_rule") or "",
                int(row.get("match_confidence") or 0),
                row.get("identity_status") or "unresolved",
                row.get("identity_source") or "",
                row.get("identity_reason") or "",
                now,
            )
            for row in rows
            if normalize_mac_key(row.get("peer_mac_normalized"))
        ]
        if not values:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO mesh_peer_mapping (
                    peer_mac_normalized, peer_ap_name, peer_ap_mac, peer_radio_id, peer_radio_label,
                    peer_site, peer_section, peer_location, peer_direction, match_rule, match_confidence,
                    identity_status, identity_source, identity_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_mac_normalized) DO UPDATE SET
                    peer_ap_name = excluded.peer_ap_name,
                    peer_ap_mac = excluded.peer_ap_mac,
                    peer_radio_id = excluded.peer_radio_id,
                    peer_radio_label = excluded.peer_radio_label,
                    peer_site = excluded.peer_site,
                    peer_section = excluded.peer_section,
                    peer_location = excluded.peer_location,
                    peer_direction = excluded.peer_direction,
                    match_rule = excluded.match_rule,
                    match_confidence = excluded.match_confidence,
                    identity_status = excluded.identity_status,
                    identity_source = excluded.identity_source,
                    identity_reason = excluded.identity_reason,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        value[0],
                        value[1],
                        value[2],
                        value[3],
                        value[4],
                        value[6],
                        value[7],
                        value[8],
                        value[9],
                        value[10],
                        value[11],
                        value[12],
                        value[13],
                        value[14],
                        value[15],
                    )
                    for value in values
                ],
            )
            conn.executemany(
                """
                INSERT INTO mesh_peer_resolve_cache (
                    peer_mac, peer_ap_name, peer_site, peer_radio, peer_radio_mac, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_mac) DO UPDATE SET
                    peer_ap_name = excluded.peer_ap_name,
                    peer_site = excluded.peer_site,
                    peer_radio = excluded.peer_radio,
                    peer_radio_mac = excluded.peer_radio_mac,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        value[0],
                        value[1],
                        value[6],
                        value[4],
                        value[5],
                        value[13] or value[12] or "unresolved",
                        value[15],
                    )
                    for value in values
                ],
            )
        if self._is_index_database():
            for repo in self._detail_repos():
                repo.upsert_peer_mappings(rows)

    def refresh_peer_mapping_on_links(self) -> None:
        if self._is_index_database():
            for repo in self._detail_repos():
                repo.refresh_peer_mapping_on_links()
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mesh_links
                SET
                    peer_mac = COALESCE(NULLIF(peer_mac_normalized, ''), peer_mac),
                    peer_ap_name = COALESCE((SELECT peer_ap_name FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_ap_mac = COALESCE((SELECT peer_ap_mac FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_site = COALESCE((SELECT peer_site FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_section = COALESCE((SELECT peer_section FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_location = COALESCE((SELECT peer_location FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_direction = COALESCE((SELECT peer_direction FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_radio_id = (SELECT peer_radio_id FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized),
                    peer_radio = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_radio_label = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_match_rule = COALESCE((SELECT match_rule FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_match_confidence = COALESCE((SELECT match_confidence FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 0),
                    peer_radio_mac = COALESCE((SELECT peer_radio_mac FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''),
                    peer_resolve_source = COALESCE((SELECT source FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), 'unresolved'),
                    peer_identity_status = COALESCE((SELECT identity_status FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 'unresolved'),
                    peer_identity_source = COALESCE((SELECT identity_source FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_identity_reason = COALESCE((SELECT identity_reason FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), '')
                WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
                """
            )

    def replace_peer_identity_mappings(
        self,
        rows: list[dict[str, object]],
        *,
        identity_index_revision: int = 0,
    ) -> dict[str, object]:
        """Atomically replace only AP identity projections on parsed MESH rows."""
        if self._is_index_database():
            by_peer = {
                normalize_mac_key(row.get("peer_mac_normalized")): row
                for row in rows
                if normalize_mac_key(row.get("peer_mac_normalized"))
            }
            summaries = []
            for repo in self._detail_repos():
                detail_rows = [
                    by_peer[peer_key]
                    for peer in repo.distinct_peer_macs()
                    if (peer_key := normalize_mac_key(peer)) in by_peer
                ]
                summaries.append(
                    repo.replace_peer_identity_mappings(
                        detail_rows,
                        identity_index_revision=identity_index_revision,
                    )
                )
            return _merge_peer_identity_remap_summaries(summaries)

        now = dt_text(datetime.now()) or ""
        values_by_key: dict[str, tuple[object, ...]] = {}
        rows_by_key: dict[str, dict[str, object]] = {}
        for row in rows:
            peer_key = normalize_mac_key(row.get("peer_mac_normalized"))
            if not peer_key:
                continue
            rows_by_key[peer_key] = dict(row)
            values_by_key[peer_key] = (
                peer_key,
                row.get("peer_ap_name") or "",
                normalize_mac(row.get("peer_ap_mac")) or "",
                row.get("peer_radio_id"),
                row.get("peer_radio_label") or "",
                normalize_mac(row.get("peer_radio_mac")) or "",
                row.get("peer_site") or "",
                row.get("peer_section") or row.get("belong_section") or "",
                row.get("peer_location") or "",
                row.get("peer_direction") or row.get("line_side") or "",
                row.get("match_rule") or "unresolved",
                int(row.get("match_confidence") or 0),
                row.get("identity_status") or "unresolved",
                row.get("identity_source") or "",
                row.get("identity_reason") or "",
                now,
            )
        values = list(values_by_key.values())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = _peer_identity_counts(conn)
            link_row_count_before = _table_row_count(conn, "mesh_links")
            active_point_row_count_before = _table_row_count(conn, "active_points")
            switch_event_row_count_before = _table_row_count(conn, "switch_events")
            fact_fingerprint_before = _mesh_fact_fingerprint(conn)
            conn.execute("DELETE FROM mesh_peer_mapping")
            conn.execute("DELETE FROM mesh_peer_resolve_cache")
            conn.executemany(
                """
                INSERT INTO mesh_peer_mapping (
                    peer_mac_normalized, peer_ap_name, peer_ap_mac,
                    peer_radio_id, peer_radio_label, peer_site, peer_section,
                    peer_location, peer_direction, match_rule, match_confidence,
                    identity_status, identity_source, identity_reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        value[0], value[1], value[2], value[3], value[4],
                        value[6], value[7], value[8], value[9], value[10],
                        value[11], value[12], value[13], value[14],
                        value[15],
                    )
                    for value in values
                ],
            )
            conn.executemany(
                """
                INSERT INTO mesh_peer_resolve_cache (
                    peer_mac, peer_ap_name, peer_site, peer_radio,
                    peer_radio_mac, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        value[0], value[1], value[6], value[4], value[5],
                        value[13] or value[12] or "unresolved", value[15],
                    )
                    for value in values
                ],
            )
            self._update_mesh_link_identity_projection(conn)
            self._update_active_point_identity_projection(conn)
            after = _peer_identity_counts(conn)
            fact_fingerprint_after = _mesh_fact_fingerprint(conn)
            summary = _peer_identity_remap_summary(
                conn,
                before=before,
                after=after,
                mapping_count=len(values),
                identity_index_revision=identity_index_revision,
                link_row_count_before=link_row_count_before,
                active_point_row_count_before=active_point_row_count_before,
                switch_event_row_count_before=switch_event_row_count_before,
                fact_fingerprint_before=fact_fingerprint_before,
                fact_fingerprint_after=fact_fingerprint_after,
            )
            _validate_peer_identity_remap(summary)
        source_counts: dict[str, int] = {}
        for value in values:
            source = str(value[13] or value[12] or "unresolved")
            source_counts[source] = source_counts.get(source, 0) + 1
        summary["source_counts"] = source_counts
        summary.update(_topology_projection_diagnostics(rows_by_key.values()))
        return summary

    @staticmethod
    def _update_mesh_link_identity_projection(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE mesh_links
            SET
                peer_ap_name = COALESCE((SELECT peer_ap_name FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_ap_mac = COALESCE((SELECT peer_ap_mac FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_site = COALESCE((SELECT peer_site FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_section = COALESCE((SELECT peer_section FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_location = COALESCE((SELECT peer_location FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_direction = COALESCE((SELECT peer_direction FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_radio_id = (SELECT peer_radio_id FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized),
                peer_radio = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_radio_label = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_radio_mac = COALESCE((SELECT peer_radio_mac FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), peer_mac_normalized, ''),
                peer_match_rule = COALESCE((SELECT match_rule FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 'unresolved'),
                peer_match_confidence = COALESCE((SELECT match_confidence FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 0),
                peer_resolve_source = COALESCE((SELECT source FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), 'unresolved'),
                peer_identity_status = COALESCE((SELECT identity_status FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 'unresolved'),
                peer_identity_source = COALESCE((SELECT identity_source FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                peer_identity_reason = COALESCE((SELECT identity_reason FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), 'exact_alias_not_found')
            WHERE peer_mac_normalized IS NOT NULL
              AND trim(peer_mac_normalized) != ''
            """
        )

    @staticmethod
    def _update_active_point_identity_projection(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE active_points
            SET
                peer_ap_name = COALESCE((SELECT peer_ap_name FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_site = COALESCE((SELECT peer_site FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_section = COALESCE((SELECT peer_section FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_location = COALESCE((SELECT peer_location FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_direction = COALESCE((SELECT peer_direction FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_radio = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), ''),
                peer_radio_label = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = active_points.peer_mac_normalized), '')
            WHERE peer_mac_normalized IS NOT NULL
              AND trim(peer_mac_normalized) != ''
            """
        )

    def update_identity_mapping_metadata(
        self,
        *,
        identity_index_revision: int,
        identity_mapped_at: str,
        identity_mapping_status: str,
    ) -> None:
        """Persist remap provenance without changing parsed MESH facts."""
        if self._is_index_database():
            for repo in self._detail_repos():
                repo.update_identity_mapping_metadata(
                    identity_index_revision=identity_index_revision,
                    identity_mapped_at=identity_mapped_at,
                    identity_mapping_status=identity_mapping_status,
                )
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE source_files
                SET identity_index_revision = ?, identity_mapped_at = ?,
                    identity_mapping_status = ?
                """,
                (
                    int(identity_index_revision),
                    str(identity_mapped_at or ""),
                    str(identity_mapping_status or "unknown"),
                ),
            )

    def rebuild_link_aggregates(self, bucket_seconds: tuple[int, ...] = (1, 10, 30, 60), should_cancel=None) -> None:
        return None

    def query_link_aggregates(self, bucket_seconds: int = 10, limit: int = 5000, offset: int = 0) -> list[dict[str, object]]:
        return []

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            conn = sqlite3.connect(
                _read_only_uri(self.path),
                uri=True,
                timeout=5,
                factory=_ReadOnlyConnection,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn
        conn = sqlite3.connect(self.path, timeout=30, factory=_ManagedConnection)
        conn.row_factory = sqlite3.Row
        configure_sqlite_connection(
            conn,
            foreign_keys=True,
            temp_store_memory=True,
        )
        return conn

    @staticmethod
    def _update_meta_counts(conn: sqlite3.Connection) -> None:
        counts = {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "source_file_count": conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0],
            "sample_count": conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0],
            "link_row_count": conn.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0],
            "active_point_count": conn.execute("SELECT COUNT(*) FROM active_points").fetchone()[0],
            "switch_event_count": conn.execute("SELECT COUNT(*) FROM switch_events").fetchone()[0],
            "active_segment_count": conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0],
            "parse_issue_count": conn.execute("SELECT COUNT(*) FROM parse_issues").fetchone()[0],
        }
        conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", [(key, str(value)) for key, value in counts.items()])

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _ensure_performance_indexes(conn: sqlite3.Connection) -> None:
        for _index_name, table, columns, sql in _MESH_PERFORMANCE_INDEXES:
            existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if all(column in existing for column in columns):
                conn.execute(sql)

    @staticmethod
    def _backfill_peer_columns(conn: sqlite3.Connection) -> None:
        now = dt_text(datetime.now()) or ""
        conn.execute(
            """
            INSERT OR IGNORE INTO mesh_peer_resolve_cache (
                peer_mac, peer_ap_name, peer_site, peer_radio, peer_radio_mac, source, updated_at
            )
            SELECT peer_mac_normalized, peer_ap_name, peer_site, peer_radio_label,
                   CASE
                       WHEN identity_status = 'matched'
                        AND (
                            peer_radio_id IS NOT NULL
                            OR lower(match_rule) LIKE '%radio%'
                            OR lower(match_rule) LIKE '%bssid%'
                        )
                       THEN peer_mac_normalized
                       ELSE ''
                   END,
                   COALESCE(NULLIF(identity_source, ''), identity_status, 'unresolved'),
                   ?
            FROM mesh_peer_mapping
            WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
            """,
            (now,),
        )
        conn.execute(
            """
            UPDATE mesh_links
            SET
                peer_mac = COALESCE(NULLIF(peer_mac, ''), peer_mac_normalized, ''),
                peer_ap_name = COALESCE(NULLIF((SELECT peer_ap_name FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_ap_name, ''),
                peer_ap_mac = COALESCE(NULLIF((SELECT peer_ap_mac FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_ap_mac, ''),
                peer_site = COALESCE(NULLIF((SELECT peer_site FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_site, ''),
                peer_section = COALESCE(NULLIF((SELECT peer_section FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_section, ''),
                peer_location = COALESCE(NULLIF((SELECT peer_location FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_location, ''),
                peer_direction = COALESCE(NULLIF((SELECT peer_direction FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_direction, ''),
                peer_radio = COALESCE(NULLIF((SELECT peer_radio FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_radio, peer_radio_label, ''),
                peer_radio_label = COALESCE(NULLIF(peer_radio_label, ''), peer_radio, ''),
                peer_radio_mac = COALESCE(NULLIF((SELECT peer_radio_mac FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_radio_mac, ''),
                peer_resolve_source = COALESCE(NULLIF((SELECT source FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_resolve_source, 'unresolved'),
                peer_match_rule = COALESCE(NULLIF((SELECT match_rule FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_match_rule, ''),
                peer_match_confidence = COALESCE((SELECT match_confidence FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), peer_match_confidence, 0),
                peer_identity_status = COALESCE(NULLIF((SELECT identity_status FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_identity_status, 'unresolved'),
                peer_identity_source = COALESCE(NULLIF((SELECT identity_source FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_identity_source, ''),
                peer_identity_reason = COALESCE(NULLIF((SELECT identity_reason FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''), peer_identity_reason, '')
            WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
            """
        )
        conn.execute(
            """
            UPDATE active_points
            SET
                peer_section = COALESCE(NULLIF((SELECT peer_section FROM mesh_links ml WHERE ml.id = active_points.link_id), ''), peer_section, ''),
                peer_location = COALESCE(NULLIF((SELECT peer_location FROM mesh_links ml WHERE ml.id = active_points.link_id), ''), peer_location, ''),
                peer_direction = COALESCE(NULLIF((SELECT peer_direction FROM mesh_links ml WHERE ml.id = active_points.link_id), ''), peer_direction, '')
            WHERE link_id IS NOT NULL
            """
        )

    def _rebuild_link_aggregates(self, conn: sqlite3.Connection, should_cancel=None, bucket_seconds: tuple[int, ...] = (1, 10, 30, 60)) -> None:
        return None

    def _rebuild_active_points_segments_stats(self, conn: sqlite3.Connection, should_cancel=None) -> None:
        conn.execute(
            """
            INSERT INTO active_points (
                link_id, sample_id, source_file_id, session_id, sample_time, device_time, radio,
                peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_site,
                peer_section, peer_location, peer_direction, peer_radio,
                peer_radio_label, establish_time, duration_text, duration_seconds, link_count,
                local_rssi_db, peer_rssi_db, local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy,
                local_noise_dbm, peer_noise_dbm, local_signal_dbm, peer_signal_dbm,
                raw_line_start, raw_line_end, raw_offset_start, raw_offset_end
            )
            SELECT
                ml.id, ml.sample_id, ml.source_file_id, COALESCE(ml.session_id, ''), ml.sample_time, s.device_time, ml.radio,
                ml.peer_mac_raw, COALESCE(ml.peer_mac_normalized, ''), COALESCE(ml.peer_mac, ''),
                COALESCE(ml.peer_ap_name, ''), COALESCE(ml.peer_site, ''),
                COALESCE(ml.peer_section, ''), COALESCE(ml.peer_location, ''),
                COALESCE(ml.peer_direction, ''), COALESCE(ml.peer_radio, ''),
                COALESCE(ml.peer_radio_label, ''), ml.establish_time, ml.duration_text, ml.duration_seconds, ml.link_count,
                ml.local_rssi_db, ml.peer_rssi_db, ml.local_tx_busy, ml.peer_tx_busy, ml.local_rx_busy, ml.peer_rx_busy,
                ml.local_noise_dbm, ml.peer_noise_dbm, ml.local_signal_dbm, ml.peer_signal_dbm,
                ml.raw_line_start, ml.raw_line_end, ml.raw_offset_start, ml.raw_offset_end
            FROM mesh_links ml
            LEFT JOIN samples s ON s.id = ml.sample_id
            WHERE ml.link_state = ?
            ORDER BY ml.source_file_id ASC, ml.radio ASC, ml.sample_time ASC, ml.id ASC
            """,
            (LINK_STATE_ACTIVE,),
        )
        rows = conn.execute(
            """
            SELECT id, source_file_id, radio, sample_time, peer_mac_normalized, peer_mac_raw,
                   peer_ap_name, peer_site, peer_section, peer_radio_label, local_rssi_db
            FROM active_points
            ORDER BY source_file_id ASC, radio ASC, sample_time ASC, id ASC
            """
        ).fetchall()
        segment_rows: list[tuple[object, ...]] = []
        point_updates: list[tuple[int, int]] = []
        current: list[sqlite3.Row] = []
        sequence = 0

        def flush_segment() -> None:
            nonlocal sequence, current
            if not current:
                return
            sequence += 1
            first = current[0]
            last = current[-1]
            rssi_values = [_int_or_none(row["local_rssi_db"]) for row in current]
            finite_rssi = [value for value in rssi_values if value not in (None, 0)]
            avg_rssi = round(sum(finite_rssi) / len(finite_rssi), 3) if finite_rssi else None
            duration = _seconds_between(str(first["sample_time"]), str(last["sample_time"]))
            segment_rows.append(
                (
                    first["radio"],
                    first["peer_mac_raw"] or "",
                    first["peer_mac_normalized"] or "",
                    first["peer_ap_name"] or "",
                    first["peer_site"] or "",
                    first["peer_section"] or "",
                    "",
                    first["sample_time"],
                    last["sample_time"],
                    max(duration, 0.0),
                    len(current),
                    avg_rssi,
                    min(finite_rssi) if finite_rssi else None,
                    max(finite_rssi) if finite_rssi else None,
                    rssi_values[0] if rssi_values else None,
                    rssi_values[-1] if rssi_values else None,
                    "stable",
                    first["source_file_id"],
                )
            )
            point_updates.extend((sequence, int(row["id"])) for row in current)
            current = []

        last_key: tuple[object, object, str] | None = None
        last_time = ""
        for row in rows:
            if should_cancel and should_cancel():
                return
            key = (row["source_file_id"], row["radio"], _canonical_mac(row["peer_mac_normalized"] or row["peer_mac_raw"]))
            sample_time = str(row["sample_time"] or "")
            if current and (key != last_key or _seconds_between(last_time, sample_time) > 5.0):
                flush_segment()
            current.append(row)
            last_key = key
            last_time = sample_time
        flush_segment()
        if segment_rows:
            conn.executemany(
                """
                INSERT INTO active_segments (
                    radio, peer_mac, peer_mac_normalized, peer_ap_name, belong_station, belong_section,
                    belong_type, start_time, end_time, duration_sec, sample_count, avg_rssi,
                    min_rssi, max_rssi, start_rssi, end_rssi, event_type, source_file_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                segment_rows,
            )
        if point_updates:
            conn.executemany("UPDATE active_points SET segment_id = ? WHERE id = ?", point_updates)
        self._rebuild_rssi_stats(conn)
        self._rebuild_diagnosis_events(conn)

    def _rebuild_rssi_stats(self, conn: sqlite3.Connection) -> None:
        scopes: dict[tuple[str, str], list[int]] = defaultdict(list)
        rows = conn.execute("SELECT radio, peer_mac_normalized, peer_site, local_rssi_db FROM active_points").fetchall()
        for row in rows:
            rssi = _int_or_none(row["local_rssi_db"])
            if rssi in (None, 0):
                continue
            scopes[("all", "all")].append(rssi)
            scopes[("radio", f"radio:{row['radio']}")].append(rssi)
            peer = str(row["peer_mac_normalized"] or "")
            if peer:
                scopes[("peer", f"peer:{peer}")].append(rssi)
            station = str(row["peer_site"] or "")
            if station:
                scopes[("station", f"station:{station}")].append(rssi)
        values = []
        for (scope_type, scope_key), samples in scopes.items():
            ordered = sorted(samples)
            values.append(
                (
                    scope_type,
                    scope_key,
                    len(ordered),
                    round(sum(ordered) / len(ordered), 3),
                    ordered[0],
                    ordered[-1],
                    _percentile(ordered, 10),
                    _percentile(ordered, 50),
                    _percentile(ordered, 90),
                    sum(1 for value in ordered if value < 25),
                    sum(1 for value in ordered if value < 20),
                )
            )
        if values:
            conn.executemany(
                """
                INSERT INTO rssi_stats (
                    scope_type, scope_key, sample_count, avg_rssi, min_rssi, max_rssi,
                    p10_rssi, p50_rssi, p90_rssi, low_rssi_count, severe_low_rssi_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def _rebuild_diagnosis_events(self, conn: sqlite3.Connection) -> None:
        switch_rows = conn.execute("SELECT event_time, event_type, radio, from_peer_mac, to_peer_mac FROM switch_events WHERE event_type IN (?, ?, ?)", (EVENT_ACTIVE_SWITCH, EVENT_NO_ACTIVE, EVENT_MULTI_ACTIVE)).fetchall()
        diagnosis_rows = [
            (
                row["event_time"],
                "warning" if row["event_type"] == EVENT_ACTIVE_SWITCH else "critical",
                "switch" if row["event_type"] == EVENT_ACTIVE_SWITCH else "link",
                row["event_type"],
                f"Radio {row['radio']} {row['event_type']}",
                f"{row['from_peer_mac'] or ''}->{row['to_peer_mac'] or ''}".strip("->"),
                "",
                row["to_peer_mac"] or row["from_peer_mac"] or "",
                None,
                None,
            )
            for row in switch_rows
        ]
        issue_rows = conn.execute(
            "SELECT line_number, severity, issue_type, message FROM parse_issues "
            "WHERE UPPER(COALESCE(severity, 'WARNING')) <> 'INFO'"
        ).fetchall()
        diagnosis_rows.extend(
            (
                None,
                "warning" if str(row["severity"] or "").upper() != "ERROR" else "critical",
                "parse",
                str(row["issue_type"] or "解析问题"),
                str(row["message"] or ""),
                f"line:{row['line_number']}",
                "",
                "",
                None,
                None,
            )
            for row in issue_rows
        )
        if diagnosis_rows:
            conn.executemany(
                """
                INSERT INTO diagnosis_events (
                    event_time, severity, category, title, detail, evidence, recommendation,
                    related_peer_mac, related_sample_id, related_segment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                diagnosis_rows,
            )

    def _rebuild_sessions_and_deltas(self, conn: sqlite3.Connection, should_cancel, progress, batch_size: int) -> None:
        cursor = conn.execute(
            """
            SELECT id, radio, peer_mac_normalized, peer_mac_raw, establish_time, sample_time,
                   link_state, local_tx, peer_tx, local_rx, peer_rx, local_retry, peer_retry,
                   local_err, peer_err, local_tx_garp, peer_rx_garp, local_tx_mul_join, peer_rx_mul_join
            FROM mesh_links
            ORDER BY radio, peer_mac_normalized, establish_time, sample_time, id
            """
        )
        previous_by_session: dict[str, sqlite3.Row] = {}
        session_rows: dict[str, dict[str, object]] = {}
        updates: list[tuple[str, int]] = []
        events: list[tuple[object, ...]] = []
        processed = 0
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                if should_cancel and should_cancel():
                    return
                metrics = _metrics_from_row(dict(row))
                peer = row["peer_mac_normalized"] or row["peer_mac_raw"]
                establish = row["establish_time"] or "unknown"
                session_id = _session_id(row["radio"], peer, establish)
                session = session_rows.setdefault(
                    session_id,
                    {
                        "session_id": session_id,
                        "radio": row["radio"],
                        "peer_mac_normalized": row["peer_mac_normalized"],
                        "peer_mac_raw": row["peer_mac_raw"],
                        "establish_time": row["establish_time"],
                        "first_sample_time": row["sample_time"],
                        "last_sample_time": row["sample_time"],
                        "sample_count": 0,
                        "active_sample_count": 0,
                        "standby_sample_count": 0,
                    },
                )
                session["last_sample_time"] = row["sample_time"]
                session["sample_count"] = int(session["sample_count"]) + 1
                if row["link_state"] == LINK_STATE_ACTIVE:
                    session["active_sample_count"] = int(session["active_sample_count"]) + 1
                else:
                    session["standby_sample_count"] = int(session["standby_sample_count"]) + 1
                previous = previous_by_session.get(session_id)
                if previous is not None:
                    previous_metrics = _metrics_from_row(dict(previous))
                    for key in _counter_keys():
                        current = metrics.get(key)
                        last = previous_metrics.get(key)
                        if isinstance(current, int) and isinstance(last, int) and current >= last:
                            continue
                        elif isinstance(current, int) and isinstance(last, int):
                            events.append(
                                (
                                    EVENT_COUNTER_RESET,
                                    row["sample_time"],
                                    row["radio"],
                                    previous["sample_time"],
                                    row["sample_time"],
                                    None,
                                    None,
                                    format_mac_h3c(row["peer_mac_normalized"]) if row["peer_mac_normalized"] else row["peer_mac_raw"],
                                    json.dumps({"event_type": EVENT_COUNTER_RESET, "source_line_number": 0}, ensure_ascii=False),
                                    None,
                                    0,
                                )
                            )
                updates.append((session_id, row["id"]))
                previous_by_session[session_id] = row
                processed += 1
            conn.executemany("UPDATE mesh_links SET session_id = ? WHERE id = ?", updates)
            updates.clear()
            if progress:
                progress(processed)
        conn.executemany(
            """
            INSERT OR REPLACE INTO mesh_sessions (
                session_id, radio, peer_mac_normalized, peer_mac_raw, establish_time,
                first_sample_time, last_sample_time, sample_count, active_sample_count, standby_sample_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session["session_id"],
                    session["radio"],
                    session["peer_mac_normalized"],
                    session["peer_mac_raw"],
                    session["establish_time"],
                    session["first_sample_time"],
                    session["last_sample_time"],
                    session["sample_count"],
                    session["active_sample_count"],
                    session["standby_sample_count"],
                )
                for session in session_rows.values()
            ],
        )
        if events:
            conn.executemany(
                """
                INSERT INTO switch_events (
                    event_type, event_time, radio, previous_sample_time, current_sample_time,
                    observed_window_ms, from_peer_mac, to_peer_mac, details_json,
                    source_file_id, source_line_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                events,
            )

    def _rebuild_active_events(self, conn: sqlite3.Connection, should_cancel, progress, batch_size: int) -> None:
        cursor = conn.execute(
            """
            SELECT id, sample_id, source_file_id, source_line_number, radio, sample_time, link_state,
                   peer_mac_normalized, peer_mac_raw, local_signal_dbm, peer_signal_dbm,
                   local_rssi_db, peer_rssi_db, local_rate_raw, peer_rate_raw
            FROM mesh_links
            ORDER BY radio, sample_time, id
            """
        )
        previous_active: dict[int, sqlite3.Row] = {}
        switch_history: dict[int, dict[str, object]] = {}
        current_key = None
        group: list[sqlite3.Row] = []
        event_rows: list[tuple[object, ...]] = []

        def flush_group(rows: list[sqlite3.Row]) -> None:
            if not rows:
                return
            radio = rows[0]["radio"]
            sample_time = rows[0]["sample_time"]
            active = [row for row in rows if row["link_state"] == LINK_STATE_ACTIVE]
            if len(active) == 0:
                event_rows.append((EVENT_NO_ACTIVE, sample_time, radio, None, sample_time, None, None, None, json.dumps({"event_type": EVENT_NO_ACTIVE}, ensure_ascii=False), rows[0]["source_file_id"], rows[0]["source_line_number"]))
                previous_active.pop(radio, None)
            elif len(active) > 1:
                event_rows.append((EVENT_MULTI_ACTIVE, sample_time, radio, None, sample_time, None, None, None, json.dumps({"event_type": EVENT_MULTI_ACTIVE}, ensure_ascii=False), active[0]["source_file_id"], active[0]["source_line_number"]))
                previous_active.pop(radio, None)
            else:
                row = active[0]
                previous = previous_active.get(radio)
                previous_peer = (previous["peer_mac_normalized"] or previous["peer_mac_raw"]) if previous else None
                current_peer = row["peer_mac_normalized"] or row["peer_mac_raw"]
                if previous is not None and _canonical_mac(previous_peer) != _canonical_mac(current_peer):
                    observed = int((datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(previous["sample_time"])).total_seconds() * 1000)
                    details = {
                        "from_local_signal_dbm": previous["local_signal_dbm"],
                        "to_local_signal_dbm": row["local_signal_dbm"],
                        "from_peer_signal_dbm": previous["peer_signal_dbm"],
                        "to_peer_signal_dbm": row["peer_signal_dbm"],
                        "from_local_rssi": previous["local_rssi_db"],
                        "to_local_rssi": row["local_rssi_db"],
                        "from_peer_rssi": previous["peer_rssi_db"],
                        "to_peer_rssi": row["peer_rssi_db"],
                        "from_local_rate": previous["local_rate_raw"],
                        "to_local_rate": row["local_rate_raw"],
                        "from_peer_rate": previous["peer_rate_raw"],
                        "to_peer_rate": row["peer_rate_raw"],
                        "source_file": "",
                    }
                    previous_switch = switch_history.get(radio)
                    previous_canonical = _canonical_mac(previous_peer)
                    current_canonical = _canonical_mac(current_peer)
                    if previous_switch and previous_switch.get("from_peer") == current_canonical and previous_switch.get("to_peer") == previous_canonical:
                        elapsed = int((datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(str(previous_switch.get("switch_time")))).total_seconds() * 1000)
                        if 0 <= elapsed <= 5000:
                            details.update(
                                {
                                    "is_rapid_flap": True,
                                    "rapid_flap_elapsed_ms": elapsed,
                                    "rapid_flap_from_peer": previous_switch.get("from_peer"),
                                    "rapid_flap_middle_peer": previous_switch.get("to_peer"),
                                    "rapid_flap_return_peer": current_canonical,
                                }
                            )
                    event_rows.append(
                        (
                            EVENT_ACTIVE_SWITCH,
                            row["sample_time"],
                            radio,
                            previous["sample_time"],
                            row["sample_time"],
                            observed,
                            normalize_mac(previous["peer_mac_normalized"]) if previous["peer_mac_normalized"] else previous["peer_mac_raw"],
                            normalize_mac(row["peer_mac_normalized"]) if row["peer_mac_normalized"] else row["peer_mac_raw"],
                            json.dumps(details, ensure_ascii=False),
                            row["source_file_id"],
                            row["source_line_number"],
                        )
                    )
                    switch_history[radio] = {"from_peer": previous_canonical, "to_peer": current_canonical, "switch_time": row["sample_time"]}
                previous_active[radio] = row

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                if should_cancel and should_cancel():
                    return
                key = (row["radio"], row["sample_id"])
                if current_key is None:
                    current_key = key
                if key != current_key:
                    flush_group(group)
                    group = []
                    current_key = key
                group.append(row)
        flush_group(group)
        if event_rows:
            conn.executemany(
                """
                INSERT INTO switch_events (
                    event_type, event_time, radio, previous_sample_time, current_sample_time,
                    observed_window_ms, from_peer_mac, to_peer_mac, details_json,
                    source_file_id, source_line_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                event_rows,
            )

    def _upsert_sessions(self, conn: sqlite3.Connection, records: list[MeshLogRecord]) -> None:
        by_session: dict[str, list[MeshLogRecord]] = {}
        for record in records:
            if record.session_id:
                by_session.setdefault(record.session_id, []).append(record)
        for session_id, rows in by_session.items():
            rows = sorted(rows, key=lambda item: item.sample_time)
            conn.execute(
                """
                INSERT OR REPLACE INTO mesh_sessions (
                    session_id, radio, peer_mac_normalized, peer_mac_raw, establish_time,
                    first_sample_time, last_sample_time, sample_count, active_sample_count, standby_sample_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    rows[0].radio,
                    rows[0].peer_mac_normalized,
                    rows[0].peer_mac_raw,
                    dt_text(rows[0].establish_time),
                    dt_text(rows[0].sample_time),
                    dt_text(rows[-1].sample_time),
                    len(rows),
                    sum(1 for row in rows if row.link_state == "ACTIVE"),
                    sum(1 for row in rows if row.link_state == "STANDBY"),
                ),
            )

    def _insert_events(self, conn: sqlite3.Connection, source_file_id: int, events: list[MeshSwitchEvent]) -> None:
        for event in events:
            conn.execute(
                """
                INSERT INTO switch_events (
                    event_type, event_time, radio, previous_sample_time, current_sample_time,
                    observed_window_ms, from_peer_mac, to_peer_mac, details_json,
                    source_file_id, source_line_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    dt_text(event.current_sample_time or event.previous_sample_time),
                    event.radio,
                    dt_text(event.previous_sample_time),
                    dt_text(event.current_sample_time),
                    event.observed_window_ms,
                    normalize_mac(event.from_peer_mac) or event.from_peer_mac,
                    normalize_mac(event.to_peer_mac) or event.to_peer_mac,
                    json.dumps(event.__dict__, default=str, ensure_ascii=False),
                    source_file_id,
                    event.source_line_number,
                ),
            )

    def _insert_issues(self, conn: sqlite3.Connection, source_file_id: int, issues: list[ParseIssue]) -> None:
        for issue in issues:
            conn.execute(
                """
                INSERT INTO parse_issues (
                    source_file_id, source_file, line_number, severity, issue_type, field_name, message,
                    raw_line_start, raw_line_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file_id,
                    issue.source_file,
                    issue.line_number,
                    issue.severity,
                    issue.issue_type,
                    issue.field_name,
                    issue.message,
                    issue.line_number,
                    issue.line_number,
                ),
            )


def _json(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metrics_from_row(row: dict[str, object]) -> dict[str, object]:
    return {column: row.get(column) for column in _METRIC_COLUMNS if row.get(column) is not None}


def _with_synthetic_payload(row: sqlite3.Row | dict[str, object]) -> dict[str, object]:
    data = dict(row)
    for field in ("peer_mac", "peer_ap_mac", "peer_radio_mac"):
        if data.get(field):
            data[field] = format_mac(data[field]) or data[field]
    data.setdefault("belong_section", data.get("peer_section") or "")
    data.setdefault("mileage", data.get("peer_location") or "")
    data.setdefault("line_side", data.get("peer_direction") or "")
    data.setdefault("metrics_json", json.dumps(_metrics_from_row(data), ensure_ascii=False))
    data.setdefault("deltas_json", "{}")
    data.setdefault("metrics", _metrics_from_row(data))
    return data


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[int], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * max(0, min(percentile, 100)) / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return round(values[lower] + (values[upper] - values[lower]) * fraction, 3)


def _session_id(radio: int, peer: str, establish_time: str) -> str:
    raw = f"{radio}|{peer}|{establish_time}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_mac(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character in "0123456789abcdef")


def _safe_mesh_db_stem(filename: str) -> str:
    stem = filename
    lowered = stem.lower()
    for suffix in (".gz", ".log", ".txt"):
        if lowered.endswith(suffix):
            stem = stem[: -len(suffix)]
            lowered = stem.lower()
    safe = "".join(character if (character.isalnum() or character in "_-") else "_" for character in stem).strip("_")
    return safe or "meshlog"


def _counter_keys() -> tuple[str, ...]:
    return (
        "local_tx",
        "peer_tx",
        "local_rx",
        "peer_rx",
        "local_retry",
        "peer_retry",
        "local_err",
        "peer_err",
        "local_tx_garp",
        "peer_rx_garp",
        "local_tx_mul_join",
        "peer_rx_mul_join",
    )


def _continuous_rows_containing(rows: list[dict[str, object]], anchor_link_id: int, group_by_time: bool = False) -> tuple[list[dict[str, object]], float | None, float | None]:
    if not rows:
        return [], None, None
    anchor_index = next((index for index, row in enumerate(rows) if int(row.get("id") or 0) == anchor_link_id), -1)
    if anchor_index < 0:
        return [], None, None
    if group_by_time:
        ordered_times = sorted({str(row.get("sample_time")) for row in rows if row.get("sample_time")})
        anchor_time = str(rows[anchor_index].get("sample_time"))
        if anchor_time not in ordered_times:
            return [], None, None
        interval, threshold = _interval_and_threshold(ordered_times)
        time_index = ordered_times.index(anchor_time)
        start_index = time_index
        while start_index > 0 and _seconds_between(ordered_times[start_index - 1], ordered_times[start_index]) <= threshold:
            start_index -= 1
        end_index = time_index
        while end_index + 1 < len(ordered_times) and _seconds_between(ordered_times[end_index], ordered_times[end_index + 1]) <= threshold:
            end_index += 1
        start_time = ordered_times[start_index]
        end_time = ordered_times[end_index]
        return [row for row in rows if start_time <= str(row.get("sample_time")) <= end_time], interval, threshold
    ordered_times = [str(row.get("sample_time")) for row in rows if row.get("sample_time")]
    interval, threshold = _interval_and_threshold(ordered_times)
    start = anchor_index
    while start > 0 and _seconds_between(str(rows[start - 1].get("sample_time")), str(rows[start].get("sample_time"))) <= threshold:
        start -= 1
    end = anchor_index
    while end + 1 < len(rows) and _seconds_between(str(rows[end].get("sample_time")), str(rows[end + 1].get("sample_time"))) <= threshold:
        end += 1
    return rows[start : end + 1], interval, threshold


def _interval_and_threshold(ordered_times: list[str]) -> tuple[float | None, float]:
    gaps = [gap for previous, current in zip(ordered_times, ordered_times[1:]) if (gap := _seconds_between(previous, current)) >= 0]
    interval = float(median(gaps)) if gaps else None
    return interval, min(max((interval or 1.0) * 5, 5.0), 60.0)


def _group_rows_by_value(rows: list[dict[str, object]], key: str) -> list[list[dict[str, object]]]:
    groups: list[list[dict[str, object]]] = []
    previous: object = object()
    for row in rows:
        value = row.get(key)
        if not groups or value != previous:
            groups.append([])
            previous = value
        groups[-1].append(row)
    return groups


def _segment_payload(anchor: dict[str, object] | None, rows: list[dict[str, object]], interval: float | None, gap: float | None) -> dict[str, object]:
    return {
        "anchor": anchor,
        "rows": rows,
        "segment_start": rows[0]["sample_time"] if rows else None,
        "segment_end": rows[-1]["sample_time"] if rows else None,
        "estimated_interval_seconds": interval,
        "continuity_gap_seconds": gap,
    }


def _empty_peer_chart_payload(message: str) -> dict[str, object]:
    peer_segment = _segment_payload(None, [], None, None)
    run_segment = _segment_payload(None, [], None, None)
    peer_segment["message"] = message
    run_segment["message"] = message
    return {"anchor": None, "peer_segment": peer_segment, "run_segment": run_segment, "message": message}


def _expand_time_range(start_time: str, end_time: str, margin_seconds: float) -> tuple[str, str]:
    try:
        start = datetime.fromisoformat(start_time) - timedelta(seconds=margin_seconds)
        end = datetime.fromisoformat(end_time) + timedelta(seconds=margin_seconds)
    except (TypeError, ValueError):
        return start_time, end_time
    return _format_sample_time(start), _format_sample_time(end)


def _format_sample_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _count_exact_backup_matches(active_rows: list[dict[str, object]], standby_rows: list[dict[str, object]]) -> int:
    standby_index: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in standby_rows:
        key = (
            str(row.get("source_file_id") or ""),
            str(row.get("sample_time") or ""),
            str(row.get("timestamp_tag") or ""),
        )
        standby_index[key] += 1
    matched = 0
    for row in active_rows:
        key = (
            str(row.get("source_file_id") or ""),
            str(row.get("sample_time") or ""),
            str(row.get("timestamp_tag") or ""),
        )
        matched += standby_index.get(key, 0)
    return matched


def _seconds_between(previous: str, current: str) -> float:
    try:
        return (datetime.fromisoformat(current) - datetime.fromisoformat(previous)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _active_build_order_rows_from_points(
    rows: list[dict[str, object]],
    analysis_params: MeshAnalysisParams | dict[str, object] | str | None = None,
    fallback_analysis_params: MeshAnalysisParams | dict[str, object] | str | None = None,
) -> list[dict[str, object]]:
    if not rows:
        return []
    override_params = normalize_mesh_analysis_params(analysis_params) if analysis_params is not None else None
    fallback_params = normalize_mesh_analysis_params(fallback_analysis_params) if fallback_analysis_params is not None else None
    times_by_scope: dict[tuple[object, object], list[str]] = defaultdict(list)
    params_by_scope: dict[tuple[object, object], MeshAnalysisParams] = {}
    for row in rows:
        sample_time = str(row.get("sample_time") or "")
        scope = (row.get("source_file_id"), row.get("radio"))
        if sample_time:
            times_by_scope[scope].append(sample_time)
        params_by_scope.setdefault(scope, _analysis_params_for_row(row, override_params, fallback_params))
    interval_by_scope: dict[tuple[object, object], tuple[float, float]] = {}
    for scope, times in times_by_scope.items():
        params = params_by_scope.get(scope) or MeshAnalysisParams()
        if params.sample_interval_ms:
            interval = max(params.sample_interval_ms / 1000.0, 0.001)
            threshold = min(max(interval * 5, 5.0), 60.0)
        else:
            interval, threshold = _interval_and_threshold(sorted(set(times)))
        interval_by_scope[scope] = (float(interval or 1.0), threshold)

    result: list[dict[str, object]] = []
    gap_seconds = {scope: values[1] for scope, values in interval_by_scope.items()}
    time_windows = {scope: params.link_time_window / 1000.0 for scope, params in params_by_scope.items()}
    segments = MeshLinkAnalyzer().group_active_points(rows, gap_seconds, time_windows)
    first_link_by_scope: set[tuple[object, object]] = set()
    previous_signal_by_scope: dict[tuple[object, object], float | None] = {}
    for segment in segments:
        scope = (segment[0].get("source_file_id"), segment[0].get("radio"))
        sample_interval, _threshold = interval_by_scope.get(scope, (1.0, 5.0))
        params = params_by_scope.get(scope) or _analysis_params_for_row(segment[0], override_params, fallback_params)
        item = _active_build_order_row(len(result) + 1, segment, sample_interval, params)
        decision = MeshLinkAnalyzer(params).evaluate_establishment(
            item,
            first_link=scope not in first_link_by_scope,
            previous_signal=previous_signal_by_scope.get(scope),
        )
        item.update(
            link_time_window=params.link_time_window,
            link_switch_threshold=params.link_switch_threshold,
            link_hold_rssi=params.link_hold_rssi,
            link_establish_threshold=params.link_establish_threshold,
            link_establish_rssi=params.link_establish_rssi,
            link_establishment_accepted=decision.accepted,
            link_establishment_signal=decision.signal,
            link_establishment_reason=decision.reason,
        )
        result.append(item)
        first_link_by_scope.add(scope)
        if decision.accepted:
            previous_signal_by_scope[scope] = decision.signal
    _classify_active_switches(result)
    _mark_pingpong_events(result)
    return result


def _active_build_order_row(sequence: int, rows: list[dict[str, object]], sample_interval: float, params: MeshAnalysisParams) -> dict[str, object]:
    first = rows[0]
    last = rows[-1]
    duration = max(_seconds_between(str(first.get("sample_time") or ""), str(last.get("sample_time") or "")) + max(sample_interval, 0.0), 0.0)
    reported_values = [value for row in rows if (value := _float(row.get("duration_seconds"))) is not None]
    rssi_values = [_float(row.get("local_rssi_db")) for row in rows]
    rssi_stats = calc_numeric_stats(rssi_values)
    tx_values = [_float(row.get("local_tx_busy")) for row in rows]
    rx_values = [_float(row.get("local_rx_busy")) for row in rows]
    peer_tx_values = [_float(row.get("peer_tx_busy")) for row in rows]
    peer_rx_values = [_float(row.get("peer_rx_busy")) for row in rows]
    peer_radio = _first_nonempty([row.get("peer_radio_label") for row in rows]) or _first_nonempty([row.get("peer_radio") for row in rows])
    short_threshold_ms = params.short_link_threshold_ms
    physical_ap_key = _physical_ap_key(first)
    return {
        "sequence": sequence,
        "source_file_id": first.get("source_file_id"),
        "radio": first.get("radio"),
        "peer_mac_raw": first.get("peer_mac_raw") or "",
        "active_peer_mac": first.get("peer_mac_normalized") or first.get("peer_mac_raw") or "",
        "peer_ap_name": first.get("peer_ap_name") or "",
        "peer_ap_mac": first.get("peer_ap_mac") or "",
        "peer_site": first.get("peer_site") or "",
        "peer_section": first.get("peer_section") or "",
        "belong_section": first.get("peer_section") or "",
        "mileage": first.get("peer_location") or "",
        "peer_location": first.get("peer_location") or "",
        "line_side": first.get("peer_direction") or "",
        "peer_direction": first.get("peer_direction") or "",
        "peer_radio": peer_radio,
        "peer_radio_mac": first.get("peer_radio_mac") or "",
        "identity_status": first.get("peer_identity_status") or first.get("identity_status") or "unresolved",
        "identity_source": first.get("peer_identity_source") or first.get("identity_source") or first.get("peer_resolve_source") or "",
        "identity_rule": first.get("peer_match_rule") or first.get("identity_rule") or "",
        "identity_confidence": first.get("peer_match_confidence") or first.get("identity_confidence") or 0,
        "identity_reason": first.get("peer_identity_reason") or first.get("identity_reason") or "",
        "anchor_link_id": first.get("link_id") or first.get("id"),
        "build_start_time": first.get("sample_time") or "",
        "build_end_time": last.get("sample_time") or "",
        "main_link_duration_seconds": round(duration, 3),
        "reported_duration_seconds": max(reported_values) if reported_values else "",
        "sample_count": len(rows),
        "avg_mr_rssi": rssi_stats["avg"],
        "min_mr_rssi": rssi_stats["min"],
        "max_mr_rssi": rssi_stats["max"],
        "p10_mr_rssi": rssi_stats["p10"],
        "avg_tx_busy": _average(tx_values),
        "avg_rx_busy": _average(rx_values),
        "avg_peer_tx_busy": _average(peer_tx_values),
        "avg_peer_rx_busy": _average(peer_rx_values),
        "main_link_switch_time_ms": params.link_time_window,
        "short_link_tolerance_ms": params.short_link_tolerance_ms,
        "pingpong_tolerance_ms": params.pingpong_tolerance_ms,
        "pingpong_return_window_ms": params.effective_pingpong_return_window_ms,
        "short_threshold_seconds": round(short_threshold_ms / 1000.0, 3),
        "min_normal_sample_count": MIN_NORMAL_ACTIVE_SAMPLE_COUNT,
        "is_same_physical_ap_radio_switch": False,
        "physical_ap_key": physical_ap_key,
        "merge_same_physical_ap_dual_radio": params.merge_same_physical_ap_dual_radio,
        "build_result": "stable",
        "judge_reason": "等待与上一有效 ACTIVE 区段比较后判定是否发生切换",
        "is_ap_return_event": False,
        "is_pingpong_abnormal": False,
        "pingpong_type": "无",
        "pingpong_group_id": "",
        "pingpong_return_duration_ms": "",
        "middle_ap_dwell_ms": "",
        "previous_ap": "",
        "middle_ap": "",
        "return_ap": "",
        "pingpong_count": "",
        "pingpong_judgment_reason": "",
        "source_file": first.get("source_file") or first.get("archived_filename") or first.get("source_file_id") or "",
    }


def _analysis_params_for_row(
    row: dict[str, object],
    override_params: MeshAnalysisParams | None,
    fallback_params: MeshAnalysisParams | None,
) -> MeshAnalysisParams:
    if override_params is not None:
        return override_params
    raw_snapshot = row.get("analysis_params_json")
    if str(raw_snapshot or "").strip():
        return mesh_analysis_params_from_json(raw_snapshot)
    return fallback_params or MeshAnalysisParams()


def _classify_active_switches(rows: list[dict[str, object]]) -> None:
    """仅对有效 ACTIVE 身份变化后的新主链做正常/短时分类。"""

    previous_by_scope: dict[tuple[object, object], dict[str, object]] = {}
    for row in sorted(rows, key=lambda item: (item.get("source_file_id"), item.get("radio"), str(item.get("build_start_time") or ""))):
        scope = (row.get("source_file_id"), row.get("radio"))
        previous = previous_by_scope.get(scope)
        duration_ms = _segment_duration_ms(row)
        threshold_ms = _positive_int_or_default(row.get("main_link_switch_time_ms"), 4000)
        current_identity = _physical_ap_key(row)
        previous_identity = _physical_ap_key(previous) if previous is not None else ""
        current_peer = _canonical_mac(row.get("active_peer_mac"))
        previous_peer = _canonical_mac(previous.get("active_peer_mac")) if previous is not None else ""

        if previous is None:
            row["build_result"] = "stable"
            row["judge_reason"] = "首个有效 ACTIVE 区段，只记为稳定主链起点，不计为切换。"
        elif current_identity and current_identity == previous_identity:
            if current_peer and previous_peer and current_peer != previous_peer:
                row["is_same_physical_ap_radio_switch"] = True
                row["build_result"] = "same_ap_radio_switch"
                row["judge_reason"] = "同一物理 AP 的射频变化，不计为 AP 主链切换或短时建链。"
            else:
                row["build_result"] = "stable"
                row["judge_reason"] = "ACTIVE AP 身份未变化，不计为新的主链切换。"
        elif duration_ms < threshold_ms:
            row["build_result"] = "short"
            row["judge_reason"] = f"切换后新主链持续 {duration_ms}ms < 基准时间 {threshold_ms}ms，判定短时建链。"
        else:
            row["build_result"] = "normal"
            row["judge_reason"] = f"切换后新主链持续 {duration_ms}ms >= 基准时间 {threshold_ms}ms，判定正常切换。"
        previous_by_scope[scope] = row


def _mark_same_physical_ap_radio_switches(rows: list[dict[str, object]]) -> None:
    for index, row in enumerate(rows):
        if row.get("build_result") != "short" or not row.get("merge_same_physical_ap_dual_radio"):
            continue
        key = str(row.get("physical_ap_key") or "")
        if not key:
            continue
        for neighbor in _neighbor_segments(rows, index):
            if not _same_switch_scope(row, neighbor):
                continue
            if key != str(neighbor.get("physical_ap_key") or ""):
                continue
            if _canonical_mac(row.get("active_peer_mac")) == _canonical_mac(neighbor.get("active_peer_mac")):
                continue
            row["is_same_physical_ap_radio_switch"] = True
            row["build_result"] = "same_ap_radio_switch"
            row["judge_reason"] = "同一物理 AP 的双射频口切换，未判短时建链"
            break


def _mark_pingpong_events(rows: list[dict[str, object]]) -> None:
    by_scope: dict[tuple[object, object], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_scope[(row.get("source_file_id"), row.get("radio"))].append(row)
    group_index = 0
    for scope_rows in by_scope.values():
        ordered = sorted(scope_rows, key=lambda item: str(item.get("build_start_time") or ""))
        for index in range(len(ordered) - 2):
            previous, middle, returned = ordered[index], ordered[index + 1], ordered[index + 2]
            return_duration_ms = _elapsed_ms(previous.get("build_end_time"), returned.get("build_start_time"))
            if return_duration_ms is None or return_duration_ms > _pingpong_return_window_ms(middle):
                continue
            previous_key = str(previous.get("physical_ap_key") or "")
            middle_key = str(middle.get("physical_ap_key") or "")
            returned_key = str(returned.get("physical_ap_key") or "")
            if not previous_key or not middle_key or not returned_key:
                continue
            middle_dwell_ms = _segment_duration_ms(middle)
            if previous_key == middle_key == returned_key and _canonical_mac(previous.get("active_peer_mac")) != _canonical_mac(middle.get("active_peer_mac")):
                group_index += 1
                _set_pingpong_fields(
                    middle,
                    group_index,
                    "同AP射频往返",
                    False,
                    False,
                    return_duration_ms,
                    middle_dwell_ms,
                    previous,
                    middle,
                    returned,
                    f"同一物理 AP 内 {previous.get('peer_radio') or '-'} -> {middle.get('peer_radio') or '-'} -> {returned.get('peer_radio') or '-'}，不计入 AP 乒乓。",
                )
                continue
            if previous_key != returned_key or previous_key == middle_key:
                continue
            group_index += 1
            pingpong_type, is_abnormal, reason = _classify_pingpong_return(previous, middle, returned, middle_dwell_ms)
            _set_pingpong_fields(
                middle,
                group_index,
                pingpong_type,
                True,
                is_abnormal,
                return_duration_ms,
                middle_dwell_ms,
                previous,
                middle,
                returned,
                reason,
            )


def _classify_pingpong_return(
    previous: dict[str, object],
    middle: dict[str, object],
    returned: dict[str, object],
    middle_dwell_ms: int,
) -> tuple[str, bool, str]:
    switch_ms = _positive_int_or_default(middle.get("main_link_switch_time_ms"), 2500)
    tolerance_ms = max(_positive_int_or_default(middle.get("pingpong_tolerance_ms"), 500), 0)
    abnormal_threshold = max(switch_ms - tolerance_ms, 0)
    critical_upper = switch_ms + tolerance_ms
    sequence = f"{_segment_ap_label(previous)} -> {_segment_ap_label(middle)} -> {_segment_ap_label(returned)}"
    dwell_text = f"{middle_dwell_ms / 1000.0:.2f}s"
    if middle_dwell_ms < abnormal_threshold:
        return (
            "AP乒乓切换异常",
            True,
            f"{sequence}，中间 AP 驻留 {dwell_text}，明显小于配置切换时间 {switch_ms}ms。",
        )
    if middle_dwell_ms <= critical_upper:
        return (
            "临界回切",
            False,
            f"{sequence}，中间 AP 驻留 {dwell_text}，接近配置切换时间 {switch_ms}ms，不计入乒乓异常。",
        )
    return (
        "普通回切事件",
        False,
        f"{sequence}，中间 AP 驻留 {dwell_text}，已超过配置切换时间 {switch_ms}ms，不计入乒乓异常。",
    )


def _set_pingpong_fields(
    row: dict[str, object],
    group_index: int,
    pingpong_type: str,
    is_ap_return_event: bool,
    is_abnormal: bool,
    return_duration_ms: int,
    middle_dwell_ms: int,
    previous: dict[str, object],
    middle: dict[str, object],
    returned: dict[str, object],
    reason: str,
) -> None:
    row["is_ap_return_event"] = is_ap_return_event
    row["is_pingpong_abnormal"] = is_abnormal
    row["pingpong_type"] = pingpong_type
    row["pingpong_group_id"] = f"PP{group_index:04d}"
    row["pingpong_return_duration_ms"] = return_duration_ms
    row["middle_ap_dwell_ms"] = middle_dwell_ms
    row["previous_ap"] = _segment_ap_label(previous)
    row["middle_ap"] = _segment_ap_label(middle)
    row["return_ap"] = _segment_ap_label(returned)
    row["pingpong_count"] = group_index
    row["pingpong_judgment_reason"] = reason


def _segment_ap_label(row: dict[str, object]) -> str:
    ap_name = str(row.get("peer_ap_name") or "").strip()
    peer = format_mac_h3c(row.get("active_peer_mac")) if row.get("active_peer_mac") else ""
    label = ap_name or peer or "-"
    station = str(row.get("peer_site") or "").strip()
    return f"{label} / {station}" if station else label


def _pingpong_return_window_ms(row: dict[str, object]) -> int:
    configured = _positive_int_or_default(row.get("pingpong_return_window_ms"), 0)
    if configured > 0:
        return configured
    switch_ms = _positive_int_or_default(row.get("main_link_switch_time_ms"), 2500)
    tolerance_ms = _positive_int_or_default(row.get("pingpong_tolerance_ms"), 500)
    return max(8000, 3 * (switch_ms + tolerance_ms))


def _segment_duration_ms(row: dict[str, object]) -> int:
    value = _float(row.get("main_link_duration_seconds"))
    if value is not None:
        return max(int(round(value * 1000)), 0)
    elapsed = _elapsed_ms(row.get("build_start_time"), row.get("build_end_time"))
    return max(elapsed or 0, 0)


def _elapsed_ms(start: object, end: object) -> int | None:
    try:
        start_dt = datetime.fromisoformat(str(start or ""))
        end_dt = datetime.fromisoformat(str(end or ""))
    except ValueError:
        return None
    return max(int(round((end_dt - start_dt).total_seconds() * 1000)), 0)


def _positive_int_or_default(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _neighbor_segments(rows: list[dict[str, object]], index: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    if index > 0:
        result.append(rows[index - 1])
    if index + 1 < len(rows):
        result.append(rows[index + 1])
    return result


def _same_switch_scope(left: dict[str, object], right: dict[str, object]) -> bool:
    return left.get("source_file_id") == right.get("source_file_id") and left.get("radio") == right.get("radio")


def _physical_ap_key(row: dict[str, object]) -> str:
    ap_mac = _canonical_mac(row.get("peer_ap_mac"))
    if ap_mac:
        return f"ap_mac:{ap_mac}"
    peer_mac = _canonical_mac(row.get("peer_mac_normalized") or row.get("peer_mac_raw") or row.get("peer_mac") or row.get("active_peer_mac"))
    return f"peer_mac:{peer_mac}" if peer_mac else ""


def _first_nonempty(values: list[object]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return round(sum(finite) / len(finite), 3) if finite else ""


def _minimum(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return min(finite) if finite else ""


def _maximum(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return max(finite) if finite else ""


def _peer_identity_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(peer_identity_status, ''), 'unresolved') AS status,
               COUNT(*) AS row_count
        FROM mesh_links
        GROUP BY COALESCE(NULLIF(peer_identity_status, ''), 'unresolved')
        """
    ).fetchall()
    counts = {"matched": 0, "unresolved": 0, "ambiguous": 0}
    for row in rows:
        status = str(row["status"] or "unresolved")
        counts[status] = counts.get(status, 0) + int(row["row_count"] or 0)
    return counts


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    if table not in {"mesh_links", "active_points", "switch_events"}:
        raise ValueError(f"Unsupported MESH count table: {table}")
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _mesh_fact_fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    table_columns = {
        "mesh_links": [
            str(row[1])
            for row in conn.execute("PRAGMA table_info(mesh_links)").fetchall()
            if str(row[1]) not in _MESH_LINK_IDENTITY_PROJECTION_COLUMNS
        ],
        "switch_events": [
            str(row[1])
            for row in conn.execute("PRAGMA table_info(switch_events)").fetchall()
        ],
    }
    for table, columns in table_columns.items():
        digest.update(table.encode("ascii"))
        digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
        cursor = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY id"
        )
        while batch := cursor.fetchmany(2048):
            for row in batch:
                digest.update(
                    json.dumps(
                        list(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                )
                digest.update(b"\n")
    return digest.hexdigest()


def _query_status_counts(
    conn: sqlite3.Connection,
    sql: str,
) -> dict[str, int]:
    counts = {"matched": 0, "unresolved": 0, "ambiguous": 0}
    for row in conn.execute(sql).fetchall():
        status = str(row["status"] or "unresolved")
        counts[status] = counts.get(status, 0) + int(row["row_count"] or 0)
    return counts


_VERIFIED_LINK_PROJECTION = """
    COALESCE(l.peer_ap_name, '') = COALESCE(pm.peer_ap_name, '')
    AND COALESCE(l.peer_ap_mac, '') = COALESCE(pm.peer_ap_mac, '')
    AND COALESCE(l.peer_site, '') = COALESCE(pm.peer_site, '')
    AND COALESCE(l.peer_section, '') = COALESCE(pm.peer_section, '')
    AND COALESCE(l.peer_location, '') = COALESCE(pm.peer_location, '')
    AND COALESCE(l.peer_direction, '') = COALESCE(pm.peer_direction, '')
    AND l.peer_radio_id IS pm.peer_radio_id
    AND COALESCE(l.peer_radio, '') = COALESCE(pm.peer_radio_label, '')
    AND COALESCE(l.peer_radio_label, '') = COALESCE(pm.peer_radio_label, '')
    AND COALESCE(l.peer_radio_mac, '') = COALESCE(pc.peer_radio_mac, l.peer_mac_normalized, '')
    AND COALESCE(l.peer_match_rule, '') = COALESCE(pm.match_rule, 'unresolved')
    AND COALESCE(l.peer_match_confidence, 0) = COALESCE(pm.match_confidence, 0)
    AND COALESCE(l.peer_resolve_source, '') = COALESCE(pc.source, 'unresolved')
    AND COALESCE(l.peer_identity_status, 'unresolved') = COALESCE(pm.identity_status, 'unresolved')
    AND COALESCE(l.peer_identity_source, '') = COALESCE(pm.identity_source, '')
    AND COALESCE(l.peer_identity_reason, '') = COALESCE(pm.identity_reason, 'exact_alias_not_found')
"""

_VERIFIED_ACTIVE_POINT_PROJECTION = """
    COALESCE(a.peer_ap_name, '') = COALESCE(pm.peer_ap_name, '')
    AND COALESCE(a.peer_site, '') = COALESCE(pm.peer_site, '')
    AND COALESCE(a.peer_section, '') = COALESCE(pm.peer_section, '')
    AND COALESCE(a.peer_location, '') = COALESCE(pm.peer_location, '')
    AND COALESCE(a.peer_direction, '') = COALESCE(pm.peer_direction, '')
    AND COALESCE(a.peer_radio, '') = COALESCE(pm.peer_radio_label, '')
    AND COALESCE(a.peer_radio_label, '') = COALESCE(pm.peer_radio_label, '')
"""


def _peer_identity_remap_summary(
    conn: sqlite3.Connection,
    *,
    before: dict[str, int],
    after: dict[str, int],
    mapping_count: int,
    identity_index_revision: int,
    link_row_count_before: int,
    active_point_row_count_before: int,
    switch_event_row_count_before: int,
    fact_fingerprint_before: str,
    fact_fingerprint_after: str,
) -> dict[str, object]:
    mapping_status = _query_status_counts(
        conn,
        """
        SELECT COALESCE(NULLIF(identity_status, ''), 'unresolved') AS status,
               COUNT(*) AS row_count
        FROM mesh_peer_mapping
        GROUP BY COALESCE(NULLIF(identity_status, ''), 'unresolved')
        """,
    )
    target_link_status = _query_status_counts(
        conn,
        """
        SELECT COALESCE(NULLIF(pm.identity_status, ''), 'unresolved') AS status,
               COUNT(*) AS row_count
        FROM mesh_links l
        JOIN mesh_peer_mapping pm ON pm.peer_mac_normalized = l.peer_mac_normalized
        GROUP BY COALESCE(NULLIF(pm.identity_status, ''), 'unresolved')
        """,
    )
    persisted_link_status = _query_status_counts(
        conn,
        f"""
        SELECT COALESCE(NULLIF(pm.identity_status, ''), 'unresolved') AS status,
               COUNT(*) AS row_count
        FROM mesh_links l
        JOIN mesh_peer_mapping pm ON pm.peer_mac_normalized = l.peer_mac_normalized
        LEFT JOIN mesh_peer_resolve_cache pc ON pc.peer_mac = l.peer_mac_normalized
        WHERE {_VERIFIED_LINK_PROJECTION}
        GROUP BY COALESCE(NULLIF(pm.identity_status, ''), 'unresolved')
        """,
    )
    active_point_status = _query_status_counts(
        conn,
        """
        SELECT COALESCE(NULLIF(pm.identity_status, ''), 'unresolved') AS status,
               COUNT(*) AS row_count
        FROM active_points a
        JOIN mesh_peer_mapping pm ON pm.peer_mac_normalized = a.peer_mac_normalized
        GROUP BY COALESCE(NULLIF(pm.identity_status, ''), 'unresolved')
        """,
    )
    source_ids = str(
        conn.execute(
            """
            SELECT COALESCE(GROUP_CONCAT(source_file_id), '')
            FROM (SELECT DISTINCT source_file_id FROM mesh_links ORDER BY source_file_id)
            """
        ).fetchone()[0]
        or ""
    )
    distinct_link_peer_count = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT peer_mac_normalized)
            FROM mesh_links
            WHERE length(peer_mac_normalized) = 12
              AND lower(peer_mac_normalized) = peer_mac_normalized
              AND peer_mac_normalized NOT GLOB '*[^0-9a-f]*'
            """
        ).fetchone()[0]
    )
    covered_link_peer_count = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT l.peer_mac_normalized)
            FROM mesh_links l
            JOIN mesh_peer_mapping pm ON pm.peer_mac_normalized = l.peer_mac_normalized
            """
        ).fetchone()[0]
    )
    covered_link_row_count = sum(target_link_status.values())
    updated_link_row_count = sum(persisted_link_status.values())
    covered_active_point_row_count = sum(active_point_status.values())
    updated_active_point_row_count = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM active_points a
            JOIN mesh_peer_mapping pm ON pm.peer_mac_normalized = a.peer_mac_normalized
            WHERE {_VERIFIED_ACTIVE_POINT_PROJECTION}
            """
        ).fetchone()[0]
    )
    link_row_count = _table_row_count(conn, "mesh_links")
    active_point_row_count = _table_row_count(conn, "active_points")
    switch_event_row_count = _table_row_count(conn, "switch_events")
    persisted_mapping_count = _table_row_count_for_mapping(conn)
    invalid_mapping_key_count = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM mesh_peer_mapping
            WHERE length(peer_mac_normalized) != 12
               OR lower(peer_mac_normalized) != peer_mac_normalized
               OR peer_mac_normalized GLOB '*[^0-9a-f]*'
            """
        ).fetchone()[0]
    )
    return {
        "before": before,
        "after": after,
        "mapping_count": mapping_count,
        "persisted_mapping_count": persisted_mapping_count,
        "matched_mapping_count": mapping_status.get("matched", 0),
        "unresolved_mapping_count": mapping_status.get("unresolved", 0),
        "ambiguous_mapping_count": mapping_status.get("ambiguous", 0),
        "invalid_mapping_key_count": invalid_mapping_key_count,
        "distinct_link_peer_count": distinct_link_peer_count,
        "covered_peer_count": covered_link_peer_count,
        "unmatched_link_peer_count": max(
            distinct_link_peer_count - covered_link_peer_count,
            0,
        ),
        "link_row_count_before": link_row_count_before,
        "link_row_count": link_row_count,
        "covered_link_row_count": covered_link_row_count,
        "updated_link_row_count": updated_link_row_count,
        "target_matched_link_row_count": target_link_status.get("matched", 0),
        "persisted_matched_link_row_count": persisted_link_status.get("matched", 0),
        "matched_link_row_count": after.get("matched", 0),
        "unresolved_link_row_count": after.get("unresolved", 0),
        "ambiguous_link_row_count": after.get("ambiguous", 0),
        "active_point_row_count_before": active_point_row_count_before,
        "active_point_row_count": active_point_row_count,
        "covered_active_point_row_count": covered_active_point_row_count,
        "updated_active_point_row_count": updated_active_point_row_count,
        "matched_active_point_row_count": active_point_status.get("matched", 0),
        "unresolved_active_point_row_count": active_point_status.get("unresolved", 0),
        "ambiguous_active_point_row_count": active_point_status.get("ambiguous", 0),
        "switch_event_row_count_before": switch_event_row_count_before,
        "switch_event_row_count": switch_event_row_count,
        "fact_fingerprint_before": fact_fingerprint_before,
        "fact_fingerprint_after": fact_fingerprint_after,
        "facts_unchanged": fact_fingerprint_before == fact_fingerprint_after,
        "identity_index_revision": int(identity_index_revision),
        "source_file_id": source_ids,
        "validation_status": "passed",
    }


def _table_row_count_for_mapping(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM mesh_peer_mapping").fetchone()[0])


def _validate_peer_identity_remap(summary: dict[str, object]) -> None:
    details = {
        "source_file_id": summary.get("source_file_id", ""),
        "mapping_count": summary.get("mapping_count", 0),
        "matched_mapping_count": summary.get("matched_mapping_count", 0),
        "covered_peer_count": summary.get("covered_peer_count", 0),
        "target_link_rows": summary.get("target_matched_link_row_count", 0),
        "persisted_matched_rows": summary.get("persisted_matched_link_row_count", 0),
        "identity_revision": summary.get("identity_index_revision", 0),
    }
    if (
        int(summary.get("persisted_mapping_count") or 0)
        != int(summary.get("mapping_count") or 0)
        or int(summary.get("invalid_mapping_key_count") or 0) != 0
        or int(summary.get("unmatched_link_peer_count") or 0) != 0
    ):
        raise MeshIdentityRemapValidationError(
            "MESH_IDENTITY_REMAP_COVERAGE_MISMATCH",
            details,
        )
    if (
        int(summary.get("link_row_count_before") or 0)
        != int(summary.get("link_row_count") or 0)
        or int(summary.get("active_point_row_count_before") or 0)
        != int(summary.get("active_point_row_count") or 0)
        or int(summary.get("switch_event_row_count_before") or 0)
        != int(summary.get("switch_event_row_count") or 0)
        or not bool(summary.get("facts_unchanged"))
    ):
        raise MeshIdentityRemapValidationError(
            "MESH_IDENTITY_REMAP_FACT_MISMATCH",
            details,
        )
    target_matched = int(summary.get("target_matched_link_row_count") or 0)
    persisted_matched = int(summary.get("persisted_matched_link_row_count") or 0)
    if target_matched > 0 and persisted_matched == 0:
        raise MeshIdentityRemapValidationError(
            "MESH_IDENTITY_REMAP_ZERO_PERSISTED_MATCH",
            details,
        )
    if (
        int(summary.get("covered_link_row_count") or 0)
        != int(summary.get("updated_link_row_count") or 0)
        or int(summary.get("covered_active_point_row_count") or 0)
        != int(summary.get("updated_active_point_row_count") or 0)
        or target_matched != persisted_matched
    ):
        raise MeshIdentityRemapValidationError(
            "MESH_IDENTITY_REMAP_STATUS_MISMATCH",
            details,
        )


def _topology_projection_diagnostics(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    station_source_counts: dict[str, int] = {}
    section_source_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    station_resolved = 0
    section_resolved = 0
    total = 0
    for row in rows:
        total += 1
        station = str(row.get("peer_site") or "").strip()
        section = str(row.get("peer_section") or row.get("belong_section") or "").strip()
        station_source = str(row.get("station_source") or "unresolved") if station else "unresolved"
        section_source = str(row.get("section_source") or "unresolved") if section else "unresolved"
        station_source_counts[station_source] = station_source_counts.get(station_source, 0) + 1
        section_source_counts[section_source] = section_source_counts.get(section_source, 0) + 1
        station_resolved += int(bool(station))
        section_resolved += int(bool(section))
        for warning in str(row.get("topology_warning") or "").split(";"):
            code = warning.strip()
            if code:
                warning_counts[code] = warning_counts.get(code, 0) + 1
    return {
        "peer_total_count": total,
        "station_resolved_mapping_count": station_resolved,
        "station_unresolved_mapping_count": total - station_resolved,
        "section_resolved_mapping_count": section_resolved,
        "section_unresolved_mapping_count": total - section_resolved,
        "station_source_counts": station_source_counts,
        "section_source_counts": section_source_counts,
        "topology_warning_counts": warning_counts,
    }


def _merge_peer_identity_remap_summaries(
    summaries: list[dict[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {
        "before": {"matched": 0, "unresolved": 0, "ambiguous": 0},
        "after": {"matched": 0, "unresolved": 0, "ambiguous": 0},
        "mapping_count": 0,
        "source_counts": {},
        "peer_total_count": 0,
        "station_resolved_mapping_count": 0,
        "station_unresolved_mapping_count": 0,
        "section_resolved_mapping_count": 0,
        "section_unresolved_mapping_count": 0,
        "station_source_counts": {},
        "section_source_counts": {},
        "topology_warning_counts": {},
        "facts_unchanged": True,
        "validation_status": "passed",
    }
    additive_fields = (
        "persisted_mapping_count",
        "matched_mapping_count",
        "unresolved_mapping_count",
        "ambiguous_mapping_count",
        "invalid_mapping_key_count",
        "distinct_link_peer_count",
        "covered_peer_count",
        "unmatched_link_peer_count",
        "link_row_count_before",
        "link_row_count",
        "covered_link_row_count",
        "updated_link_row_count",
        "target_matched_link_row_count",
        "persisted_matched_link_row_count",
        "matched_link_row_count",
        "unresolved_link_row_count",
        "ambiguous_link_row_count",
        "active_point_row_count_before",
        "active_point_row_count",
        "covered_active_point_row_count",
        "updated_active_point_row_count",
        "matched_active_point_row_count",
        "unresolved_active_point_row_count",
        "ambiguous_active_point_row_count",
        "switch_event_row_count_before",
        "switch_event_row_count",
        "peer_total_count",
        "station_resolved_mapping_count",
        "station_unresolved_mapping_count",
        "section_resolved_mapping_count",
        "section_unresolved_mapping_count",
    )
    before_fingerprints: list[str] = []
    after_fingerprints: list[str] = []
    source_file_ids: list[str] = []
    for summary in summaries:
        for phase in ("before", "after"):
            target = result[phase]
            source = summary.get(phase) or {}
            if isinstance(target, dict) and isinstance(source, dict):
                for status, count in source.items():
                    target[str(status)] = int(target.get(str(status), 0)) + int(
                        count or 0
                    )
        result["mapping_count"] = int(result["mapping_count"]) + int(
            summary.get("mapping_count") or 0
        )
        for field in additive_fields:
            result[field] = int(result.get(field) or 0) + int(
                summary.get(field) or 0
            )
        result["facts_unchanged"] = bool(result["facts_unchanged"]) and bool(
            summary.get("facts_unchanged")
        )
        result["identity_index_revision"] = max(
            int(result.get("identity_index_revision") or 0),
            int(summary.get("identity_index_revision") or 0),
        )
        before_fingerprints.append(str(summary.get("fact_fingerprint_before") or ""))
        after_fingerprints.append(str(summary.get("fact_fingerprint_after") or ""))
        if summary.get("source_file_id") not in (None, ""):
            source_file_ids.append(str(summary["source_file_id"]))
        target_sources = result["source_counts"]
        source_counts = summary.get("source_counts") or {}
        if isinstance(target_sources, dict) and isinstance(source_counts, dict):
            for source, count in source_counts.items():
                target_sources[str(source)] = int(
                    target_sources.get(str(source), 0)
                ) + int(count or 0)
        for field in (
            "station_source_counts",
            "section_source_counts",
            "topology_warning_counts",
        ):
            target = result[field]
            source = summary.get(field) or {}
            if isinstance(target, dict) and isinstance(source, dict):
                for key, count in source.items():
                    target[str(key)] = int(target.get(str(key), 0)) + int(count or 0)
    result["fact_fingerprint_before"] = hashlib.sha256(
        "\n".join(before_fingerprints).encode("ascii")
    ).hexdigest()
    result["fact_fingerprint_after"] = hashlib.sha256(
        "\n".join(after_fingerprints).encode("ascii")
    ).hexdigest()
    result["source_file_id"] = ",".join(source_file_ids)
    return result
