from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Callable

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, LINK_STATE_STANDBY, format_mac_h3c
from netconsole.services.mesh_quality_analysis import (
    MR_RAW_MESH_LOG,
    MeshQualityRules,
    build_quality_report,
    get_threshold_template,
    load_default_rules,
)


ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class MeshReportOptions:
    report_name: str = ""
    data_source_type: str = MR_RAW_MESH_LOG
    start_time: str | None = None
    end_time: str | None = None
    radio_filter: int | None = None
    source_file_id: int | None = None
    source_file_name: str = ""
    rssi_excellent_threshold: int = 40
    rssi_good_threshold: int = 30
    rssi_warning_threshold: int = 25
    rssi_bad_threshold: int = 20
    backup_available_threshold: int = 30
    backup_strong_threshold: int = 40
    busy_warning_threshold: int = 60
    busy_bad_threshold: int = 75
    no_backup_min_seconds: int = 5
    weak_active_min_seconds: int = 3
    switch_late_window_seconds: int = 5
    switch_target_window_seconds: int = 5
    flap_window_seconds: int = 30
    short_active_segment_seconds: int = 5
    include_raw_evidence: bool = True
    include_all_link_details: bool = False
    include_busy_analysis: bool = True
    use_multi_core: bool = True
    worker_processes: int = 0
    stream_large_excel: bool = True
    autofit_scan_limit: int = 2000
    open_output_dir_after_done: bool = True
    separate_reports_by_source_file: bool = True
    include_raw_events: bool = True
    include_parse_issues: bool = True
    include_peer_lifecycle: bool = True
    include_link_establishment: bool = True
    include_flap_analysis: bool = True
    export_format: str = "excel"
    excluded_region_keywords: tuple[str, ...] = ()
    threshold_template_key: str = "pis_wifi6_40_80_standard"
    business_type: str = "PIS"
    working_mode: str = "Wi-Fi6 / 11ax"
    bandwidth: str = "40M / 80M 混合"
    ap_spacing: str = "80~150m"
    threshold_template_description: str = ""


@dataclass
class MeshAnalysisReportModel:
    mr_name: str
    report_name: str
    generated_at: datetime
    options: MeshReportOptions
    overview: dict[str, object] = field(default_factory=dict)
    switch_sequence: list[dict[str, object]] = field(default_factory=list)
    active_segments: list[dict[str, object]] = field(default_factory=list)
    flap_events: list[dict[str, object]] = field(default_factory=list)
    link_establishment_order: list[dict[str, object]] = field(default_factory=list)
    peer_lifecycle: list[dict[str, object]] = field(default_factory=list)
    active_anomalies: list[dict[str, object]] = field(default_factory=list)
    rssi_statistics: list[dict[str, object]] = field(default_factory=list)
    channel_busy_statistics: list[dict[str, object]] = field(default_factory=list)
    raw_events: list[dict[str, object]] = field(default_factory=list)
    parse_issues: list[dict[str, object]] = field(default_factory=list)
    source_files: list[dict[str, object]] = field(default_factory=list)
    score_rows: list[dict[str, object]] = field(default_factory=list)
    sample_quality: list[dict[str, object]] = field(default_factory=list)
    peer_ranking: list[dict[str, object]] = field(default_factory=list)
    switch_events: list[dict[str, object]] = field(default_factory=list)
    anomaly_events: list[dict[str, object]] = field(default_factory=list)
    no_backup_risks: list[dict[str, object]] = field(default_factory=list)
    busy_analysis: list[dict[str, object]] = field(default_factory=list)
    link_rebuild_events: list[dict[str, object]] = field(default_factory=list)
    raw_evidence: list[dict[str, object]] = field(default_factory=list)
    all_link_details: list[dict[str, object]] = field(default_factory=list)


class MeshReportCancelled(RuntimeError):
    """Raised when report generation is cancelled before export completes."""


