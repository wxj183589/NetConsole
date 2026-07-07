from __future__ import annotations

import hashlib
import gc
import json
import sqlite3
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.models.mesh_log_models import (
    EVENT_ACTIVE_SWITCH,
    EVENT_COUNTER_RESET,
    EVENT_MULTI_ACTIVE,
    EVENT_NO_ACTIVE,
    LINK_STATE_ACTIVE,
    MeshLogRecord,
    PAIRED_METRICS,
    MeshSwitchEvent,
    ParseIssue,
    format_mac_h3c,
)
from netconsole.repositories.mesh_catalog_repository import dt_text


SCHEMA_VERSION = "meshlog_compact_v2_single_log"
SCHEMA_KEY = "schema_" + "version"
PARSER_VERSION = "meshlog_compact_v2_single_log"
DERIVED_ANALYSIS_VERSION = "6"
DERIVED_ANALYSIS_KEY = "derived_analysis_version"
_METRIC_COLUMNS = tuple(dict.fromkeys(column for _name, left, right in PAIRED_METRICS for column in (left, right)))
_METRIC_SELECT_COLUMNS = ", ".join(_METRIC_COLUMNS)
_MESH_LINK_CHART_COLUMNS = (
    "id, source_file_id, session_id, sample_time, radio, link_state, peer_mac_raw, peer_mac_normalized, "
    "peer_ap_name, peer_site, peer_radio, peer_radio_label, establish_time, "
    + _METRIC_SELECT_COLUMNS
)
_ACTIVE_POINT_CHART_COLUMNS = (
    "link_id AS id, source_file_id, session_id, sample_time, radio, 'ACTIVE' AS link_state, "
    "peer_mac_raw, peer_mac_normalized, peer_ap_name, peer_site, peer_radio, peer_radio_label, "
    "establish_time, local_rssi_db, peer_rssi_db, local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy"
)
_MESH_EVENT_CHART_COLUMNS = (
    "id, event_time, event_type, radio, from_peer_mac, to_peer_mac, "
    "current_sample_time, observed_window_ms, details_json"
)


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


class MeshMrRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rebuilt_legacy_path: Path | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        if self.path.exists() and not self._is_compact_schema(self.path):
            self.rebuilt_legacy_path = self._archive_legacy_database()
        is_new_database = not self.path.exists()
        with self._connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_' || 'version', 'meshlog_compact_v2_single_log');
                INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', 'meshlog_compact_v2_single_log');
                INSERT OR REPLACE INTO meta(key, value) VALUES ('parser_version', 'meshlog_compact_v2_single_log');
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
                    sha256 TEXT NOT NULL UNIQUE,
                    file_size INTEGER NOT NULL,
                    file_mtime TEXT NULL,
                    imported_at TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    encoding TEXT DEFAULT '',
                    is_gzip INTEGER DEFAULT 0,
                    first_sample_time TEXT NULL,
                    last_sample_time TEXT NULL,
                    lines_read INTEGER DEFAULT 0,
                    records_parsed INTEGER DEFAULT 0,
                    records_skipped INTEGER DEFAULT 0,
                    duplicate_records INTEGER DEFAULT 0,
                    issue_count INTEGER DEFAULT 0,
                    error_message TEXT DEFAULT '',
                    file_exists INTEGER DEFAULT 1,
                    deleted_at TEXT DEFAULT '',
                    delete_error TEXT DEFAULT '',
                    file_status TEXT DEFAULT 'ok',
                    parsed_deleted_at TEXT DEFAULT '',
                    parsed_delete_error TEXT DEFAULT '',
                    source_file_order INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                    radio INTEGER NOT NULL,
                    sample_time TEXT NOT NULL,
                    device_time TEXT NULL,
                    sample_time_epoch_ms INTEGER NOT NULL,
                    timestamp_tag TEXT NULL,
                    raw_line_start INTEGER DEFAULT 0,
                    raw_line_end INTEGER DEFAULT 0,
                    raw_offset_start INTEGER DEFAULT 0,
                    raw_offset_end INTEGER DEFAULT 0,
                    UNIQUE(source_file_id, radio, sample_time)
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
                    peer_radio_id INTEGER NULL,
                    peer_radio TEXT DEFAULT '',
                    peer_radio_label TEXT DEFAULT '',
                    peer_radio_mac TEXT DEFAULT '',
                    peer_match_rule TEXT DEFAULT '',
                    peer_resolve_source TEXT DEFAULT 'unresolved',
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
                    peer_location TEXT DEFAULT '',
                    peer_direction TEXT DEFAULT '',
                    match_rule TEXT DEFAULT '',
                    match_confidence INTEGER DEFAULT 0,
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
            self._ensure_column(conn, "mesh_links", "peer_ap_name", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_ap_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_site", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_id", "INTEGER NULL")
            self._ensure_column(conn, "mesh_links", "peer_radio", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_label", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_radio_mac", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_match_rule", "TEXT DEFAULT ''")
            self._ensure_column(conn, "mesh_links", "peer_resolve_source", "TEXT DEFAULT 'unresolved'")
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_peer_ap ON mesh_links(peer_ap_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_peer_site ON mesh_links(peer_site)")
            self._backfill_peer_columns(conn)
            if is_new_database:
                conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))
            self._update_meta_counts(conn)
        conn.close()

    @staticmethod
    def _is_compact_schema(path: Path) -> bool:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(path)
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

    def _archive_legacy_database(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.path.with_name(f"{self.path.name}.legacy_{timestamp}")
        counter = 1
        while target.exists():
            target = self.path.with_name(f"{self.path.name}.legacy_{timestamp}_{counter}")
            counter += 1
        self.path.replace(target)
        for suffix in ("-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists():
                sidecar.replace(target.with_name(target.name + suffix))
        return target

    def _reset_to_compact_schema(self) -> None:
        if self.path.exists():
            self.rebuilt_legacy_path = self._archive_legacy_database()
        self.initialize()

    def _is_index_database(self) -> bool:
        return self.path.name == "mesh.sqlite" and self.path.parent.name != "parsed"

    def _single_log_db_path(self, archived_path: Path, sha256: str) -> Path:
        parsed_dir = self.path.parent / "parsed"
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
    ) -> int:
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
                    parser_version, parse_status, encoding, is_gzip, first_sample_time, last_sample_time,
                    lines_read, records_parsed, records_skipped, duplicate_records, issue_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    parser_version,
                    parse_status,
                    "",
                    1 if archived_path.name.lower().endswith(".gz") else 0,
                    dt_text(first_sample_time),
                    dt_text(last_sample_time),
                    lines_read,
                    records_parsed,
                    records_skipped,
                    duplicate_records,
                    issue_count,
                    error_message,
                ),
            )
            source_file_id = int(cursor.lastrowid)
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
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_files (
                    mr_id, original_path, archived_path, parsed_db_path, parsed_db_size, db_schema_version,
                    original_filename, archived_filename, sha256,
                    file_size, file_mtime, imported_at, parser_version, parse_status, encoding, is_gzip,
                    first_sample_time, last_sample_time, lines_read, records_parsed, records_skipped,
                    duplicate_records, issue_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    duplicate_records,
                    issue_count,
                    error_message,
                ),
            )
            source_file_id = int(cursor.lastrowid)
            file_order = min((int(record.source_file_order or 0) for record in records if int(record.source_file_order or 0) > 0), default=source_file_id)
            conn.execute("UPDATE source_files SET source_file_order = ? WHERE id = ?", (file_order, source_file_id))
            sample_rows = {}
            for record in records:
                sample_rows[(source_file_id, record.radio, dt_text(record.sample_time) or "")] = (
                    source_file_id,
                    record.radio,
                    dt_text(record.sample_time),
                    None,
                    record.sample_time_epoch_ms or int(record.sample_time.timestamp() * 1000),
                    record.timestamp_tag,
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
            sample_ids: dict[tuple[int, int, str], int] = {}
            keys = list(sample_rows)
            for start in range(0, len(keys), 400):
                chunk = keys[start : start + 400]
                rows = conn.execute(
                    f"SELECT id, source_file_id, radio, sample_time FROM samples WHERE {' OR '.join('(source_file_id = ? AND radio = ? AND sample_time = ?)' for _ in chunk)}",
                    [value for key in chunk for value in key],
                ).fetchall()
                sample_ids.update({(int(row["source_file_id"]), int(row["radio"]), row["sample_time"]): int(row["id"]) for row in rows})
            link_rows = []
            for record in records:
                sample_time = dt_text(record.sample_time)
                record.sample_id = sample_ids.get((source_file_id, record.radio, sample_time))
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
                        record.peer_mac_normalized,
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
        result: list[dict[str, object]] = []
        for row in rows:
            data = dict(row)
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
            result.append(data)
        return result

    def get_source_file(self, source_file_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM source_files WHERE id = ?", (source_file_id,)).fetchone()
        return dict(row) if row else None

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
                SELECT ml.*, sf.archived_filename, sf.archived_path
                FROM mesh_links ml
                LEFT JOIN source_files sf ON sf.id = ml.source_file_id
                {where}
                ORDER BY ml.record_seq ASC, ml.source_file_order ASC, ml.source_line_number ASC, ml.id ASC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        result: list[dict[str, object]] = []
        group_indexes: dict[tuple[object, object], int] = {}
        for row in rows:
            data = _with_synthetic_payload(row)
            key = (data.get("sample_time"), data.get("radio"))
            if key not in group_indexes:
                group_indexes[key] = len(group_indexes)
            data["sample_group_index"] = group_indexes[key]
            result.append(data)
        return int(total), result

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
            rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"""
                    SELECT {_MESH_LINK_CHART_COLUMNS}
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
            rows: list[dict[str, object]] = []
            events: list[dict[str, object]] = []
            anchor = None
            interval: float | None = None
            gap: float | None = None
            for repo in self._detail_repos():
                payload = repo.query_peer_chart_segments(anchor_link_id, None)
                if payload.get("anchor") is not None and anchor is None:
                    anchor = payload.get("anchor")
                run = dict(payload.get("run_segment") or {})
                rows.extend(list(run.get("rows") or []))
                events.extend(list(run.get("events") or []))
                interval = interval or run.get("estimated_interval_seconds")
                gap = gap or run.get("continuity_gap_seconds")
            rows.sort(key=lambda row: (str(row.get("sample_time") or ""), int(row.get("radio") or 0), int(row.get("id") or 0)))
            run_segment = _segment_payload(anchor, rows, interval, gap)
            run_segment["events"] = events
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, rows, interval, gap), "run_segment": run_segment}
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id, source_file_id=source_file_id)
        if anchor is None or start_time is None or end_time is None:
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, [], interval, gap), "run_segment": _segment_payload(anchor, [], interval, gap)}
        return self._query_peer_chart_segments_in_range(anchor, start_time, end_time, interval, gap, partial=False, full_loading=False, source_file_id=source_file_id)

    def query_active_link_chart_segments(self, source_file_id: int | str | None = None, radio: int | None = None) -> dict[str, object]:
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                if repo is None:
                    return {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
                payload = repo.query_active_link_chart_segments(None, radio)
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
                payload = repo.query_active_link_chart_segments(None, radio)
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
            run_segment["events"] = events
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, [], interval, gap), "run_segment": run_segment}
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("radio = ?")
            values.append(int(radio))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        events_where = where
        with self._connect() as conn:
            rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"""
                    SELECT {_ACTIVE_POINT_CHART_COLUMNS}
                    FROM active_points
                    {where}
                    ORDER BY radio ASC, sample_time ASC, id ASC
                    """,
                    values,
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT {_MESH_EVENT_CHART_COLUMNS}
                    FROM switch_events
                    {events_where}
                    ORDER BY radio ASC, event_time ASC, id ASC
                    """,
                    values,
                ).fetchall()
            ]
        active_count = len(rows)
        anchor = next((row for row in rows if row.get("link_state") == LINK_STATE_ACTIVE), rows[0] if rows else None)
        interval, gap = _interval_and_threshold([str(row.get("sample_time") or "") for row in rows if row.get("sample_time")])
        run_segment = _segment_payload(anchor, rows, interval, gap)
        peer_segment = _segment_payload(anchor, [], interval, gap)
        for segment in (peer_segment, run_segment):
            segment["partial"] = False
            segment["full_loading"] = False
            segment["full_active_payload"] = True
            segment["query_active_count"] = active_count
        run_segment["events"] = events
        return {"anchor": anchor, "peer_segment": peer_segment, "run_segment": run_segment}

    def query_active_link_build_order(self, source_file_id: int | str | None = None, radio: int | None = None) -> list[dict[str, object]]:
        if self._is_index_database():
            if source_file_id not in (None, ""):
                repo = self._detail_repo_for_source(source_file_id)
                rows = repo.query_active_link_build_order(None, radio) if repo else []
                for row in rows:
                    row["source_file_id"] = int(source_file_id)
                return rows
            rows: list[dict[str, object]] = []
            for source_id, repo in self._detail_repo_items():
                detail_rows = repo.query_active_link_build_order(None, radio)
                for row in detail_rows:
                    row["source_file_id"] = source_id
                rows.extend(detail_rows)
            for index, row in enumerate(rows, start=1):
                row["sequence"] = index
            return rows
        clauses: list[str] = []
        values: list[object] = []
        if source_file_id not in (None, ""):
            clauses.append("s.source_file_id = ?")
            values.append(int(source_file_id))
        if radio is not None:
            clauses.append("s.radio = ?")
            values.append(int(radio))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT s.id, s.source_file_id, s.radio, s.peer_mac_normalized, s.peer_mac,
                           s.peer_ap_name, s.belong_station AS peer_site, '' AS peer_radio,
                           s.start_time AS build_start_time, s.end_time AS build_end_time,
                           s.duration_sec AS main_link_duration_seconds,
                           s.sample_count, s.avg_rssi AS avg_mr_rssi, s.min_rssi AS min_mr_rssi,
                           s.max_rssi AS max_mr_rssi, s.event_type AS build_result,
                           sf.archived_filename AS source_file
                    FROM active_segments s
                    LEFT JOIN source_files sf ON sf.id = s.source_file_id
                    {where}
                    ORDER BY s.radio ASC, s.start_time ASC, s.id ASC
                    """,
                    values,
                ).fetchall()
            ]
        result: list[dict[str, object]] = []
        for sequence, row in enumerate(rows, start=1):
            result.append(
                {
                    "sequence": sequence,
                    "radio": row.get("radio"),
                    "active_peer_mac": row.get("peer_mac_normalized") or row.get("peer_mac") or "",
                    "peer_ap_name": row.get("peer_ap_name") or "",
                    "peer_site": row.get("peer_site") or "",
                    "peer_radio": row.get("peer_radio") or "",
                    "build_start_time": row.get("build_start_time") or "",
                    "build_end_time": row.get("build_end_time") or "",
                    "main_link_duration_seconds": row.get("main_link_duration_seconds") or "",
                    "reported_duration_seconds": "",
                    "sample_count": row.get("sample_count") or "",
                    "avg_mr_rssi": row.get("avg_mr_rssi") or "",
                    "min_mr_rssi": row.get("min_mr_rssi") or "",
                    "max_mr_rssi": row.get("max_mr_rssi") or "",
                    "avg_tx_busy": "",
                    "avg_rx_busy": "",
                    "build_result": "short" if (_float(row.get("main_link_duration_seconds")) or 0.0) < 2.0 else "normal",
                    "source_file": row.get("source_file") or "",
                }
            )
        return result

    def query_peer_chart_initial_segments(self, anchor_link_id: int, visible_samples: int = 300, margin_samples: int = 60, source_file_id: int | str | None = None) -> dict[str, object]:
        if self._is_index_database() and source_file_id not in (None, ""):
            repo = self._detail_repo_for_source(source_file_id)
            return repo.query_peer_chart_initial_segments(anchor_link_id, visible_samples, margin_samples, None) if repo else {"anchor": None, "peer_segment": _segment_payload(None, [], None, None), "run_segment": _segment_payload(None, [], None, None)}
        with self._connect() as conn:
            anchor_row = conn.execute(f"SELECT {_MESH_LINK_CHART_COLUMNS} FROM mesh_links WHERE id = ?", (anchor_link_id,)).fetchone()
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
        with self._connect() as conn:
            peer_rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"SELECT {_MESH_LINK_CHART_COLUMNS} FROM mesh_links WHERE {' AND '.join(peer_clauses)} ORDER BY sample_time ASC, id ASC",
                    peer_values,
                ).fetchall()
            ]
            run_rows = [
                _with_synthetic_payload(row)
                for row in conn.execute(
                    f"""
                    SELECT {_MESH_LINK_CHART_COLUMNS}
                    FROM mesh_links
                    WHERE radio = ? AND sample_time >= ? AND sample_time <= ? AND (? IS NULL OR session_id = ?) AND (? IS NULL OR source_file_id = ?)
                    ORDER BY sample_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time, anchor.get("session_id"), anchor.get("session_id"), effective_source_file_id, effective_source_file_id),
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
            anchor_row = conn.execute(f"SELECT {_MESH_LINK_CHART_COLUMNS} FROM mesh_links WHERE id = ?", (anchor_link_id,)).fetchone()
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
            if conn is not None:
                conn.close()
                conn = None
            self._reset_to_compact_schema()
            return False
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
                row.get("peer_mac_normalized"),
                row.get("peer_ap_name") or "",
                row.get("peer_ap_mac") or "",
                row.get("peer_radio_id"),
                row.get("peer_radio_label") or "",
                row.get("peer_radio_mac") or "",
                row.get("peer_site") or "",
                row.get("peer_location") or "",
                row.get("peer_direction") or "",
                row.get("match_rule") or "",
                int(row.get("match_confidence") or 0),
                now,
            )
            for row in rows
            if row.get("peer_mac_normalized")
        ]
        if not values:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO mesh_peer_mapping (
                    peer_mac_normalized, peer_ap_name, peer_ap_mac, peer_radio_id, peer_radio_label,
                    peer_site, peer_location, peer_direction, match_rule, match_confidence, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_mac_normalized) DO UPDATE SET
                    peer_ap_name = excluded.peer_ap_name,
                    peer_ap_mac = excluded.peer_ap_mac,
                    peer_radio_id = excluded.peer_radio_id,
                    peer_radio_label = excluded.peer_radio_label,
                    peer_site = excluded.peer_site,
                    peer_location = excluded.peer_location,
                    peer_direction = excluded.peer_direction,
                    match_rule = excluded.match_rule,
                    match_confidence = excluded.match_confidence,
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
                        value[9] or "unresolved",
                        value[11],
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
                    peer_radio_id = (SELECT peer_radio_id FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized),
                    peer_radio = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_radio_label = COALESCE((SELECT peer_radio_label FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_match_rule = COALESCE((SELECT match_rule FROM mesh_peer_mapping pm WHERE pm.peer_mac_normalized = mesh_links.peer_mac_normalized), ''),
                    peer_radio_mac = COALESCE((SELECT peer_radio_mac FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''),
                    peer_resolve_source = COALESCE((SELECT source FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), 'unresolved')
                WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
                """
            )

    def rebuild_link_aggregates(self, bucket_seconds: tuple[int, ...] = (1, 10, 30, 60), should_cancel=None) -> None:
        return None

    def query_link_aggregates(self, bucket_seconds: int = 10, limit: int = 5000, offset: int = 0) -> list[dict[str, object]]:
        return []

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True, temp_store_memory=True)

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
    def _backfill_peer_columns(conn: sqlite3.Connection) -> None:
        now = dt_text(datetime.now()) or ""
        conn.execute(
            """
            INSERT OR IGNORE INTO mesh_peer_resolve_cache (
                peer_mac, peer_ap_name, peer_site, peer_radio, peer_radio_mac, source, updated_at
            )
            SELECT peer_mac_normalized, peer_ap_name, peer_site, peer_radio_label, peer_mac_normalized, match_rule, ?
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
                peer_radio = COALESCE(NULLIF((SELECT peer_radio FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_radio, peer_radio_label, ''),
                peer_radio_label = COALESCE(NULLIF(peer_radio_label, ''), peer_radio, ''),
                peer_radio_mac = COALESCE(NULLIF((SELECT peer_radio_mac FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_radio_mac, ''),
                peer_resolve_source = COALESCE(NULLIF((SELECT source FROM mesh_peer_resolve_cache pc WHERE pc.peer_mac = mesh_links.peer_mac_normalized), ''), peer_resolve_source, 'unresolved')
            WHERE peer_mac_normalized IS NOT NULL AND trim(peer_mac_normalized) != ''
            """
        )

    def _rebuild_link_aggregates(self, conn: sqlite3.Connection, should_cancel=None, bucket_seconds: tuple[int, ...] = (1, 10, 30, 60)) -> None:
        return None

    def _rebuild_active_points_segments_stats(self, conn: sqlite3.Connection, should_cancel=None) -> None:
        conn.execute(
            """
            INSERT INTO active_points (
                link_id, sample_id, source_file_id, session_id, sample_time, device_time, radio,
                peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_site, peer_radio,
                peer_radio_label, establish_time, duration_text, duration_seconds, link_count,
                local_rssi_db, peer_rssi_db, local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy,
                local_noise_dbm, peer_noise_dbm, local_signal_dbm, peer_signal_dbm,
                raw_line_start, raw_line_end, raw_offset_start, raw_offset_end
            )
            SELECT
                ml.id, ml.sample_id, ml.source_file_id, COALESCE(ml.session_id, ''), ml.sample_time, s.device_time, ml.radio,
                ml.peer_mac_raw, COALESCE(ml.peer_mac_normalized, ''), COALESCE(ml.peer_mac, ''),
                COALESCE(ml.peer_ap_name, ''), COALESCE(ml.peer_site, ''), COALESCE(ml.peer_radio, ''),
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
                   peer_ap_name, peer_site, peer_radio_label, local_rssi_db
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
            finite_rssi = [value for value in rssi_values if value is not None]
            avg_rssi = round(sum(finite_rssi) / len(finite_rssi), 3) if finite_rssi else None
            duration = _seconds_between(str(first["sample_time"]), str(last["sample_time"]))
            segment_rows.append(
                (
                    first["radio"],
                    first["peer_mac_raw"] or "",
                    first["peer_mac_normalized"] or "",
                    first["peer_ap_name"] or "",
                    first["peer_site"] or "",
                    "",
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
            if rssi is None:
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
        issue_rows = conn.execute("SELECT line_number, severity, issue_type, message FROM parse_issues").fetchall()
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
                    seconds = max((datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(previous["sample_time"])).total_seconds(), 0.0)
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
            SELECT id, source_file_id, source_line_number, radio, sample_time, link_state,
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
                            format_mac_h3c(previous["peer_mac_normalized"]) if previous["peer_mac_normalized"] else previous["peer_mac_raw"],
                            format_mac_h3c(row["peer_mac_normalized"]) if row["peer_mac_normalized"] else row["peer_mac_raw"],
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
                key = (row["radio"], row["sample_time"])
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
                    event.from_peer_mac,
                    event.to_peer_mac,
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


def _segment_payload(anchor: dict[str, object] | None, rows: list[dict[str, object]], interval: float | None, gap: float | None) -> dict[str, object]:
    return {
        "anchor": anchor,
        "rows": rows,
        "segment_start": rows[0]["sample_time"] if rows else None,
        "segment_end": rows[-1]["sample_time"] if rows else None,
        "estimated_interval_seconds": interval,
        "continuity_gap_seconds": gap,
    }


def _seconds_between(previous: str, current: str) -> float:
    try:
        return (datetime.fromisoformat(current) - datetime.fromisoformat(previous)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _active_build_order_row(sequence: int, rows: list[dict[str, object]], sample_interval: float) -> dict[str, object]:
    first = rows[0]
    last = rows[-1]
    duration = max(_seconds_between(str(first.get("sample_time") or ""), str(last.get("sample_time") or "")) + max(sample_interval, 0.0), 0.0)
    reported_values = [value for row in rows if (value := _float(row.get("duration_seconds"))) is not None]
    rssi_values = [_float(row.get("local_rssi_db")) for row in rows]
    tx_values = [_float(row.get("local_tx_busy")) for row in rows]
    rx_values = [_float(row.get("local_rx_busy")) for row in rows]
    return {
        "sequence": sequence,
        "radio": first.get("radio"),
        "active_peer_mac": first.get("peer_mac_normalized") or first.get("peer_mac_raw") or "",
        "peer_ap_name": first.get("peer_ap_name") or "",
        "peer_site": first.get("peer_site") or "",
        "peer_radio": first.get("peer_radio_label") or first.get("peer_radio") or "",
        "build_start_time": first.get("sample_time") or "",
        "build_end_time": last.get("sample_time") or "",
        "main_link_duration_seconds": round(duration, 3),
        "reported_duration_seconds": max(reported_values) if reported_values else "",
        "sample_count": len(rows),
        "avg_mr_rssi": _average(rssi_values),
        "min_mr_rssi": _minimum(rssi_values),
        "max_mr_rssi": _maximum(rssi_values),
        "avg_tx_busy": _average(tx_values),
        "avg_rx_busy": _average(rx_values),
        "build_result": "normal" if duration >= 2.0 else "short",
        "source_file": first.get("archived_filename") or first.get("source_file_id") or "",
    }


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
