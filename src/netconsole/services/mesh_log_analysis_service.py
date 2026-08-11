from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from netconsole.models.mesh_log_models import (
    EVENT_ACTIVE_SWITCH,
    EVENT_COUNTER_RESET,
    EVENT_LINK_REESTABLISHED,
    EVENT_MULTI_ACTIVE,
    EVENT_NO_ACTIVE,
    LINK_STATE_ACTIVE,
    PAIRED_METRICS,
    ImportedLogFile,
    MeshAnalysisResult,
    MeshAnalysisSummary,
    MeshLogRecord,
    MeshPeerResolver,
    MeshSwitchEvent,
    NullMeshPeerResolver,
    ParseIssue,
    dataclass_to_json_dict,
    format_mac_h3c,
    summarize_parse_issues,
)
from netconsole.parsers.mesh_log_parser import MeshLogParser


SUPPORTED_SUFFIXES = (".log", ".txt", ".gz")
COUNTER_KEYS = (
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


def _timestamp_tag_sort_key(value: str | None) -> tuple[int, int | str]:
    text = str(value or "").strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text)


class MeshLogAnalysisService:
    def __init__(self, site_id: str, site_root: Path, resolver: MeshPeerResolver | None = None) -> None:
        self.site_id = site_id
        self.site_root = site_root
        self.resolver = resolver or NullMeshPeerResolver()
        self.parser = MeshLogParser()

    def discover_mesh_logs(self, folder: Path, include_txt: bool = True) -> list[Path]:
        if not folder.exists():
            return []
        paths: list[Path] = []
        for path in folder.iterdir():
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith("meshlog.log") or name.endswith("meshlog.log.gz") or (include_txt and name.endswith(".txt")):
                paths.append(path)
        return sorted(paths, key=lambda item: item.name.casefold())

    def analyze(
        self,
        files: list[Path],
        source_labels: dict[str, str] | None = None,
        analysis_name: str | None = None,
        should_cancel=None,
        progress=None,
    ) -> MeshAnalysisResult:
        analysis_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
        imported_files: list[ImportedLogFile] = []
        all_records: list[MeshLogRecord] = []
        all_issues: list[ParseIssue] = []
        total_files = len(files)
        for index, path in enumerate(files, start=1):
            if should_cancel and should_cancel():
                break
            source_label = (source_labels or {}).get(str(path))

            def on_file_progress(lines: int, parsed: int, skipped: int, file_index=index) -> None:
                if progress:
                    progress(file_index, total_files, lines, parsed, skipped)

            info, records, issues = self.parser.parse_file(path, source_label=source_label, should_cancel=should_cancel, progress=on_file_progress)
            imported_files.append(info)
            all_records.extend(records)
            all_issues.extend(issues)
            if progress:
                progress(index, total_files, 0, len(all_records), sum(item.skipped_count for item in imported_files))
        merged_records, duplicate_count_by_file = merge_and_deduplicate(all_records)
        for info in imported_files:
            info.duplicate_count = duplicate_count_by_file.get(str(info.path), 0)
        switch_events = analyze_active_events(merged_records)
        summary = build_summary(imported_files, merged_records, switch_events, all_issues, len(all_records))
        result = MeshAnalysisResult(
            analysis_id=analysis_id,
            site_id=self.site_id,
            analysis_name=analysis_name or f"MESH {analysis_id}",
            files=imported_files,
            records=merged_records,
            switch_events=switch_events,
            issues=all_issues,
            summary=summary,
        )
        result.analysis_dir = self.persist(result)
        return result

    def persist(self, result: MeshAnalysisResult) -> Path:
        analysis_dir = self.site_root / "analysis" / "mesh" / result.analysis_id
        exports_dir = analysis_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "analysis_id": result.analysis_id,
            "created_at": datetime.now().isoformat(sep=" "),
            "site_id": result.site_id,
            "analysis_name": result.analysis_name,
            "files": [dataclass_to_json_dict(item) for item in result.files],
            "summary": dataclass_to_json_dict(result.summary),
            "time_range": {
                "start": result.summary.start_time,
                "end": result.summary.end_time,
            },
        }
        with (analysis_dir / "metadata.json").open("w", encoding="utf-8") as file:
            json.dump(dataclass_to_json_dict(metadata), file, ensure_ascii=False, indent=2)
        write_analysis_sqlite(analysis_dir / "analysis.sqlite", result)
        return analysis_dir


