from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

from netconsole.models.mesh_log_models import (
    EVENT_ACTIVE_SWITCH,
    EVENT_COUNTER_RESET,
    EVENT_MULTI_ACTIVE,
    EVENT_NO_ACTIVE,
    LINK_STATE_ACTIVE,
    MeshLogRecord,
    MeshSwitchEvent,
    ParseIssue,
    format_mac_h3c,
)
from netconsole.repositories.mesh_catalog_repository import dt_text


SCHEMA_VERSION = "1"
SCHEMA_KEY = "schema_" + "version"
DERIVED_ANALYSIS_VERSION = "2"
DERIVED_ANALYSIS_KEY = "derived_analysis_version"


class MeshMrRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        is_new_database = not self.path.exists()
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_' || 'version', '1');
                CREATE TABLE IF NOT EXISTS source_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mr_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    archived_path TEXT NOT NULL,
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
                    error_message TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                    radio INTEGER NOT NULL,
                    sample_time TEXT NOT NULL,
                    sample_time_epoch_ms INTEGER NOT NULL,
                    timestamp_tag TEXT NULL,
                    UNIQUE(radio, sample_time)
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
                    source_line_number INTEGER NOT NULL,
                    raw_line TEXT NOT NULL,
                    radio INTEGER NOT NULL,
                    sample_time TEXT NOT NULL,
                    link_state_raw TEXT NOT NULL,
                    link_state TEXT NOT NULL,
                    peer_mac_raw TEXT NOT NULL,
                    peer_mac_normalized TEXT NULL,
                    establish_time TEXT NULL,
                    duration_text TEXT NOT NULL,
                    duration_seconds INTEGER NULL,
                    expected_duration_seconds INTEGER NULL,
                    duration_deviation_seconds INTEGER NULL,
                    link_count INTEGER NULL,
                    session_id TEXT NULL,
                    metrics_json TEXT NOT NULL,
                    deltas_json TEXT NOT NULL,
                    local_noise_dbm INTEGER NULL,
                    peer_noise_dbm INTEGER NULL,
                    local_signal_dbm INTEGER NULL,
                    peer_signal_dbm INTEGER NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS mesh_deltas (
                    link_id INTEGER PRIMARY KEY REFERENCES mesh_links(id) ON DELETE CASCADE,
                    deltas_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mesh_events (
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
                    source_line_number INTEGER DEFAULT 0
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
                    raw_line TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_samples_radio_time ON samples(radio, sample_time);
                CREATE INDEX IF NOT EXISTS idx_samples_time ON samples(sample_time);
                CREATE INDEX IF NOT EXISTS idx_links_sample ON mesh_links(sample_id);
                CREATE INDEX IF NOT EXISTS idx_links_peer ON mesh_links(peer_mac_normalized);
                CREATE INDEX IF NOT EXISTS idx_links_peer_radio_time ON mesh_links(peer_mac_normalized, radio, sample_time);
                CREATE INDEX IF NOT EXISTS idx_mesh_links_peer_radio_time ON mesh_links(peer_mac_normalized, radio, sample_time);
                CREATE INDEX IF NOT EXISTS idx_mesh_links_radio_time ON mesh_links(radio, sample_time);
                CREATE INDEX IF NOT EXISTS idx_mesh_links_radio_time_state ON mesh_links(radio, sample_time, link_state);
                CREATE INDEX IF NOT EXISTS idx_mesh_links_session_time ON mesh_links(session_id, sample_time);
                CREATE INDEX IF NOT EXISTS idx_links_state ON mesh_links(link_state);
                CREATE INDEX IF NOT EXISTS idx_links_session ON mesh_links(session_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_peer ON mesh_sessions(radio, peer_mac_normalized);
                CREATE INDEX IF NOT EXISTS idx_sessions_first ON mesh_sessions(first_sample_time);
                CREATE INDEX IF NOT EXISTS idx_sessions_last ON mesh_sessions(last_sample_time);
                CREATE INDEX IF NOT EXISTS idx_events_type_time ON mesh_events(event_type, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_radio_time ON mesh_events(radio, event_time);
                CREATE INDEX IF NOT EXISTS idx_mesh_events_radio_time ON mesh_events(radio, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_from_peer ON mesh_events(from_peer_mac);
                CREATE INDEX IF NOT EXISTS idx_events_to_peer ON mesh_events(to_peer_mac);
                CREATE INDEX IF NOT EXISTS idx_source_sha ON source_files(sha256);
                CREATE INDEX IF NOT EXISTS idx_source_time ON source_files(first_sample_time, last_sample_time);
                """
            )
            if is_new_database:
                conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))

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
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_files (
                    mr_id, original_path, archived_path, original_filename, archived_filename, sha256,
                    file_size, file_mtime, imported_at, parser_version, parse_status, encoding, is_gzip,
                    first_sample_time, last_sample_time, lines_read, records_parsed, records_skipped,
                    duplicate_records, issue_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mr_id,
                    str(original_path),
                    str(archived_path),
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
            sample_rows = {}
            for record in records:
                sample_rows[(record.radio, dt_text(record.sample_time) or "")] = (
                    source_file_id,
                    record.radio,
                    dt_text(record.sample_time),
                    record.sample_time_epoch_ms or int(record.sample_time.timestamp() * 1000),
                    record.timestamp_tag,
                )
            conn.executemany(
                "INSERT OR IGNORE INTO samples(source_file_id, radio, sample_time, sample_time_epoch_ms, timestamp_tag) VALUES (?, ?, ?, ?, ?)",
                list(sample_rows.values()),
            )
            sample_ids: dict[tuple[int, str], int] = {}
            keys = list(sample_rows)
            for start in range(0, len(keys), 400):
                chunk = keys[start : start + 400]
                rows = conn.execute(
                    f"SELECT id, radio, sample_time FROM samples WHERE {' OR '.join('(radio = ? AND sample_time = ?)' for _ in chunk)}",
                    [value for key in chunk for value in key],
                ).fetchall()
                sample_ids.update({(int(row["radio"]), row["sample_time"]): int(row["id"]) for row in rows})
            link_rows = []
            for record in records:
                sample_time = dt_text(record.sample_time)
                record.sample_id = sample_ids.get((record.radio, sample_time))
                record.source_file_id = source_file_id
                link_rows.append(
                    (
                        record.sample_id,
                        source_file_id,
                        record.source_line_number,
                        record.raw_line,
                        record.radio,
                        sample_time,
                        record.link_state_raw,
                        record.link_state,
                        record.peer_mac_raw,
                        record.peer_mac_normalized,
                        dt_text(record.establish_time),
                        record.duration_text,
                        record.duration_seconds,
                        record.expected_duration_seconds,
                        record.duration_deviation_seconds,
                        record.link_count,
                        record.session_id,
                        json.dumps(record.metrics, ensure_ascii=False),
                        json.dumps(record.deltas, ensure_ascii=False),
                        record.local_noise_dbm,
                        record.peer_noise_dbm,
                        record.local_signal_dbm,
                        record.peer_signal_dbm,
                        record.duplicate_hash,
                    )
                )
            conn.executemany(
                """
                INSERT OR IGNORE INTO mesh_links (
                    sample_id, source_file_id, source_line_number, raw_line, radio, sample_time,
                    link_state_raw, link_state, peer_mac_raw, peer_mac_normalized, establish_time,
                    duration_text, duration_seconds, expected_duration_seconds, duration_deviation_seconds,
                    link_count, session_id, metrics_json, deltas_json, local_noise_dbm, peer_noise_dbm,
                    local_signal_dbm, peer_signal_dbm, record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                link_rows,
            )
            self._insert_issues(conn, source_file_id, issues)
            return source_file_id

    def list_source_files(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM source_files ORDER BY COALESCE(first_sample_time, imported_at) ASC, id ASC").fetchall()
        return [dict(row) for row in rows]

    def query_links(self, limit: int, offset: int, filters: dict[str, object] | None = None) -> tuple[int, list[dict[str, object]]]:
        filters = filters or {}
        clauses: list[str] = []
        values: list[object] = []
        if filters.get("radio") is not None:
            clauses.append("radio = ?")
            values.append(filters["radio"])
        if filters.get("state"):
            clauses.append("link_state = ?")
            values.append(filters["state"])
        if filters.get("peer"):
            clauses.append("(peer_mac_normalized LIKE ? OR peer_mac_raw LIKE ?)")
            peer = f"%{filters['peer']}%"
            values.extend([peer, peer])
        if filters.get("keyword"):
            clauses.append("(raw_line LIKE ? OR peer_mac_raw LIKE ?)")
            keyword = f"%{filters['keyword']}%"
            values.extend([keyword, keyword])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count FROM mesh_links{where}", values).fetchone()["count"]
            rows = conn.execute(
                f"""
                WITH filtered AS (
                    SELECT ml.*,
                           DENSE_RANK() OVER (ORDER BY ml.sample_time ASC, ml.radio ASC) - 1 AS sample_group_index
                    FROM mesh_links ml
                    {where}
                )
                SELECT filtered.*, sf.archived_filename, sf.archived_path
                FROM filtered
                LEFT JOIN source_files sf ON sf.id = filtered.source_file_id
                ORDER BY filtered.sample_time ASC, filtered.radio ASC, filtered.id ASC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        return int(total), [dict(row) for row in rows]

    def query_events(self, limit: int, offset: int) -> tuple[int, list[dict[str, object]]]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM mesh_events").fetchone()["count"]
            rows = conn.execute("SELECT * FROM mesh_events ORDER BY event_time ASC, id ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return int(total), [dict(row) for row in rows]

    def query_issues(self, limit: int, offset: int) -> tuple[int, list[dict[str, object]]]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM parse_issues").fetchone()["count"]
            rows = conn.execute("SELECT * FROM parse_issues ORDER BY source_file ASC, line_number ASC, id ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return int(total), [dict(row) for row in rows]

    def get_link_by_id(self, link_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mesh_links WHERE id = ?", (link_id,)).fetchone()
        return dict(row) if row else None

    def query_peer_context_segment(self, anchor_link_id: int) -> dict[str, object]:
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
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM mesh_links WHERE {' AND '.join(clauses)} ORDER BY sample_time ASC, id ASC",
                    values,
                ).fetchall()
            ]
        return _segment_payload(anchor, rows, interval, gap)

    def query_run_context_segment(self, anchor_link_id: int) -> dict[str, object]:
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id)
        if anchor is None or start_time is None or end_time is None:
            payload = _segment_payload(None, [], None, None)
            payload["events"] = []
            return payload
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM mesh_links
                    WHERE radio = ? AND sample_time >= ? AND sample_time <= ?
                    ORDER BY sample_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time),
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM mesh_events
                    WHERE radio = ? AND (? IS NULL OR event_time >= ?) AND (? IS NULL OR event_time <= ?)
                    ORDER BY event_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, start_time, end_time, end_time),
                ).fetchall()
            ]
        payload = _segment_payload(anchor, rows, interval, gap)
        payload["events"] = events
        return payload

    def query_peer_chart_segments(self, anchor_link_id: int) -> dict[str, object]:
        anchor, start_time, end_time, interval, gap = self._locate_run_segment(anchor_link_id)
        if anchor is None or start_time is None or end_time is None:
            return {"anchor": anchor, "peer_segment": _segment_payload(anchor, [], interval, gap), "run_segment": _segment_payload(anchor, [], interval, gap)}
        peer_clauses = ["peer_mac_normalized = ?", "radio = ?", "sample_time >= ?", "sample_time <= ?"]
        peer_values: list[object] = [anchor.get("peer_mac_normalized"), anchor.get("radio"), start_time, end_time]
        if anchor.get("session_id"):
            peer_clauses.insert(2, "session_id = ?")
            peer_values.insert(2, anchor.get("session_id"))
        with self._connect() as conn:
            peer_rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM mesh_links WHERE {' AND '.join(peer_clauses)} ORDER BY sample_time ASC, id ASC",
                    peer_values,
                ).fetchall()
            ]
            run_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM mesh_links
                    WHERE radio = ? AND sample_time >= ? AND sample_time <= ?
                    ORDER BY sample_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time),
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM mesh_events
                    WHERE radio = ? AND event_time >= ? AND event_time <= ?
                    ORDER BY event_time ASC, id ASC
                    """,
                    (anchor.get("radio"), start_time, end_time),
                ).fetchall()
            ]
        peer_segment = _segment_payload(anchor, peer_rows, interval, gap)
        run_segment = _segment_payload(anchor, run_rows, interval, gap)
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

    def _locate_run_segment(self, anchor_link_id: int, batch_size: int = 1000) -> tuple[dict[str, object] | None, str | None, str | None, float | None, float | None]:
        with self._connect() as conn:
            anchor_row = conn.execute("SELECT * FROM mesh_links WHERE id = ?", (anchor_link_id,)).fetchone()
            if anchor_row is None:
                return None, None, None, None, None
            anchor = dict(anchor_row)
            radio = anchor["radio"]
            anchor_time = anchor["sample_time"]
            interval, gap = self._estimate_local_interval(conn, radio, anchor_time)
            start_time = self._scan_segment_boundary(conn, radio, anchor_time, gap, "backward", batch_size)
            end_time = self._scan_segment_boundary(conn, radio, anchor_time, gap, "forward", batch_size)
        return anchor, start_time, end_time, interval, gap

    def _estimate_local_interval(self, conn: sqlite3.Connection, radio: int, anchor_time: str) -> tuple[float, float]:
        before = [
            row["sample_time"]
            for row in conn.execute(
                """
                SELECT DISTINCT sample_time
                FROM mesh_links
                WHERE radio = ? AND sample_time <= ?
                ORDER BY sample_time DESC
                LIMIT 21
                """,
                (radio, anchor_time),
            ).fetchall()
        ]
        after = [
            row["sample_time"]
            for row in conn.execute(
                """
                SELECT DISTINCT sample_time
                FROM mesh_links
                WHERE radio = ? AND sample_time >= ?
                ORDER BY sample_time ASC
                LIMIT 21
                """,
                (radio, anchor_time),
            ).fetchall()
        ]
        interval, gap = _interval_and_threshold(sorted(set(before + after)))
        return interval or 1.0, gap

    def _scan_segment_boundary(self, conn: sqlite3.Connection, radio: int, anchor_time: str, gap_seconds: float, direction: str, batch_size: int) -> str:
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
                    WHERE radio = ? AND sample_time {operator} ?
                    ORDER BY sample_time {order}
                    LIMIT ?
                    """,
                    (radio, current, batch_size),
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
    ) -> list[dict[str, object]]:
        clauses = ["peer_mac_normalized = ?"]
        values: list[object] = [peer_mac_normalized]
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
                       local_signal_dbm, peer_signal_dbm, metrics_json, deltas_json, link_count
                FROM mesh_links
                WHERE {where}
                ORDER BY sample_time ASC, id ASC
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def rebuild_derived_analysis(self, should_cancel=None, progress=None, batch_size: int = 1000) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM mesh_deltas")
            conn.execute("DELETE FROM mesh_sessions")
            conn.execute("DELETE FROM mesh_events")
            self._rebuild_sessions_and_deltas(conn, should_cancel, progress, batch_size)
            self._rebuild_active_events(conn, should_cancel, progress, batch_size)
            if should_cancel is None or not should_cancel():
                conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)", (DERIVED_ANALYSIS_KEY, DERIVED_ANALYSIS_VERSION))

    def needs_derived_analysis_rebuild(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (DERIVED_ANALYSIS_KEY,)).fetchone()
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
                    (SELECT COUNT(*) FROM mesh_events) AS event_count,
                    (SELECT MAX(imported_at) FROM source_files) AS last_import_at
                FROM mesh_links
                """
            ).fetchone()
        return dict(row)

    def export_rows(self, table: str) -> list[dict[str, object]]:
        if table not in {"mesh_links", "mesh_events", "mesh_sessions", "parse_issues", "source_files"}:
            raise ValueError(f"Unsupported export table: {table}")
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def _rebuild_sessions_and_deltas(self, conn: sqlite3.Connection, should_cancel, progress, batch_size: int) -> None:
        cursor = conn.execute(
            """
            SELECT id, radio, peer_mac_normalized, peer_mac_raw, establish_time, sample_time,
                   link_state, metrics_json
            FROM mesh_links
            ORDER BY radio, peer_mac_normalized, establish_time, sample_time, id
            """
        )
        previous_by_session: dict[str, sqlite3.Row] = {}
        session_rows: dict[str, dict[str, object]] = {}
        updates: list[tuple[str, str, int]] = []
        delta_rows: list[tuple[int, str]] = []
        events: list[tuple[object, ...]] = []
        processed = 0
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                if should_cancel and should_cancel():
                    return
                metrics = _json(row["metrics_json"])
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
                deltas: dict[str, int | float | None] = {}
                previous = previous_by_session.get(session_id)
                if previous is not None:
                    previous_metrics = _json(previous["metrics_json"])
                    seconds = max((datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(previous["sample_time"])).total_seconds(), 0.0)
                    for key in _counter_keys():
                        current = metrics.get(key)
                        last = previous_metrics.get(key)
                        delta_key = f"delta_{key}"
                        per_second_key = f"{delta_key}_per_second"
                        if isinstance(current, int) and isinstance(last, int) and current >= last:
                            delta = current - last
                            deltas[delta_key] = delta
                            deltas[per_second_key] = round(delta / seconds, 6) if seconds > 0 else None
                        elif isinstance(current, int) and isinstance(last, int):
                            deltas[delta_key] = None
                            deltas[per_second_key] = None
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
                        else:
                            deltas[delta_key] = None
                            deltas[per_second_key] = None
                deltas_json = json.dumps(deltas, ensure_ascii=False)
                updates.append((session_id, deltas_json, row["id"]))
                delta_rows.append((row["id"], deltas_json))
                previous_by_session[session_id] = row
                processed += 1
            conn.executemany("UPDATE mesh_links SET session_id = ?, deltas_json = ? WHERE id = ?", updates)
            conn.executemany("INSERT OR REPLACE INTO mesh_deltas(link_id, deltas_json) VALUES (?, ?)", delta_rows)
            updates.clear()
            delta_rows.clear()
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
                INSERT INTO mesh_events (
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
                   metrics_json
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
                    previous_metrics = _json(previous["metrics_json"])
                    current_metrics = _json(row["metrics_json"])
                    details = {
                        "from_local_signal_dbm": previous["local_signal_dbm"],
                        "to_local_signal_dbm": row["local_signal_dbm"],
                        "from_peer_signal_dbm": previous["peer_signal_dbm"],
                        "to_peer_signal_dbm": row["peer_signal_dbm"],
                        "from_local_rssi": previous_metrics.get("local_rssi_db"),
                        "to_local_rssi": current_metrics.get("local_rssi_db"),
                        "from_peer_rssi": previous_metrics.get("peer_rssi_db"),
                        "to_peer_rssi": current_metrics.get("peer_rssi_db"),
                        "from_local_rate": previous_metrics.get("local_rate_raw"),
                        "to_local_rate": current_metrics.get("local_rate_raw"),
                        "from_peer_rate": previous_metrics.get("peer_rate_raw"),
                        "to_peer_rate": current_metrics.get("peer_rate_raw"),
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
                INSERT INTO mesh_events (
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
                INSERT INTO mesh_events (
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
                    source_file_id, source_file, line_number, severity, issue_type, field_name, message, raw_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_file_id, issue.source_file, issue.line_number, issue.severity, issue.issue_type, issue.field_name, issue.message, issue.raw_line),
            )


def _json(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _session_id(radio: int, peer: str, establish_time: str) -> str:
    raw = f"{radio}|{peer}|{establish_time}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_mac(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character in "0123456789abcdef")


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