class MeshAnalysisReportService:
    def __init__(self, db_path: Path, mr_name: str = "") -> None:
        self.db_path = Path(db_path)
        self.mr_name = mr_name or self.db_path.parent.name

    def build_report(
        self,
        options: MeshReportOptions | None = None,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> MeshAnalysisReportModel:
        options = options or MeshReportOptions()
        progress = progress or (lambda _value, _message: None)
        should_cancel = should_cancel or (lambda: False)
        self._raise_if_cancelled(should_cancel)
        progress(5, "loading")
        links = self._load_links(options)
        events = self._load_events(options) if options.include_raw_events else []
        parse_issues = self._load_parse_issues(options) if options.include_parse_issues else []
        source_files = self._load_source_files(options)
        self._raise_if_cancelled(should_cancel)

        rules = self._rules_from_options(options)
        quality_report = build_quality_report(
            links,
            source_files,
            parse_issues,
            self.mr_name,
            options.report_name or self.mr_name,
            options.data_source_type,
            rules,
            include_raw_evidence=options.include_raw_evidence,
            include_all_link_details=options.include_all_link_details,
            include_parse_issues=options.include_parse_issues,
            include_busy_analysis=options.include_busy_analysis,
            threshold_template_key=options.threshold_template_key,
            excluded_region_keywords=options.excluded_region_keywords,
            progress=progress,
            should_cancel=should_cancel,
        )
        self._raise_if_cancelled(should_cancel)

        progress(25, "active_segments")
        active_segments = build_active_segments(links)
        switch_sequence = build_switch_sequence(active_segments)
        self._raise_if_cancelled(should_cancel)

        progress(45, "flap")
        flap_events = detect_flap_switches(active_segments, options.flap_window_seconds) if options.include_flap_analysis else []
        active_anomalies = build_active_anomalies(links)
        self._raise_if_cancelled(should_cancel)

        progress(65, "peers")
        link_establishment_order = build_link_establishment_order(links) if options.include_link_establishment else []
        peer_lifecycle = build_peer_lifecycle(links, active_segments, switch_sequence) if options.include_peer_lifecycle else []
        self._raise_if_cancelled(should_cancel)

        progress(82, "statistics")
        rssi_statistics = build_rssi_statistics(links)
        channel_busy_statistics = build_channel_busy_statistics(links)
        overview = dict(quality_report.overview)
        overview.update(
            {
                "业务类型": options.business_type,
                "实际工作模式": options.working_mode,
                "频宽": options.bandwidth,
                "典型 AP 间隔": options.ap_spacing,
                "评估模板说明": options.threshold_template_description or overview.get("评估模板说明", ""),
            }
        )
        progress(88, "analysis_done")
        return MeshAnalysisReportModel(
            mr_name=self.mr_name,
            report_name=options.report_name or self.mr_name,
            generated_at=datetime.now(),
            options=options,
            overview=overview,
            switch_sequence=switch_sequence,
            flap_events=flap_events,
            link_establishment_order=link_establishment_order,
            peer_lifecycle=peer_lifecycle,
            active_anomalies=active_anomalies,
            rssi_statistics=rssi_statistics,
            channel_busy_statistics=channel_busy_statistics,
            raw_events=events,
            parse_issues=parse_issues,
            source_files=quality_report.source_files,
            score_rows=quality_report.score_rows,
            sample_quality=quality_report.sample_quality,
            active_segments=quality_report.active_segments or active_segments,
            peer_ranking=quality_report.peer_ranking,
            switch_events=quality_report.switch_events,
            anomaly_events=quality_report.anomaly_events,
            no_backup_risks=quality_report.no_backup_risks,
            busy_analysis=quality_report.busy_analysis,
            link_rebuild_events=quality_report.link_rebuild_events,
            raw_evidence=quality_report.raw_evidence,
            all_link_details=quality_report.all_link_details,
        )

    def _rules_from_options(self, options: MeshReportOptions) -> MeshQualityRules:
        defaults = load_default_rules()
        template = get_threshold_template(options.threshold_template_key)
        weights = template.rules.score_weights or defaults.score_weights
        return MeshQualityRules(
            rssi_excellent_threshold=options.rssi_excellent_threshold or defaults.rssi_excellent_threshold,
            rssi_good_threshold=options.rssi_good_threshold or defaults.rssi_good_threshold,
            rssi_warning_threshold=options.rssi_warning_threshold or defaults.rssi_warning_threshold,
            rssi_bad_threshold=options.rssi_bad_threshold or defaults.rssi_bad_threshold,
            backup_available_threshold=options.backup_available_threshold or defaults.backup_available_threshold,
            backup_strong_threshold=options.backup_strong_threshold or defaults.backup_strong_threshold,
            busy_warning_threshold=options.busy_warning_threshold or defaults.busy_warning_threshold,
            busy_bad_threshold=options.busy_bad_threshold or defaults.busy_bad_threshold,
            no_backup_min_seconds=options.no_backup_min_seconds or defaults.no_backup_min_seconds,
            weak_active_min_seconds=options.weak_active_min_seconds or defaults.weak_active_min_seconds,
            switch_late_window_seconds=options.switch_late_window_seconds or defaults.switch_late_window_seconds,
            switch_target_window_seconds=options.switch_target_window_seconds or defaults.switch_target_window_seconds,
            flap_window_seconds=options.flap_window_seconds or defaults.flap_window_seconds,
            short_active_segment_seconds=options.short_active_segment_seconds or defaults.short_active_segment_seconds,
            score_weights=weights,
        )

    def _load_links(self, options: MeshReportOptions) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if options.radio_filter is not None:
            clauses.append("ml.radio = ?")
            values.append(options.radio_filter)
        if options.source_file_id is not None:
            clauses.append("ml.source_file_id = ?")
            values.append(options.source_file_id)
        if options.start_time:
            clauses.append("ml.sample_time >= ?")
            values.append(options.start_time)
        if options.end_time:
            clauses.append("ml.sample_time <= ?")
            values.append(options.end_time)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    ml.id, ml.sample_id, ml.source_file_id, ml.source_file_order, ml.record_seq,
                    ml.source_line_number, ml.raw_line, ml.radio, ml.sample_time,
                    ml.link_state_raw, ml.link_state, ml.peer_mac_raw, ml.peer_mac_normalized,
                    ml.peer_mac, ml.peer_ap_name, ml.peer_ap_mac, ml.peer_site,
                    ml.peer_radio_id, ml.peer_radio, ml.peer_radio_label, ml.peer_radio_mac,
                    ml.peer_match_rule, ml.peer_resolve_source, ml.establish_time,
                    ml.duration_text, ml.duration_seconds, ml.link_count, ml.session_id,
                    ml.metrics_json, ml.deltas_json, ml.local_noise_dbm, ml.peer_noise_dbm,
                    ml.local_signal_dbm, ml.peer_signal_dbm,
                    sf.archived_filename, sf.original_filename
                FROM mesh_links ml
                LEFT JOIN source_files sf ON sf.id = ml.source_file_id
                {where}
                ORDER BY ml.sample_time ASC, ml.radio ASC, ml.id ASC
                """,
                values,
            ).fetchall()
        return [_normalize_link_row(dict(row)) for row in rows]

    def _load_events(self, options: MeshReportOptions) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if options.radio_filter is not None:
            clauses.append("radio = ?")
            values.append(options.radio_filter)
        if options.source_file_id is not None:
            clauses.append("source_file_id = ?")
            values.append(options.source_file_id)
        if options.start_time:
            clauses.append("event_time >= ?")
            values.append(options.start_time)
        if options.end_time:
            clauses.append("event_time <= ?")
            values.append(options.end_time)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM mesh_events {where} ORDER BY event_time ASC, id ASC", values).fetchall()
        return [dict(row) for row in rows]

    def _load_parse_issues(self, options: MeshReportOptions) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if options.source_file_id is not None:
            clauses.append("source_file_id = ?")
            values.append(options.source_file_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM parse_issues {where} ORDER BY source_file ASC, line_number ASC, id ASC", values).fetchall()
        return [dict(row) for row in rows]

    def _load_source_files(self, options: MeshReportOptions) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if options.source_file_id is not None:
            clauses.append("id = ?")
            values.append(options.source_file_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM source_files {where} ORDER BY COALESCE(first_sample_time, imported_at) ASC, id ASC", values).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
        if should_cancel():
            raise MeshReportCancelled()


def build_active_segments(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = _group_by_radio_time(rows)
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_rows: list[dict[str, object]] = []
    for (radio, sample_time), sample_rows in grouped:
        active_rows = [row for row in sample_rows if _state(row) == LINK_STATE_ACTIVE]
        if len(active_rows) != 1:
            if current is not None:
                _finish_segment(current, current_rows)
                segments.append(current)
                current = None
                current_rows = []
            continue
        active = active_rows[0]
        peer = _peer(active)
        if current is not None and current.get("radio") == radio and current.get("active_peer_mac") == peer:
            current["end_time"] = sample_time
            current["sample_count"] = int(current.get("sample_count") or 0) + 1
            current_rows.append(active)
            continue
        if current is not None:
            _finish_segment(current, current_rows)
            segments.append(current)
        current = {
            "segment_id": len(segments) + 1,
            "radio": radio,
            "active_peer_mac": peer,
            "active_peer": format_mac_h3c(peer),
            "start_time": sample_time,
            "end_time": sample_time,
            "sample_count": 1,
        }
        current_rows = [active]
    if current is not None:
        _finish_segment(current, current_rows)
        segments.append(current)
    return segments


def build_switch_sequence(segments: list[dict[str, object]]) -> list[dict[str, object]]:
    switches: list[dict[str, object]] = []
    by_radio: dict[object, list[dict[str, object]]] = {}
    for segment in segments:
        by_radio.setdefault(segment.get("radio"), []).append(segment)
    for radio, radio_segments in by_radio.items():
        ordered = sorted(radio_segments, key=lambda item: str(item.get("start_time") or ""))
        for previous, current in zip(ordered, ordered[1:]):
            if previous.get("active_peer_mac") == current.get("active_peer_mac"):
                continue
            switches.append(
                {
                    "sequence": len(switches) + 1,
                    "radio": radio,
                    "switch_time": current.get("start_time"),
                    "from_peer_mac": previous.get("active_peer_mac"),
                    "from_peer": previous.get("active_peer"),
                    "to_peer_mac": current.get("active_peer_mac"),
                    "to_peer": current.get("active_peer"),
                    "previous_start_time": previous.get("start_time"),
                    "previous_end_time": previous.get("end_time"),
                    "previous_duration_seconds": previous.get("duration_seconds"),
                    "new_segment_end_time": current.get("end_time"),
                    "new_duration_seconds": current.get("duration_seconds"),
                    "from_mr_rssi": previous.get("avg_mr_rssi"),
                    "to_mr_rssi": current.get("avg_mr_rssi"),
                }
            )
    switches.sort(key=lambda item: str(item.get("switch_time") or ""))
    for index, switch in enumerate(switches, 1):
        switch["sequence"] = index
    return switches


def detect_flap_switches(segments: list[dict[str, object]], flap_window_seconds: int = 5) -> list[dict[str, object]]:
    flaps: list[dict[str, object]] = []
    by_radio: dict[object, list[dict[str, object]]] = {}
    for segment in segments:
        by_radio.setdefault(segment.get("radio"), []).append(segment)
    for radio, radio_segments in by_radio.items():
        ordered = sorted(radio_segments, key=lambda item: str(item.get("start_time") or ""))
        for index in range(len(ordered) - 2):
            a, b, c = ordered[index], ordered[index + 1], ordered[index + 2]
            if a.get("active_peer_mac") != c.get("active_peer_mac") or a.get("active_peer_mac") == b.get("active_peer_mac"):
                continue
            window = _seconds_between(a.get("end_time"), c.get("start_time"))
            if window is None or window > flap_window_seconds:
                continue
            flaps.append(
                {
                    "sequence": len(flaps) + 1,
                    "radio": radio,
                    "flap_type": "A-B-A",
                    "start_time": a.get("start_time"),
                    "return_time": c.get("start_time"),
                    "peer_a": a.get("active_peer"),
                    "peer_b": b.get("active_peer"),
                    "peer_a_mac": a.get("active_peer_mac"),
                    "peer_b_mac": b.get("active_peer_mac"),
                    "window_seconds": window,
                }
            )
        for index in range(len(ordered) - 3):
            peers = [ordered[index + offset].get("active_peer_mac") for offset in range(4)]
            if peers[0] == peers[2] and peers[1] == peers[3] and peers[0] != peers[1]:
                window = _seconds_between(ordered[index].get("start_time"), ordered[index + 3].get("start_time"))
                if window is not None and window <= flap_window_seconds:
                    flaps.append(
                        {
                            "sequence": len(flaps) + 1,
                            "radio": radio,
                            "flap_type": "A-B-A-B",
                            "start_time": ordered[index].get("start_time"),
                            "return_time": ordered[index + 3].get("start_time"),
                            "peer_a": ordered[index].get("active_peer"),
                            "peer_b": ordered[index + 1].get("active_peer"),
                            "peer_a_mac": peers[0],
                            "peer_b_mac": peers[1],
                            "window_seconds": window,
                        }
                    )
    flaps.sort(key=lambda item: str(item.get("start_time") or ""))
    for index, flap in enumerate(flaps, 1):
        flap["sequence"] = index
    return flaps


def build_link_establishment_order(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_peer: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        peer = _peer(row)
        if peer:
            by_peer.setdefault((row.get("radio"), peer), []).append(row)
    result: list[dict[str, object]] = []
    for (radio, peer), peer_rows in by_peer.items():
        ordered = sorted(peer_rows, key=lambda item: str(item.get("sample_time") or ""))
        active_count = len([row for row in ordered if _state(row) == LINK_STATE_ACTIVE])
        standby_count = len([row for row in ordered if _state(row) == LINK_STATE_STANDBY])
        first_establish = min((str(row.get("establish_time")) for row in ordered if row.get("establish_time")), default="")
        result.append(
            {
                "sequence": 0,
                "radio": radio,
                "peer_mac": peer,
                "peer": format_mac_h3c(peer),
                "first_seen_time": ordered[0].get("sample_time"),
                "first_establish_time": first_establish,
                "last_seen_time": ordered[-1].get("sample_time"),
                "sample_count": len(ordered),
                "active_sample_count": active_count,
                "standby_sample_count": standby_count,
                "max_duration_seconds": max((_number(row.get("duration_seconds")) or 0 for row in ordered), default=0),
            }
        )
    result.sort(key=lambda item: (str(item.get("first_establish_time") or ""), str(item.get("first_seen_time") or "")))
    for index, item in enumerate(result, 1):
        item["sequence"] = index
    return result


def build_peer_lifecycle(rows: list[dict[str, object]], segments: list[dict[str, object]], switches: list[dict[str, object]]) -> list[dict[str, object]]:
    by_peer: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        peer = _peer(row)
        if peer:
            by_peer.setdefault((row.get("radio"), peer), []).append(row)
    result: list[dict[str, object]] = []
    for (radio, peer), peer_rows in by_peer.items():
        ordered = sorted(peer_rows, key=lambda item: str(item.get("sample_time") or ""))
        active_segments = [segment for segment in segments if segment.get("radio") == radio and segment.get("active_peer_mac") == peer]
        to_peer = [switch for switch in switches if switch.get("radio") == radio and switch.get("to_peer_mac") == peer]
        from_peer = [switch for switch in switches if switch.get("radio") == radio and switch.get("from_peer_mac") == peer]
        result.append(
            {
                "radio": radio,
                "peer_mac": peer,
                "peer": format_mac_h3c(peer),
                "first_seen_time": ordered[0].get("sample_time"),
                "last_seen_time": ordered[-1].get("sample_time"),
                "first_active_time": min((str(segment.get("start_time")) for segment in active_segments), default=""),
                "last_active_time": max((str(segment.get("end_time")) for segment in active_segments), default=""),
                "active_segment_count": len(active_segments),
                "active_sample_count": len([row for row in ordered if _state(row) == LINK_STATE_ACTIVE]),
                "standby_sample_count": len([row for row in ordered if _state(row) == LINK_STATE_STANDBY]),
                "switch_in_count": len(to_peer),
                "switch_out_count": len(from_peer),
            }
        )
    return sorted(result, key=lambda item: (str(item.get("first_seen_time") or ""), str(item.get("peer_mac") or "")))


def build_active_anomalies(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    anomalies: list[dict[str, object]] = []
    for (radio, sample_time), sample_rows in _group_by_radio_time(rows):
        active_rows = [row for row in sample_rows if _state(row) == LINK_STATE_ACTIVE]
        if len(active_rows) == 1:
            continue
        anomalies.append(
            {
                "anomaly_type": "NO_ACTIVE" if not active_rows else "MULTI_ACTIVE",
                "radio": radio,
                "start_time": sample_time,
                "end_time": sample_time,
                "active_count": len(active_rows),
                "active_peers": ", ".join(format_mac_h3c(_peer(row)) for row in active_rows if _peer(row)),
                "sample_count": 1,
            }
        )
    return anomalies


def build_rssi_statistics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return _metric_statistics(rows, ("mr_rssi", "peer_rssi"), "rssi")


def build_channel_busy_statistics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return _metric_statistics(rows, ("local_tx_busy", "local_rx_busy", "peer_tx_busy", "peer_rx_busy"), "busy")


def _metric_statistics(rows: list[dict[str, object]], fields: tuple[str, ...], metric_group: str) -> list[dict[str, object]]:
    by_peer: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        peer = _peer(row)
        if peer:
            by_peer.setdefault((row.get("radio"), peer), []).append(row)
    result: list[dict[str, object]] = []
    for (radio, peer), peer_rows in by_peer.items():
        item: dict[str, object] = {"metric_group": metric_group, "radio": radio, "peer_mac": peer, "peer": format_mac_h3c(peer), "sample_count": len(peer_rows)}
        for field_name in fields:
            values = [_number(row.get(field_name)) for row in peer_rows]
            values = [value for value in values if value is not None]
            item[f"{field_name}_avg"] = round(mean(values), 2) if values else ""
            item[f"{field_name}_min"] = min(values) if values else ""
            item[f"{field_name}_max"] = max(values) if values else ""
        result.append(item)
    return sorted(result, key=lambda item: (str(item.get("radio") or ""), str(item.get("peer_mac") or "")))


def _normalize_link_row(row: dict[str, object]) -> dict[str, object]:
    metrics = _json_dict(row.get("metrics_json"))
    normalized = dict(row)
    normalized["mr_rssi"] = metrics.get("local_rssi_db")
    normalized["peer_rssi"] = metrics.get("peer_rssi_db")
    normalized["local_tx_busy"] = metrics.get("local_tx_busy")
    normalized["peer_tx_busy"] = metrics.get("peer_tx_busy")
    normalized["local_rx_busy"] = metrics.get("local_rx_busy")
    normalized["peer_rx_busy"] = metrics.get("peer_rx_busy")
    normalized["local_rate_raw"] = metrics.get("local_rate_raw")
    normalized["peer_rate_raw"] = metrics.get("peer_rate_raw")
    return normalized


def _finish_segment(segment: dict[str, object], rows: list[dict[str, object]]) -> None:
    segment["duration_seconds"] = _seconds_between(segment.get("start_time"), segment.get("end_time")) or 0
    for output_key, input_key in (
        ("mr_rssi", "mr_rssi"),
        ("peer_rssi", "peer_rssi"),
        ("tx_busy", "local_tx_busy"),
        ("rx_busy", "local_rx_busy"),
        ("rate_raw", "local_rate_raw"),
    ):
        values = [_number(row.get(input_key)) for row in rows]
        values = [value for value in values if value is not None]
        segment[f"avg_{output_key}"] = round(mean(values), 2) if values else ""
        segment[f"min_{output_key}"] = min(values) if values else ""
        segment[f"max_{output_key}"] = max(values) if values else ""
    segment["first_mr_rssi"] = rows[0].get("mr_rssi") if rows else ""
    segment["source_files"] = ", ".join(sorted({str(row.get("archived_filename") or row.get("source_file") or "") for row in rows if row.get("archived_filename") or row.get("source_file")}))


def _group_by_radio_time(rows: list[dict[str, object]]) -> list[tuple[tuple[object, str], list[dict[str, object]]]]:
    grouped: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((row.get("radio"), str(row.get("sample_time") or "")), []).append(row)
    return sorted(grouped.items(), key=lambda item: (item[0][1], str(item[0][0])))


def _peer(row: dict[str, object]) -> str:
    return str(row.get("peer_mac_normalized") or row.get("peer_mac") or row.get("peer_mac_raw") or "").replace("-", "").replace(":", "").lower()


def _state(row: dict[str, object]) -> str:
    return str(row.get("link_state") or row.get("state") or "").upper()


def _json_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _seconds_between(start: object, end: object) -> float | None:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if start_dt is None or end_dt is None:
        return None
    return max((end_dt - start_dt).total_seconds(), 0.0)