def merge_and_deduplicate(records: list[MeshLogRecord]) -> tuple[list[MeshLogRecord], dict[str, int]]:
    seen: set[str] = set()
    merged: list[MeshLogRecord] = []
    duplicate_count_by_file: dict[str, int] = defaultdict(int)
    for record in sorted(
        records,
        key=lambda item: (
            item.source_label,
            item.sample_time,
            _timestamp_tag_sort_key(item.timestamp_tag),
            item.radio,
            item.peer_mac_normalized or item.peer_mac_raw,
            item.source_file,
            item.source_line_number,
        ),
    ):
        if record.duplicate_hash in seen:
            duplicate_count_by_file[record.source_file] += 1
            continue
        seen.add(record.duplicate_hash)
        merged.append(record)
    return merged, dict(duplicate_count_by_file)


def analyze_active_events(records: list[MeshLogRecord]) -> list[MeshSwitchEvent]:
    events: list[MeshSwitchEvent] = []
    by_sample: dict[tuple[str, int, datetime, str], list[MeshLogRecord]] = defaultdict(list)
    for record in records:
        by_sample[(record.source_label, record.radio, record.sample_time, record.timestamp_tag or "")].append(record)
    active_by_group: dict[tuple[str, int], list[tuple[datetime, str, MeshLogRecord | None]]] = defaultdict(list)
    for (source_label, radio, sample_time, timestamp_tag), rows in sorted(
        by_sample.items(),
        key=lambda item: (item[0][0], item[0][1], item[0][2], _timestamp_tag_sort_key(item[0][3])),
    ):
        active_rows = [row for row in rows if row.link_state == LINK_STATE_ACTIVE]
        if len(active_rows) == 1:
            active_by_group[(source_label, radio)].append((sample_time, timestamp_tag, active_rows[0]))
        elif len(active_rows) == 0:
            events.append(MeshSwitchEvent(EVENT_NO_ACTIVE, source_label, radio, current_sample_time=sample_time, source_file=rows[0].source_file, source_line_number=rows[0].source_line_number))
            active_by_group[(source_label, radio)].append((sample_time, timestamp_tag, None))
        else:
            events.append(MeshSwitchEvent(EVENT_MULTI_ACTIVE, source_label, radio, current_sample_time=sample_time, source_file=active_rows[0].source_file, source_line_number=active_rows[0].source_line_number))
            active_by_group[(source_label, radio)].append((sample_time, timestamp_tag, None))
    for (source_label, radio), samples in active_by_group.items():
        previous: tuple[datetime, MeshLogRecord] | None = None
        for sample_time, _timestamp_tag, active in sorted(samples, key=lambda item: (item[0], _timestamp_tag_sort_key(item[1]))):
            if active is None:
                previous = None
                continue
            if previous is not None and (previous[1].peer_mac_normalized or previous[1].peer_mac_raw) != (active.peer_mac_normalized or active.peer_mac_raw):
                events.append(make_switch_event(source_label, radio, previous[0], previous[1], sample_time, active))
            previous = (sample_time, active)
    return sorted(events, key=lambda item: (item.source_label, item.radio, item.current_sample_time or datetime.min, item.event_type))


def enrich_sessions_deltas_and_events(records: list[MeshLogRecord]) -> tuple[list[MeshLogRecord], list[MeshSwitchEvent]]:
    sorted_records = sorted(
        records,
        key=lambda item: (
            item.radio,
            item.peer_mac_normalized or item.peer_mac_raw,
            item.establish_time or datetime.min,
            item.sample_time,
            _timestamp_tag_sort_key(item.timestamp_tag),
            item.source_line_number,
        ),
    )
    events: list[MeshSwitchEvent] = []
    previous_by_session: dict[str, MeshLogRecord] = {}
    seen_peer_sessions: set[tuple[int, str]] = set()
    seen_sessions: set[str] = set()
    for record in sorted_records:
        peer_key = record.peer_mac_normalized or record.peer_mac_raw
        establish_key = record.establish_time.isoformat(sep=" ", timespec="seconds") if record.establish_time else "unknown"
        record.session_id = f"{record.radio}:{peer_key}:{establish_key}"
        is_new_session = record.session_id not in seen_sessions
        if is_new_session and (record.radio, peer_key) in seen_peer_sessions and record.establish_time is not None:
            events.append(
                MeshSwitchEvent(
                    EVENT_LINK_REESTABLISHED,
                    record.source_label,
                    record.radio,
                    current_sample_time=record.sample_time,
                    to_peer_mac=record.peer_mac_h3c(),
                    source_file=record.source_file,
                    source_line_number=record.source_line_number,
                )
            )
        seen_peer_sessions.add((record.radio, peer_key))
        seen_sessions.add(record.session_id)
        previous = previous_by_session.get(record.session_id)
        record.deltas = {}
        if previous is not None:
            seconds = max((record.sample_time - previous.sample_time).total_seconds(), 0.0)
            for key in COUNTER_KEYS:
                current = record.metrics.get(key)
                last = previous.metrics.get(key)
                delta_key = f"delta_{key}"
                per_second_key = f"{delta_key}_per_second"
                if isinstance(current, int) and isinstance(last, int):
                    if current >= last:
                        delta = current - last
                        record.deltas[delta_key] = delta
                        record.deltas[per_second_key] = round(delta / seconds, 6) if seconds > 0 else None
                    else:
                        record.deltas[delta_key] = None
                        record.deltas[per_second_key] = None
                        events.append(
                            MeshSwitchEvent(
                                EVENT_COUNTER_RESET,
                                record.source_label,
                                record.radio,
                                previous_sample_time=previous.sample_time,
                                current_sample_time=record.sample_time,
                                to_peer_mac=record.peer_mac_h3c(),
                                source_file=record.source_file,
                                source_line_number=record.source_line_number,
                            )
                        )
                else:
                    record.deltas[delta_key] = None
                    record.deltas[per_second_key] = None
        previous_by_session[record.session_id] = record
    return records, events


def make_switch_event(source_label: str, radio: int, previous_time: datetime, previous: MeshLogRecord, current_time: datetime, current: MeshLogRecord) -> MeshSwitchEvent:
    observed = int((current_time - previous_time).total_seconds() * 1000)
    return MeshSwitchEvent(
        event_type=EVENT_ACTIVE_SWITCH,
        source_label=source_label,
        radio=radio,
        previous_sample_time=previous_time,
        current_sample_time=current_time,
        observed_window_ms=observed,
        from_peer_mac=format_mac_h3c(previous.peer_mac_normalized) if previous.peer_mac_normalized else previous.peer_mac_raw,
        to_peer_mac=format_mac_h3c(current.peer_mac_normalized) if current.peer_mac_normalized else current.peer_mac_raw,
        from_local_rssi=previous.metrics.get("local_rssi_db"),
        from_peer_rssi=previous.metrics.get("peer_rssi_db"),
        from_local_signal_dbm=previous.local_signal_dbm,
        from_peer_signal_dbm=previous.peer_signal_dbm,
        from_local_rate=previous.metrics.get("local_rate_raw"),
        from_peer_rate=previous.metrics.get("peer_rate_raw"),
        to_local_rssi=current.metrics.get("local_rssi_db"),
        to_peer_rssi=current.metrics.get("peer_rssi_db"),
        to_local_signal_dbm=current.local_signal_dbm,
        to_peer_signal_dbm=current.peer_signal_dbm,
        to_local_rate=current.metrics.get("local_rate_raw"),
        to_peer_rate=current.metrics.get("peer_rate_raw"),
        source_file=current.source_file,
        source_line_number=current.source_line_number,
    )


def build_summary(files: list[ImportedLogFile], records: list[MeshLogRecord], events: list[MeshSwitchEvent], issues: list[ParseIssue], raw_record_count: int) -> MeshAnalysisSummary:
    times = [record.sample_time for record in records]
    issue_counts = summarize_parse_issues(issues)
    return MeshAnalysisSummary(
        file_count=len(files),
        source_count=len({item.source_label for item in files}),
        start_time=min(times) if times else None,
        end_time=max(times) if times else None,
        sample_count=len({(record.source_label, record.radio, record.sample_time) for record in records}),
        record_count=len(records),
        radio_count=len({(record.source_label, record.radio) for record in records}),
        peer_count=len({record.peer_mac_normalized or record.peer_mac_raw for record in records}),
        active_switch_count=sum(1 for event in events if event.event_type == EVENT_ACTIVE_SWITCH),
        no_active_count=sum(1 for event in events if event.event_type == EVENT_NO_ACTIVE),
        multi_active_count=sum(1 for event in events if event.event_type == EVENT_MULTI_ACTIVE),
        info_count=issue_counts["info"],
        warning_count=issue_counts["warning"],
        error_count=issue_counts["error"],
        issue_count=issue_counts["total"],
        raw_record_count=raw_record_count,
        duplicate_record_count=max(raw_record_count - len(records), 0),
    )


def write_analysis_sqlite(path: Path, result: MeshAnalysisResult) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE imported_files (
                path TEXT PRIMARY KEY, source_label TEXT, size INTEGER, modified_time TEXT, file_hash TEXT,
                status TEXT, record_count INTEGER, skipped_count INTEGER, duplicate_count INTEGER,
                error_count INTEGER, start_time TEXT, end_time TEXT, error_message TEXT
            );
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_label TEXT, source_file TEXT, source_line_number INTEGER,
                raw_line TEXT, radio INTEGER, sample_time TEXT, timestamp_tag TEXT, link_state_raw TEXT, link_state TEXT,
                peer_mac_raw TEXT, peer_mac_normalized TEXT, establish_time TEXT, duration_text TEXT,
                duration_seconds INTEGER, link_count INTEGER, metrics_json TEXT, local_noise_dbm INTEGER,
                peer_noise_dbm INTEGER, local_signal_dbm INTEGER, peer_signal_dbm INTEGER, duplicate_hash TEXT
            );
            CREATE TABLE switch_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, source_label TEXT, radio INTEGER,
                previous_sample_time TEXT, current_sample_time TEXT, observed_window_ms INTEGER,
                from_peer_mac TEXT, to_peer_mac TEXT, from_local_rssi INTEGER, from_peer_rssi INTEGER,
                from_local_signal_dbm INTEGER, from_peer_signal_dbm INTEGER, from_local_rate INTEGER,
                from_peer_rate INTEGER, to_local_rssi INTEGER, to_peer_rssi INTEGER, to_local_signal_dbm INTEGER,
                to_peer_signal_dbm INTEGER, to_local_rate INTEGER, to_peer_rate INTEGER,
                source_file TEXT, source_line_number INTEGER
            );
            CREATE TABLE parse_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT, line_number INTEGER,
                issue_type TEXT, message TEXT, raw_line TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO imported_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(item.path),
                    item.source_label,
                    item.size,
                    _dt(item.modified_time),
                    item.file_hash,
                    item.status,
                    item.record_count,
                    item.skipped_count,
                    item.duplicate_count,
                    item.error_count,
                    _dt(item.start_time),
                    _dt(item.end_time),
                    item.error_message,
                )
                for item in result.files
            ],
        )
        conn.executemany(
            """
            INSERT INTO records (
                source_label, source_file, source_line_number, raw_line, radio, sample_time, timestamp_tag,
                link_state_raw, link_state, peer_mac_raw, peer_mac_normalized, establish_time, duration_text,
                duration_seconds, link_count, metrics_json, local_noise_dbm, peer_noise_dbm, local_signal_dbm,
                peer_signal_dbm, duplicate_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.source_label,
                    record.source_file,
                    record.source_line_number,
                    record.raw_line,
                    record.radio,
                    _dt(record.sample_time),
                    record.timestamp_tag,
                    record.link_state_raw,
                    record.link_state,
                    record.peer_mac_raw,
                    record.peer_mac_normalized,
                    _dt(record.establish_time),
                    record.duration_text,
                    record.duration_seconds,
                    record.link_count,
                    json.dumps(record.metrics, ensure_ascii=False),
                    record.local_noise_dbm,
                    record.peer_noise_dbm,
                    record.local_signal_dbm,
                    record.peer_signal_dbm,
                    record.duplicate_hash,
                )
                for record in result.records
            ],
        )
        conn.executemany(
            """
            INSERT INTO switch_events VALUES (
                NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    event.event_type,
                    event.source_label,
                    event.radio,
                    _dt(event.previous_sample_time),
                    _dt(event.current_sample_time),
                    event.observed_window_ms,
                    event.from_peer_mac,
                    event.to_peer_mac,
                    event.from_local_rssi,
                    event.from_peer_rssi,
                    event.from_local_signal_dbm,
                    event.from_peer_signal_dbm,
                    event.from_local_rate,
                    event.from_peer_rate,
                    event.to_local_rssi,
                    event.to_peer_rssi,
                    event.to_local_signal_dbm,
                    event.to_peer_signal_dbm,
                    event.to_local_rate,
                    event.to_peer_rate,
                    event.source_file,
                    event.source_line_number,
                )
                for event in result.switch_events
            ],
        )
        conn.executemany(
            "INSERT INTO parse_issues VALUES (NULL, ?, ?, ?, ?, ?)",
            [(issue.source_file, issue.line_number, issue.issue_type, issue.message, issue.raw_line) for issue in result.issues],
        )
        conn.commit()
    finally:
        conn.close()


DETAIL_EXPORT_COLUMNS = [
    "source_label",
    "sample_time",
    "radio",
    "link_state",
    "peer_mac",
    "establish_time",
    "duration_text",
    "duration_seconds",
    "link_count",
    "local_noise_dbm",
    "peer_noise_dbm",
    "local_signal_dbm",
    "peer_signal_dbm",
    "source_file",
    "source_line_number",
    "raw_line",
]


def export_records(path: Path, records: list[MeshLogRecord]) -> None:
    rows = []
    for record in records:
        row = {
            "source_label": record.source_label,
            "sample_time": _dt(record.sample_time),
            "radio": record.radio,
            "link_state": record.link_state,
            "peer_mac": record.peer_mac_h3c(),
            "establish_time": _dt(record.establish_time),
            "duration_text": record.duration_text,
            "duration_seconds": record.duration_seconds,
            "link_count": record.link_count,
            "local_noise_dbm": record.local_noise_dbm,
            "peer_noise_dbm": record.peer_noise_dbm,
            "local_signal_dbm": record.local_signal_dbm,
            "peer_signal_dbm": record.peer_signal_dbm,
            "source_file": record.source_file,
            "source_line_number": record.source_line_number,
            "raw_line": record.raw_line,
        }
        row.update(record.metrics)
        rows.append(row)
    columns = DETAIL_EXPORT_COLUMNS + [key for _, local_key, peer_key in PAIRED_METRICS for key in (local_key, peer_key)]
    write_rows(path, columns, rows)


def export_events(path: Path, events: list[MeshSwitchEvent]) -> None:
    columns = [
        "event_type",
        "source_label",
        "radio",
        "previous_sample_time",
        "current_sample_time",
        "observed_window_ms",
        "from_peer_mac",
        "to_peer_mac",
        "from_local_signal_dbm",
        "to_local_signal_dbm",
        "from_peer_signal_dbm",
        "to_peer_signal_dbm",
        "from_local_rate",
        "to_local_rate",
        "source_file",
        "source_line_number",
    ]
    rows = [dataclass_to_json_dict(event) for event in events]
    write_rows(path, columns, rows)


def export_issues(path: Path, issues: list[ParseIssue]) -> None:
    write_rows(path, ["source_file", "line_number", "issue_type", "message", "raw_line"], [dataclass_to_json_dict(issue) for issue in issues])


def write_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(columns)
        for row in rows:
            ws.append([row.get(column) for column in columns])
        wb.save(path)
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="milliseconds")
