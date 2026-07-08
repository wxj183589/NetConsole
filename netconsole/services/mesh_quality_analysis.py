from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Callable

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, LINK_STATE_STANDBY, format_mac_h3c
from netconsole.services.mesh_rssi_stats import calc_numeric_stats


MR_RAW_MESH_LOG = "MR_RAW_MESH_LOG"
VEHICLE_MR_REALTIME_OFFLINE = "VEHICLE_MR_REALTIME_OFFLINE"
MAX_RAW_EVIDENCE_ROWS = 10000
MAX_RAW_EVIDENCE_ROWS_PER_EVENT = 12


@dataclass(frozen=True)
class MeshQualityRules:
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
    main_link_switch_time_ms: int = 2500
    pingpong_tolerance_ms: int = 500
    pingpong_return_window_ms: int | None = None
    short_active_segment_seconds: int = 5
    score_weights: dict[str, int] = field(
        default_factory=lambda: {
            "active_rssi": 30,
            "backup_health": 15,
            "switch_quality": 20,
            "busy_quality": 15,
            "link_stability": 15,
            "parse_integrity": 5,
        }
    )


@dataclass(frozen=True)
class MeshThresholdTemplate:
    key: str
    label: str
    business_type: str
    working_mode: str
    bandwidth: str
    ap_spacing: str
    description: str
    rules: MeshQualityRules


@dataclass
class MeshQualityReport:
    overview: dict[str, object]
    score_rows: list[dict[str, object]]
    source_files: list[dict[str, object]]
    sample_quality: list[dict[str, object]]
    active_segments: list[dict[str, object]]
    peer_ranking: list[dict[str, object]]
    switch_events: list[dict[str, object]]
    anomaly_events: list[dict[str, object]]
    no_backup_risks: list[dict[str, object]]
    busy_analysis: list[dict[str, object]]
    link_rebuild_events: list[dict[str, object]]
    raw_evidence: list[dict[str, object]]
    parse_issues: list[dict[str, object]]
    all_link_details: list[dict[str, object]]


def load_threshold_templates() -> dict[str, MeshThresholdTemplate]:
    defaults = load_default_rules()
    standard_pis = replace(
        defaults,
        rssi_excellent_threshold=42,
        rssi_good_threshold=32,
        rssi_warning_threshold=26,
        rssi_bad_threshold=20,
        backup_available_threshold=32,
        backup_strong_threshold=42,
        busy_warning_threshold=60,
        busy_bad_threshold=75,
        no_backup_min_seconds=5,
        weak_active_min_seconds=3,
        switch_late_window_seconds=5,
        switch_target_window_seconds=5,
        flap_window_seconds=30,
        short_active_segment_seconds=5,
    )
    high_quality_pis = replace(
        standard_pis,
        rssi_excellent_threshold=45,
        rssi_good_threshold=35,
        rssi_warning_threshold=28,
        rssi_bad_threshold=22,
        backup_available_threshold=35,
        backup_strong_threshold=45,
    )
    wifi5_pis = replace(
        standard_pis,
        rssi_excellent_threshold=40,
        rssi_good_threshold=30,
        rssi_warning_threshold=25,
        rssi_bad_threshold=20,
        backup_available_threshold=30,
        backup_strong_threshold=40,
    )
    dcs_dot11a = replace(
        standard_pis,
        rssi_excellent_threshold=35,
        rssi_good_threshold=28,
        rssi_warning_threshold=22,
        rssi_bad_threshold=18,
        backup_available_threshold=28,
        backup_strong_threshold=35,
        busy_warning_threshold=55,
        busy_bad_threshold=70,
        no_backup_min_seconds=15,
        weak_active_min_seconds=5,
        switch_late_window_seconds=8,
        switch_target_window_seconds=8,
        flap_window_seconds=45,
        short_active_segment_seconds=5,
    )
    templates = [
        MeshThresholdTemplate(
            "pis_wifi6_40_80_standard",
            "PIS - Wi-Fi6 - 40/80M - 标准间隔",
            "PIS",
            "Wi-Fi6 / 11ax",
            "40M / 80M 混合",
            "80~150m",
            "按 PIS 高吞吐业务评估，RSSI 与备份链路要求高于 DCS/20M 远间隔场景。",
            standard_pis,
        ),
        MeshThresholdTemplate(
            "pis_wifi6_80_high_quality",
            "PIS - Wi-Fi6 - 80M - 高质量覆盖",
            "PIS",
            "Wi-Fi6 / 11ax",
            "80M",
            "80~120m",
            "适用于高质量 PIS/视频业务和较密集覆盖，要求更高链路余量。",
            high_quality_pis,
        ),
        MeshThresholdTemplate(
            "pis_wifi5_80_normal",
            "PIS - Wi-Fi5 - 80M - 常规覆盖",
            "PIS",
            "Wi-Fi5 / 11ac",
            "80M",
            "100~150m",
            "适用于 Wi-Fi5/11ac 的常规 PIS 覆盖。",
            wifi5_pis,
        ),
        MeshThresholdTemplate(
            "dcs_wifi6_dot11a_20_far",
            "DCS - Wi-Fi6设备 - dot11a/20M - 远间隔",
            "DCS/信号",
            "强制 dot11a",
            "20M",
            "150~180m 或更远",
            "按低带宽远间隔稳定链路评估；低 RSSI 容忍度高于 PIS，但链路重建、无 Active、短时切换会被重点关注。",
            dcs_dot11a,
        ),
        MeshThresholdTemplate(
            "dcs_80211a_20_legacy",
            "DCS - 802.11a/20M - 老线兼容",
            "DCS/信号",
            "802.11a",
            "20M",
            "150~180m 或更远",
            "适用于老线 802.11a/20M 低吞吐业务，关注连续性和稳定性，不按 Wi-Fi6 高质量覆盖评估。",
            dcs_dot11a,
        ),
        MeshThresholdTemplate(
            "custom",
            "自定义",
            "自定义",
            "未知",
            "未知",
            "未知",
            "用户自定义阈值。设备代际不等于评估模板，应按实际工作模式和业务场景选择。",
            standard_pis,
        ),
    ]
    return {template.key: template for template in templates}


def load_threshold_template_rules() -> dict[str, MeshQualityRules]:
    return {key: template.rules for key, template in load_threshold_templates().items()}


def get_threshold_template(key: str) -> MeshThresholdTemplate:
    templates = load_threshold_templates()
    return templates.get(key) or templates["pis_wifi6_40_80_standard"]


def threshold_template_labels() -> dict[str, str]:
    return {key: template.label for key, template in load_threshold_templates().items()}


def template_overview_fields(template_key: str, rules: MeshQualityRules) -> dict[str, object]:
    template = get_threshold_template(template_key)
    overview = {
        "评估模板": template.label,
        "业务类型": template.business_type,
        "实际工作模式": template.working_mode,
        "频宽": template.bandwidth,
        "典型 AP 间隔": template.ap_spacing,
        "RSSI 良好线": rules.rssi_good_threshold,
        "可用备份线": rules.backup_available_threshold,
        "无备份风险窗口": f"{rules.no_backup_min_seconds}秒",
        "评估模板说明": template.description,
    }
    return overview


def load_default_rules() -> MeshQualityRules:
    path = Path(__file__).resolve().parents[1] / "resources" / "mesh_quality_rules.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return MeshQualityRules(
        rssi_excellent_threshold=int(data.get("rssi", {}).get("excellent", 40)),
        rssi_good_threshold=int(data.get("rssi", {}).get("good", 30)),
        rssi_warning_threshold=int(data.get("rssi", {}).get("warning", 25)),
        rssi_bad_threshold=int(data.get("rssi", {}).get("bad", 20)),
        backup_available_threshold=int(data.get("backup", {}).get("available_threshold", 30)),
        backup_strong_threshold=int(data.get("backup", {}).get("strong_threshold", 40)),
        no_backup_min_seconds=int(data.get("backup", {}).get("no_backup_min_seconds", 5)),
        busy_warning_threshold=int(data.get("busy", {}).get("warning_threshold", 60)),
        busy_bad_threshold=int(data.get("busy", {}).get("bad_threshold", 75)),
        switch_late_window_seconds=int(data.get("switch", {}).get("late_window_seconds", 5)),
        switch_target_window_seconds=int(data.get("switch", {}).get("target_window_seconds", 5)),
        flap_window_seconds=int(data.get("switch", {}).get("flap_window_seconds", 30)),
        main_link_switch_time_ms=int(data.get("switch", {}).get("main_link_switch_time_ms", 2500)),
        pingpong_tolerance_ms=int(data.get("switch", {}).get("pingpong_tolerance_ms", 500)),
        pingpong_return_window_ms=_optional_int(data.get("switch", {}).get("pingpong_return_window_ms")),
        short_active_segment_seconds=int(data.get("switch", {}).get("short_active_segment_seconds", 5)),
        weak_active_min_seconds=int(data.get("anomaly", {}).get("weak_active_min_seconds", 3)),
        score_weights={key: int(value) for key, value in dict(data.get("score_weights") or {}).items()},
    )


def _optional_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def percentile(values: list[float], ratio: float) -> float | str:
    finite = sorted(value for value in values if value is not None)
    if not finite:
        return ""
    if len(finite) == 1:
        return finite[0]
    pos = max(min(ratio, 1.0), 0.0) * (len(finite) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(finite) - 1)
    if lower == upper:
        return finite[lower]
    return round(finite[lower] + (finite[upper] - finite[lower]) * (pos - lower), 3)


def build_quality_report(
    rows: list[dict[str, object]],
    source_files: list[dict[str, object]],
    parse_issues: list[dict[str, object]],
    mr_name: str,
    report_name: str,
    data_source_type: str,
    rules: MeshQualityRules,
    *,
    include_raw_evidence: bool = True,
    include_all_link_details: bool = False,
    include_parse_issues: bool = True,
    include_busy_analysis: bool = True,
    threshold_template_key: str = "pis_wifi6_40_80_standard",
    excluded_region_keywords: tuple[str, ...] = (),
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MeshQualityReport:
    progress = progress or (lambda _value, _stage: None)
    should_cancel = should_cancel or (lambda: False)
    normalized = mark_excluded_rows(normalize_samples(rows), excluded_region_keywords)
    analysis_rows = [row for row in normalized if not row.get("excluded")]
    excluded_source_files = mark_excluded_source_files(source_files, normalized)
    _cancel(should_cancel)
    progress(12, "normalize_samples")
    _cancel(should_cancel)
    progress(18, "sample_quality")
    sample_quality = build_sample_quality(analysis_rows, rules)
    _cancel(should_cancel)
    progress(30, "active_segments")
    active_segments = build_active_segments(sample_quality, analysis_rows, rules)
    _cancel(should_cancel)
    progress(42, "switch_analysis")
    switch_events = analyze_switch_events(active_segments, sample_quality, rules)
    progress(50, "peer_ranking")
    peer_ranking = build_peer_quality(analysis_rows, active_segments, switch_events, rules)
    _cancel(should_cancel)
    progress(56, "anomaly_analysis")
    anomaly_events = analyze_anomaly_events(sample_quality, analysis_rows, rules, include_busy_analysis=include_busy_analysis)
    no_backup_risks = [event for event in anomaly_events if event.get("event_type") == "NO_BACKUP"]
    _cancel(should_cancel)
    progress(68, "busy_analysis")
    busy_analysis = build_busy_analysis(analysis_rows, rules) if include_busy_analysis else []
    _cancel(should_cancel)
    progress(76, "link_rebuild_analysis")
    rebuild_events = analyze_link_rebuilds(analysis_rows)
    _cancel(should_cancel)
    progress(84, "raw_evidence")
    raw_evidence = collect_raw_evidence(normalized, switch_events, anomaly_events, rebuild_events) if include_raw_evidence else []
    score_rows, total_score, score_level, tags = build_score_rows(sample_quality, switch_events, anomaly_events, rebuild_events, parse_issues if include_parse_issues else [], rules)
    overview = build_overview(
        mr_name,
        report_name,
        data_source_type,
        excluded_source_files,
        analysis_rows,
        active_segments,
        switch_events,
        anomaly_events,
        rebuild_events,
        parse_issues if include_parse_issues else [],
        total_score,
        score_level,
        tags,
        threshold_template_key,
        rules,
        tuple(keyword for keyword in excluded_region_keywords if str(keyword).strip()),
        len(normalized) - len(analysis_rows),
    )
    return MeshQualityReport(
        overview=overview,
        score_rows=score_rows,
        source_files=excluded_source_files,
        sample_quality=sample_quality,
        active_segments=active_segments,
        peer_ranking=peer_ranking,
        switch_events=switch_events,
        anomaly_events=anomaly_events,
        no_backup_risks=no_backup_risks,
        busy_analysis=busy_analysis,
        link_rebuild_events=rebuild_events,
        raw_evidence=raw_evidence,
        parse_issues=parse_issues if include_parse_issues else [],
        all_link_details=normalized if include_all_link_details else [],
    )


def normalize_samples(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        metrics = _json_dict(row.get("metrics_json"))
        item = dict(row)
        item["peer_mac"] = _peer(row)
        item["peer_mac_display"] = format_mac_h3c(item["peer_mac"]) if item["peer_mac"] else str(row.get("peer_mac_raw") or "")
        item["mr_rssi"] = _num(row.get("mr_rssi"), metrics.get("local_rssi_db"))
        item["peer_rssi"] = _num(row.get("peer_rssi"), metrics.get("peer_rssi_db"))
        item["tx_busy"] = _num(row.get("local_tx_busy"), metrics.get("local_tx_busy"))
        item["rx_busy"] = _num(row.get("local_rx_busy"), metrics.get("local_rx_busy"))
        item["peer_tx_busy"] = _num(row.get("peer_tx_busy"), metrics.get("peer_tx_busy"))
        item["peer_rx_busy"] = _num(row.get("peer_rx_busy"), metrics.get("peer_rx_busy"))
        item["fping_loss_rate"] = None
        item["fping_latency_ms"] = None
        item["interface_in_rate"] = None
        item["interface_out_rate"] = None
        item["realtime_channelbusy"] = None
        item["realtime_radio_statistics"] = None
        result.append(item)
    return sorted(result, key=lambda row: (str(row.get("sample_time") or ""), str(row.get("radio") or ""), int(row.get("id") or 0)))


def mark_excluded_rows(rows: list[dict[str, object]], keywords: tuple[str, ...]) -> list[dict[str, object]]:
    normalized_keywords = tuple(str(keyword).strip().lower() for keyword in keywords if str(keyword).strip())
    if not normalized_keywords:
        return [dict(row, excluded=False) for row in rows]
    result = []
    for row in rows:
        site = str(row.get("peer_site") or "").lower()
        excluded = any(keyword in site for keyword in normalized_keywords)
        result.append(dict(row, excluded=excluded))
    return result


def mark_excluded_source_files(source_files: list[dict[str, object]], rows: list[dict[str, object]]) -> list[dict[str, object]]:
    excluded_by_source: dict[int, bool] = {}
    seen_by_source: set[int] = set()
    for row in rows:
        source_file_id = int(row.get("source_file_id") or 0)
        if source_file_id <= 0:
            continue
        seen_by_source.add(source_file_id)
        excluded_by_source[source_file_id] = bool(row.get("excluded")) or excluded_by_source.get(source_file_id, False)
    result = []
    for source in source_files:
        item = dict(source)
        source_file_id = int(item.get("id") or 0)
        item["excluded"] = bool(excluded_by_source.get(source_file_id, False)) if source_file_id in seen_by_source else False
        result.append(item)
    return result


def build_sample_quality(rows: list[dict[str, object]], rules: MeshQualityRules) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    no_backup_since: dict[object, str] = {}
    for (radio, sample_time), sample_rows in _group_by_radio_time(rows):
        active_rows = [row for row in sample_rows if _state(row) == LINK_STATE_ACTIVE]
        standby_rows = [row for row in sample_rows if _state(row) == LINK_STATE_STANDBY]
        active = active_rows[0] if len(active_rows) == 1 else None
        backups = [row for row in standby_rows if (_num(row.get("mr_rssi")) or 0) >= rules.backup_available_threshold]
        strong = [row for row in standby_rows if (_num(row.get("mr_rssi")) or 0) >= rules.backup_strong_threshold]
        best_backup = max(backups, key=lambda row: _num(row.get("mr_rssi")) or -1, default=None)
        active_rssi = _num(active.get("mr_rssi")) if active else None
        active_tx = _num(active.get("tx_busy")) if active else None
        active_rx = _num(active.get("rx_busy")) if active else None
        max_tx = max([_num(row.get("tx_busy")) for row in sample_rows if _num(row.get("tx_busy")) is not None], default=None)
        max_rx = max([_num(row.get("rx_busy")) for row in sample_rows if _num(row.get("rx_busy")) is not None], default=None)
        reasons: list[str] = []
        level = "EXCELLENT"
        if len(active_rows) == 0:
            level, reasons = "BAD", ["短时无 Active"]
        elif len(active_rows) > 1:
            level, reasons = "BAD", ["短时多 Active"]
        elif active_rssi is None:
            level, reasons = "CRITICAL", ["Active RSSI 缺失"]
        elif active_rssi < rules.rssi_bad_threshold:
            level, reasons = "CRITICAL", ["Active RSSI 严重偏低"]
        elif active_rssi < rules.rssi_warning_threshold:
            level, reasons = "BAD", ["Active RSSI 偏差"]
        elif active_rssi < rules.rssi_good_threshold:
            level, reasons = "WARNING", ["Active RSSI 关注"]
        elif active_rssi < rules.rssi_excellent_threshold:
            level, reasons = "GOOD", ["Active RSSI 良好"]
        if max((active_tx or 0), (active_rx or 0), (max_tx or 0), (max_rx or 0)) >= rules.busy_bad_threshold:
            level = _worse(level, "BAD")
            reasons.append("Busy 严重偏高")
        elif max((active_tx or 0), (active_rx or 0), (max_tx or 0), (max_rx or 0)) >= rules.busy_warning_threshold:
            level = _worse(level, "WARNING")
            reasons.append("Busy 关注")
        no_backup_seconds = 0.0
        if active and not backups:
            start = no_backup_since.setdefault(radio, sample_time)
            no_backup_seconds = _seconds_between(start, sample_time) or 0.0
            if no_backup_seconds >= rules.no_backup_min_seconds:
                level = _worse(level, "WARNING")
                reasons.append("无可用备份链路")
        else:
            no_backup_since.pop(radio, None)
        score = _score_from_level(level)
        samples.append(
            {
                "sample_time": sample_time,
                "radio": radio,
                "total_peer_count": len(sample_rows),
                "active_peer_count": len(active_rows),
                "active_peer_mac": active.get("peer_mac_display") if active else "",
                "active_peer_key": active.get("peer_mac") if active else "",
                "active_mr_rssi": active_rssi if active_rssi is not None else "",
                "active_peer_rssi": _num(active.get("peer_rssi")) if active else "",
                "standby_peer_count": len(standby_rows),
                "available_backup_count": len(backups),
                "strong_backup_count": len(strong),
                "best_backup_peer_mac": best_backup.get("peer_mac_display") if best_backup else "",
                "best_backup_peer_key": best_backup.get("peer_mac") if best_backup else "",
                "best_backup_rssi": _num(best_backup.get("mr_rssi")) if best_backup else "",
                "active_tx_busy": active_tx if active_tx is not None else "",
                "active_rx_busy": active_rx if active_rx is not None else "",
                "max_tx_busy": max_tx if max_tx is not None else "",
                "max_rx_busy": max_rx if max_rx is not None else "",
                "link_count": active.get("link_count") if active else "",
                "active_link_cnt": active.get("link_count") if active else "",
                "active_establish_time": active.get("establish_time") if active else "",
                "active_duration_time": active.get("duration_seconds") if active else "",
                "source_file_id": active.get("source_file_id") if active else sample_rows[0].get("source_file_id"),
                "source_file": active.get("archived_filename") or active.get("source_file") if active else (sample_rows[0].get("archived_filename") or ""),
                "source_line_number": active.get("source_line_number") if active else sample_rows[0].get("source_line_number"),
                "quality_level": level,
                "quality_score": score,
                "quality_reasons": "; ".join(dict.fromkeys(reasons)),
                "no_backup_seconds": no_backup_seconds,
            }
        )
    return samples


def build_active_segments(samples: list[dict[str, object]], rows: list[dict[str, object]], rules: MeshQualityRules) -> list[dict[str, object]]:
    segments = []
    current: dict[str, object] | None = None
    current_samples: list[dict[str, object]] = []
    row_index = _build_peer_time_index(rows)
    interval_by_radio = _sample_interval_by_scope(samples)
    for sample in samples:
        peer = str(sample.get("active_peer_key") or "")
        if not peer:
            if current:
                _finish_segment(current, current_samples, row_index, rules)
                segments.append(current)
            current, current_samples = None, []
            continue
        if current and current.get("source_file_id") == sample.get("source_file_id") and current.get("radio") == sample.get("radio") and current.get("active_peer_key") == peer:
            current["end_time"] = sample.get("sample_time")
            current_samples.append(sample)
            continue
        if current:
            _finish_segment(current, current_samples, row_index, rules)
            segments.append(current)
        current = {
            "sequence": len(segments) + 1,
            "source_file_id": sample.get("source_file_id"),
            "radio": sample.get("radio"),
            "active_peer_key": peer,
            "active_peer_mac": sample.get("active_peer_mac"),
            "sample_interval_seconds": interval_by_radio.get((sample.get("source_file_id"), sample.get("radio")), 1.0),
            "start_time": sample.get("sample_time"),
            "end_time": sample.get("sample_time"),
        }
        current_samples = [sample]
    if current:
        _finish_segment(current, current_samples, row_index, rules)
        segments.append(current)
    return segments


def analyze_switch_events(segments: list[dict[str, object]], samples: list[dict[str, object]], rules: MeshQualityRules) -> list[dict[str, object]]:
    events = []
    by_radio: dict[tuple[object, object], list[dict[str, object]]] = {}
    for segment in segments:
        by_radio.setdefault((segment.get("source_file_id"), segment.get("radio")), []).append(segment)
    sample_index = _build_source_radio_time_index(samples)
    for (_source_file_id, radio), radio_segments in by_radio.items():
        ordered = sorted(radio_segments, key=lambda row: str(row.get("start_time") or ""))
        for index, (previous, current) in enumerate(zip(ordered, ordered[1:])):
            if previous.get("active_peer_key") == current.get("active_peer_key"):
                continue
            scope = (current.get("source_file_id"), radio)
            before = _samples_between_indexed(sample_index, samples, scope, previous.get("end_time"), rules.switch_late_window_seconds, before=True)
            after = _samples_between_indexed(sample_index, samples, scope, current.get("start_time"), rules.switch_target_window_seconds, before=False)
            switch_type = "NORMAL_SWITCH"
            severity = "GOOD"
            diagnosis = "主链路切换未发现明显异常。"
            pingpong = _classify_pingpong_switch(ordered, index, rules)
            if pingpong and pingpong.get("is_pingpong_abnormal"):
                switch_type, severity, diagnosis = "FLAP_SWITCH", "WARNING", str(pingpong.get("judgment_reason") or "出现 AP 乒乓切换异常。")
            if _num(current.get("duration_seconds")) is not None and float(current.get("duration_seconds") or 0) < rules.short_active_segment_seconds and switch_type == "NORMAL_SWITCH":
                switch_type, severity, diagnosis = "SHORT_SEGMENT_SWITCH", "WARNING", "新 Active 区段持续时间过短。"
            if switch_type == "NORMAL_SWITCH" and before and (_all_low(before, rules.rssi_good_threshold) and _has_better_backup(before) or _all_low(before, rules.rssi_warning_threshold)):
                switch_type, severity, diagnosis = "LATE_SWITCH", "BAD", "切换前主链路 RSSI 已偏低且未及时切换。"
            if switch_type == "NORMAL_SWITCH" and after and (_avg([_num(row.get("active_mr_rssi")) for row in after]) < rules.rssi_good_threshold or min([_num(row.get("active_mr_rssi")) for row in after if _num(row.get("active_mr_rssi")) is not None], default=999) < rules.rssi_warning_threshold):
                switch_type, severity, diagnosis = "WEAK_TARGET_SWITCH", "BAD", "切入后的新主链路 RSSI 偏低。"
            evidence_id = f"SW{len(events) + 1:04d}"
            events.append(
                {
                    "sequence": len(events) + 1,
                    "radio": radio,
                    "switch_time": current.get("start_time"),
                    "from_peer": previous.get("active_peer_mac"),
                    "from_peer_ap_name": previous.get("peer_ap_name") or "",
                    "to_peer": current.get("active_peer_mac"),
                    "to_peer_ap_name": current.get("peer_ap_name") or "",
                    "previous_segment_duration": previous.get("duration_seconds"),
                    "new_segment_duration": current.get("duration_seconds"),
                    "from_last_rssi": previous.get("last_mr_rssi"),
                    "from_avg_rssi_before_switch": _avg([_num(row.get("active_mr_rssi")) for row in before]),
                    "to_first_rssi": current.get("first_mr_rssi"),
                    "to_avg_rssi_after_switch": _avg([_num(row.get("active_mr_rssi")) for row in after]),
                    "best_backup_peer_before_switch": before[-1].get("best_backup_peer_mac") if before else "",
                    "best_backup_rssi_before_switch": before[-1].get("best_backup_rssi") if before else "",
                    "tx_busy_before_switch": before[-1].get("active_tx_busy") if before else "",
                    "rx_busy_before_switch": before[-1].get("active_rx_busy") if before else "",
                    "tx_busy_after_switch": after[0].get("active_tx_busy") if after else "",
                    "rx_busy_after_switch": after[0].get("active_rx_busy") if after else "",
                    "switch_type": switch_type,
                    "severity": severity,
                    "diagnosis": diagnosis,
                    "is_ap_return_event": bool(pingpong.get("is_ap_return_event")) if pingpong else False,
                    "is_pingpong_abnormal": bool(pingpong.get("is_pingpong_abnormal")) if pingpong else False,
                    "pingpong_type": pingpong.get("pingpong_type") if pingpong else "",
                    "pingpong_group_id": pingpong.get("pingpong_group_id") if pingpong else "",
                    "pingpong_return_duration_ms": pingpong.get("pingpong_return_duration_ms") if pingpong else "",
                    "middle_ap_dwell_ms": pingpong.get("middle_ap_dwell_ms") if pingpong else "",
                    "previous_ap": pingpong.get("previous_ap") if pingpong else "",
                    "middle_ap": pingpong.get("middle_ap") if pingpong else "",
                    "return_ap": pingpong.get("return_ap") if pingpong else "",
                    "pingpong_judgment_reason": pingpong.get("judgment_reason") if pingpong else "",
                    "suggestion": _switch_suggestion(switch_type),
                    "evidence_id": evidence_id,
                }
            )
    return sorted(events, key=lambda row: str(row.get("switch_time") or ""))


def analyze_anomaly_events(samples: list[dict[str, object]], rows: list[dict[str, object]], rules: MeshQualityRules, *, include_busy_analysis: bool = True) -> list[dict[str, object]]:
    predicates = [
        ("NO_ACTIVE", lambda s: int(s.get("active_peer_count") or 0) == 0, "BAD", "该时间段没有任何 Active 主链路。"),
        ("MULTI_ACTIVE", lambda s: int(s.get("active_peer_count") or 0) > 1, "BAD", "同一采样点出现多条 Active 主链路。"),
        ("WEAK_ACTIVE", lambda s: _num(s.get("active_mr_rssi")) is not None and _num(s.get("active_mr_rssi")) < rules.rssi_good_threshold, "WARNING", "Active RSSI 持续低于良好阈值。"),
        ("BAD_ACTIVE", lambda s: _num(s.get("active_mr_rssi")) is not None and _num(s.get("active_mr_rssi")) < rules.rssi_bad_threshold, "CRITICAL", "Active RSSI 严重偏低。"),
        ("NO_BACKUP", lambda s: int(s.get("active_peer_count") or 0) == 1 and int(s.get("available_backup_count") or 0) == 0, "WARNING", "Active 存在但无可用备份链路。"),
    ]
    if include_busy_analysis:
        predicates.extend(
            [
                ("HIGH_BUSY", lambda s: max(_num(s.get("active_tx_busy")) or 0, _num(s.get("active_rx_busy")) or 0, _num(s.get("max_tx_busy")) or 0, _num(s.get("max_rx_busy")) or 0) >= rules.busy_bad_threshold, "BAD", "TxBusy 或 RxBusy 达到严重阈值。"),
                ("BUSY_WARNING", lambda s: max(_num(s.get("active_tx_busy")) or 0, _num(s.get("active_rx_busy")) or 0, _num(s.get("max_tx_busy")) or 0, _num(s.get("max_rx_busy")) or 0) >= rules.busy_warning_threshold, "WARNING", "TxBusy 或 RxBusy 达到关注阈值。"),
            ]
        )
    events = []
    min_duration = {"NO_BACKUP": rules.no_backup_min_seconds, "WEAK_ACTIVE": rules.weak_active_min_seconds}
    for event_type, predicate, severity, diagnosis in predicates:
        for block in _merge_samples(samples, predicate, rules):
            duration = _duration(block)
            if duration < min_duration.get(event_type, 0):
                continue
            active_values = [_num(row.get("active_mr_rssi")) for row in block]
            event = {
                "event_sequence": len(events) + 1,
                "event_time_start": block[0].get("sample_time"),
                "event_time_end": block[-1].get("sample_time"),
                "duration_seconds": duration,
                "radio": block[0].get("radio"),
                "event_type": event_type,
                "severity": severity,
                "active_peer": block[0].get("active_peer_mac"),
                "peer_ap_name": "",
                "active_rssi_min": _min(active_values),
                "active_rssi_avg": _avg(active_values),
                "backup_count_min": min((int(row.get("available_backup_count") or 0) for row in block), default=""),
                "tx_busy_max": _max([_num(row.get("active_tx_busy")) for row in block] + [_num(row.get("max_tx_busy")) for row in block]),
                "rx_busy_max": _max([_num(row.get("active_rx_busy")) for row in block] + [_num(row.get("max_rx_busy")) for row in block]),
                "source_file": block[0].get("source_file"),
                "source_line_number_start": block[0].get("source_line_number"),
                "source_line_number_end": block[-1].get("source_line_number"),
                "diagnosis": diagnosis,
                "suggestion": _anomaly_suggestion(event_type),
                "evidence_id": f"EV{len(events) + 1:04d}",
            }
            events.append(event)
    return sorted(events, key=lambda row: (str(row.get("event_time_start") or ""), str(row.get("event_type") or "")))


def build_peer_quality(rows: list[dict[str, object]], segments: list[dict[str, object]], switches: list[dict[str, object]], rules: MeshQualityRules) -> list[dict[str, object]]:
    result = []
    for (radio, peer), peer_rows in _group_by_peer(rows).items():
        active_rows = [row for row in peer_rows if _state(row) == LINK_STATE_ACTIVE]
        standby_rows = [row for row in peer_rows if _state(row) == LINK_STATE_STANDBY]
        peer_segments = [row for row in segments if row.get("radio") == radio and row.get("active_peer_key") == peer]
        values = [_num(row.get("mr_rssi")) for row in active_rows]
        weak_seconds = sum(float(segment.get("weak_rssi_seconds") or 0) for segment in peer_segments)
        no_backup_seconds = sum(float(segment.get("no_backup_seconds") or 0) for segment in peer_segments)
        tags = []
        if _min(values) != "" and _min(values) < rules.rssi_good_threshold:
            tags.append("弱覆盖")
        if no_backup_seconds > 0:
            tags.append("无备份链路")
        if any(float(segment.get("duration_reset_count") or 0) + float(segment.get("link_count_delta_count") or 0) for segment in peer_segments):
            tags.append("链路重建异常")
        item = {
            "radio": radio,
            "peer_mac": format_mac_h3c(peer) if peer else "",
            "peer_ap_name": peer_rows[0].get("peer_ap_name") or "",
            "peer_ap_mac": format_mac_h3c(str(peer_rows[0].get("peer_ap_mac") or "")) if peer_rows[0].get("peer_ap_mac") else "",
            "peer_site": peer_rows[0].get("peer_site") or "",
            "peer_radio": peer_rows[0].get("peer_radio") or peer_rows[0].get("peer_radio_label") or "",
            "first_seen_time": peer_rows[0].get("sample_time"),
            "last_seen_time": peer_rows[-1].get("sample_time"),
            "seen_sample_count": len(peer_rows),
            "active_sample_count": len(active_rows),
            "standby_sample_count": len(standby_rows),
            "active_segment_count": len(peer_segments),
            "switch_in_count": len([event for event in switches if event.get("radio") == radio and _canonical(event.get("to_peer")) == peer]),
            "switch_out_count": len([event for event in switches if event.get("radio") == radio and _canonical(event.get("from_peer")) == peer]),
            "active_total_seconds": sum(float(segment.get("duration_seconds") or 0) for segment in peer_segments),
            "active_total_ratio": round(len(active_rows) / max(len(peer_rows), 1), 4),
            "avg_active_rssi": _avg(values),
            "min_active_rssi": _min(values),
            "p10_active_rssi": percentile([value for value in values if value is not None], 0.1),
            "max_active_rssi": _max(values),
            "rssi_jitter": _jitter(values),
            "weak_active_seconds": weak_seconds,
            "no_backup_when_active_seconds": no_backup_seconds,
            "avg_tx_busy": _avg([_num(row.get("tx_busy")) for row in active_rows]),
            "max_tx_busy": _max([_num(row.get("tx_busy")) for row in active_rows]),
            "avg_rx_busy": _avg([_num(row.get("rx_busy")) for row in active_rows]),
            "max_rx_busy": _max([_num(row.get("rx_busy")) for row in active_rows]),
            "link_rebuild_count": sum(int(segment.get("link_count_delta_count") or 0) + int(segment.get("duration_reset_count") or 0) + int(segment.get("establish_reset_count") or 0) for segment in peer_segments),
            "short_segment_count": len([segment for segment in peer_segments if float(segment.get("duration_seconds") or 0) < rules.short_active_segment_seconds]),
            "flap_related_count": len([event for event in switches if _is_pingpong_abnormal_event(event) and (_canonical(event.get("to_peer")) == peer or _canonical(event.get("from_peer")) == peer)]),
            "peer_quality_score": max(0, 100 - len(tags) * 15),
            "problem_tags": "; ".join(tags),
            "suggestion": _peer_suggestion(tags),
        }
        result.append(item)
    return sorted(result, key=lambda row: (-(row.get("link_rebuild_count") or 0), row.get("peer_quality_score") or 0, str(row.get("peer_mac") or "")))


def build_busy_analysis(rows: list[dict[str, object]], rules: MeshQualityRules) -> list[dict[str, object]]:
    result = []
    for (radio, peer), peer_rows in _group_by_peer([row for row in rows if _state(row) == LINK_STATE_ACTIVE]).items():
        tx = [_num(row.get("tx_busy")) for row in peer_rows]
        rx = [_num(row.get("rx_busy")) for row in peer_rows]
        rssi = [_num(row.get("mr_rssi")) for row in peer_rows]
        warning = len([row for row in peer_rows if max(_num(row.get("tx_busy")) or 0, _num(row.get("rx_busy")) or 0) >= rules.busy_warning_threshold])
        bad = len([row for row in peer_rows if max(_num(row.get("tx_busy")) or 0, _num(row.get("rx_busy")) or 0) >= rules.busy_bad_threshold])
        busy_level = "GOOD" if bad == 0 and warning == 0 else "BAD" if bad else "WARNING"
        avg_rssi = _avg(rssi)
        busy_high = bad > 0 or warning > 0
        rssi_low = avg_rssi != "" and avg_rssi < rules.rssi_good_threshold
        diagnosis = "RSSI 正常且 Busy 正常。"
        if rssi_low and not busy_high:
            diagnosis = "RSSI 差，Busy 正常，偏覆盖问题。"
        elif not rssi_low and busy_high:
            diagnosis = "RSSI 正常，Busy 高，偏空口干扰/负载/同频竞争。"
        elif rssi_low and busy_high:
            diagnosis = "RSSI 差且 Busy 高，覆盖和空口问题叠加。"
        result.append(
            {
                "radio": radio,
                "peer_mac": format_mac_h3c(peer),
                "peer_ap_name": peer_rows[0].get("peer_ap_name") or "",
                "sample_count": len(peer_rows),
                "avg_tx_busy": _avg(tx),
                "max_tx_busy": _max(tx),
                "p90_tx_busy": percentile([value for value in tx if value is not None], 0.9),
                "avg_rx_busy": _avg(rx),
                "max_rx_busy": _max(rx),
                "p90_rx_busy": percentile([value for value in rx if value is not None], 0.9),
                "busy_warning_seconds": warning,
                "busy_bad_seconds": bad,
                "busy_ratio": round((warning + bad) / max(len(peer_rows), 1), 4),
                "busy_level": busy_level,
                "diagnosis": diagnosis,
            }
        )
    return result


def analyze_link_rebuilds(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    events = []
    previous_by_peer: dict[tuple[object, str], dict[str, object]] = {}
    for row in rows:
        if _state(row) != LINK_STATE_ACTIVE:
            continue
        key = (row.get("radio"), str(row.get("peer_mac") or ""))
        previous = previous_by_peer.get(key)
        if previous:
            rebuild_type = ""
            if _num(row.get("link_count")) is not None and _num(previous.get("link_count")) is not None and _num(row.get("link_count")) > _num(previous.get("link_count")):
                rebuild_type = "LINKCNT_INCREASE"
            elif _num(row.get("duration_seconds")) is not None and _num(previous.get("duration_seconds")) is not None and _num(row.get("duration_seconds")) < _num(previous.get("duration_seconds")):
                rebuild_type = "DURATION_RESET"
            elif row.get("establish_time") and previous.get("establish_time") and row.get("establish_time") != previous.get("establish_time"):
                rebuild_type = "ESTABLISH_RESET"
            if rebuild_type:
                events.append(
                    {
                        "sequence": len(events) + 1,
                        "event_time": row.get("sample_time"),
                        "radio": row.get("radio"),
                        "peer_mac": row.get("peer_mac_display"),
                        "peer_ap_name": row.get("peer_ap_name") or "",
                        "previous_link_cnt": previous.get("link_count"),
                        "current_link_cnt": row.get("link_count"),
                        "previous_duration_time": previous.get("duration_seconds"),
                        "current_duration_time": row.get("duration_seconds"),
                        "previous_establish_time": previous.get("establish_time"),
                        "current_establish_time": row.get("establish_time"),
                        "rebuild_type": rebuild_type,
                        "severity": "BAD",
                        "diagnosis": "Active peer 未变化但链路计数或时间字段出现重建特征。",
                        "source_file": row.get("archived_filename") or row.get("source_file"),
                        "source_line_number": row.get("source_line_number"),
                        "raw_line": row.get("raw_line"),
                        "evidence_id": f"RB{len(events) + 1:04d}",
                    }
                )
        previous_by_peer[key] = row
    return events


def collect_raw_evidence(rows: list[dict[str, object]], switches: list[dict[str, object]], anomalies: list[dict[str, object]], rebuilds: list[dict[str, object]]) -> list[dict[str, object]]:
    evidence = []
    seen: set[tuple[object, object, object]] = set()
    time_index = _build_radio_time_index(rows)
    line_index: dict[tuple[object, object], list[dict[str, object]]] = {}
    for row in rows:
        line_index.setdefault((row.get("radio"), row.get("source_line_number")), []).append(row)

    def add(related_sheet: str, related_sequence: object, related_event_type: object, evidence_id: str, candidates: list[dict[str, object]]) -> None:
        if len(evidence) >= MAX_RAW_EVIDENCE_ROWS:
            return
        for row in candidates[:MAX_RAW_EVIDENCE_ROWS_PER_EVENT]:
            if len(evidence) >= MAX_RAW_EVIDENCE_ROWS:
                return
            key = (row.get("source_file_id"), row.get("source_line_number"), related_sequence)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "related_sheet": related_sheet,
                    "related_sequence": related_sequence,
                    "related_event_type": related_event_type,
                    "radio": row.get("radio"),
                    "sample_time": row.get("sample_time"),
                    "source_file": row.get("archived_filename") or row.get("source_file"),
                    "source_line_number": row.get("source_line_number"),
                    "link_state": row.get("link_state"),
                    "peer_mac": row.get("peer_mac_display"),
                    "peer_ap_name": row.get("peer_ap_name") or "",
                    "mr_rssi": row.get("mr_rssi"),
                    "peer_rssi": row.get("peer_rssi"),
                    "tx_busy": row.get("tx_busy"),
                    "rx_busy": row.get("rx_busy"),
                    "link_cnt": row.get("link_count"),
                    "establish_time": row.get("establish_time"),
                    "duration_time": row.get("duration_seconds"),
                    "raw_line": row.get("raw_line"),
                }
            )

    for event in switches:
        radio = event.get("radio")
        switch_time = event.get("switch_time")
        add("切换事件分析", event.get("sequence"), event.get("switch_type"), str(event.get("evidence_id") or ""), _rows_around(time_index, radio, switch_time, 5))
    for event in anomalies:
        radio = event.get("radio")
        add("异常事件分析", event.get("event_sequence"), event.get("event_type"), str(event.get("evidence_id") or ""), _rows_between_time(time_index, radio, event.get("event_time_start"), event.get("event_time_end")))
    for event in rebuilds:
        add("链路重建计数异常", event.get("sequence"), event.get("rebuild_type"), str(event.get("evidence_id") or ""), line_index.get((event.get("radio"), event.get("source_line_number")), []))
    return evidence


def build_score_rows(samples: list[dict[str, object]], switches: list[dict[str, object]], anomalies: list[dict[str, object]], rebuilds: list[dict[str, object]], parse_issues: list[dict[str, object]], rules: MeshQualityRules) -> tuple[list[dict[str, object]], int, str, list[str]]:
    weights = rules.score_weights
    penalties = {
        "active_rssi": len([s for s in samples if _num(s.get("active_mr_rssi")) is not None and _num(s.get("active_mr_rssi")) < rules.rssi_good_threshold]) / max(len(samples), 1),
        "backup_health": len([e for e in anomalies if e.get("event_type") == "NO_BACKUP"]) / max(len(samples), 1),
        "switch_quality": len([s for s in switches if s.get("switch_type") != "NORMAL_SWITCH"]) / max(len(switches), 1),
        "busy_quality": len([e for e in anomalies if e.get("event_type") in {"HIGH_BUSY", "BUSY_WARNING"}]) / max(len(samples), 1),
        "link_stability": len(rebuilds) / max(len(samples), 1),
        "parse_integrity": len(parse_issues) / max(len(samples), 1),
    }
    rows = []
    total = 0.0
    names = {
        "active_rssi": "主链路 RSSI",
        "backup_health": "备份链路健康度",
        "switch_quality": "切换质量",
        "busy_quality": "空口繁忙度",
        "link_stability": "链路稳定性",
        "parse_integrity": "解析完整性",
    }
    for key, weight in weights.items():
        score = max(0.0, weight * (1.0 - min(penalties.get(key, 0.0) * 3, 1.0)))
        total += score
        rows.append({"dimension": names.get(key, key), "weight": weight, "score": round(score, 2), "diagnosis": "N/A" if key == "parse_integrity" and not parse_issues else ""})
    final = int(round(total))
    tags = _problem_tags(samples, switches, anomalies, rebuilds, parse_issues)
    return rows, final, _score_level(final), tags


def build_overview(
    mr_name: str,
    report_name: str,
    data_source_type: str,
    source_files: list[dict[str, object]],
    rows: list[dict[str, object]],
    segments: list[dict[str, object]],
    switches: list[dict[str, object]],
    anomalies: list[dict[str, object]],
    rebuilds: list[dict[str, object]],
    parse_issues: list[dict[str, object]],
    score: int,
    score_level: str,
    tags: list[str],
    threshold_template_key: str = "pis_wifi6_40_80_standard",
    rules: MeshQualityRules | None = None,
    excluded_region_keywords: tuple[str, ...] = (),
    excluded_link_count: int = 0,
) -> dict[str, object]:
    sample_keys = {(row.get("radio"), row.get("sample_time")) for row in rows}
    return {
        "报告名称": report_name or mr_name,
        "MR 名称": mr_name,
        "数据来源类型": data_source_type,
        "生成时间": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "源文件数量": len(source_files),
        "排除区域规则": "、".join(excluded_region_keywords) if excluded_region_keywords else "未启用",
        "排除区域链路记录数": excluded_link_count,
        "采样时间范围": f"{min((str(row.get('sample_time')) for row in rows if row.get('sample_time')), default='')} ~ {max((str(row.get('sample_time')) for row in rows if row.get('sample_time')), default='')}",
        "Radio 数量": len({row.get("radio") for row in rows if row.get("radio") is not None}),
        "Peer 数量": len({row.get("peer_mac") for row in rows if row.get("peer_mac")}),
        "总采样点数量": len(sample_keys),
        "总链路记录数": len(rows),
        "Active 区段数量": len(segments),
        "主链路切换次数": len(switches),
        "乒乓切换次数": len([event for event in switches if _is_pingpong_abnormal_event(event)]),
        "切换滞后次数": len([event for event in switches if event.get("switch_type") == "LATE_SWITCH"]),
        "切入质量差次数": len([event for event in switches if event.get("switch_type") == "WEAK_TARGET_SWITCH"]),
        "无 Active 次数": len([event for event in anomalies if event.get("event_type") == "NO_ACTIVE"]),
        "多 Active 次数": len([event for event in anomalies if event.get("event_type") == "MULTI_ACTIVE"]),
        "无备份风险时长": sum(float(event.get("duration_seconds") or 0) for event in anomalies if event.get("event_type") == "NO_BACKUP"),
        "弱主链路时长": sum(float(event.get("duration_seconds") or 0) for event in anomalies if event.get("event_type") in {"WEAK_ACTIVE", "BAD_ACTIVE"}),
        "空口繁忙风险时长": sum(float(event.get("duration_seconds") or 0) for event in anomalies if event.get("event_type") in {"HIGH_BUSY", "BUSY_WARNING"}),
        "链路重建异常次数": len(rebuilds),
        "解析问题数量": len(parse_issues),
        "综合评分": score,
        "评分等级": score_level,
        "主要问题标签": "; ".join(tags) if tags else "无",
        "总体结论": _overall_conclusion(score, tags),
        "切换检测窗口说明": "MR原始MESH日志为周期采样数据，切换事件的实际发生时间只能定位在相邻采样之间，无法精确到真实切换耗时。",
    }
    if rules is not None:
        overview.update(template_overview_fields(threshold_template_key, rules))
    return overview


def _finish_segment(segment: dict[str, object], samples: list[dict[str, object]], row_index: dict[tuple[object, str], tuple[list[datetime], list[dict[str, object]]]], rules: MeshQualityRules) -> None:
    peer = str(segment.get("active_peer_key") or "")
    radio = segment.get("radio")
    row_matches = _peer_rows_between(row_index, radio, peer, segment.get("start_time"), segment.get("end_time"))
    mr = [_num(row.get("active_mr_rssi")) for row in samples]
    mr_stats = calc_numeric_stats(mr)
    peer_rssi = [_num(row.get("active_peer_rssi")) for row in samples]
    tx = [_num(row.get("active_tx_busy")) for row in samples]
    rx = [_num(row.get("active_rx_busy")) for row in samples]
    segment["peer_ap_name"] = row_matches[0].get("peer_ap_name") if row_matches else ""
    segment["peer_ap_mac"] = format_mac_h3c(str(row_matches[0].get("peer_ap_mac") or "")) if row_matches and row_matches[0].get("peer_ap_mac") else ""
    segment["peer_site"] = row_matches[0].get("peer_site") if row_matches else ""
    segment["peer_radio"] = row_matches[0].get("peer_radio") or row_matches[0].get("peer_radio_label") if row_matches else ""
    segment["peer_radio_mac"] = row_matches[0].get("peer_radio_mac") if row_matches else ""
    segment["physical_ap_key"] = _physical_ap_key(row_matches[0]) if row_matches else f"peer_mac:{peer}"
    base_duration = _seconds_between(segment.get("start_time"), segment.get("end_time")) or 0
    segment["duration_seconds"] = round(base_duration + max(float(segment.get("sample_interval_seconds") or 0), 0.0), 3)
    segment["sample_count"] = len(samples)
    segment["first_mr_rssi"] = mr[0] if mr else ""
    segment["last_mr_rssi"] = mr[-1] if mr else ""
    segment["avg_mr_rssi"] = mr_stats["avg"]
    segment["min_mr_rssi"] = mr_stats["min"]
    segment["p10_mr_rssi"] = mr_stats["p10"]
    segment["max_mr_rssi"] = mr_stats["max"]
    segment["rssi_jitter"] = _jitter(mr)
    segment["avg_peer_rssi"] = _avg(peer_rssi)
    segment["min_peer_rssi"] = _min(peer_rssi)
    segment["avg_tx_busy"] = _avg(tx)
    segment["max_tx_busy"] = _max(tx)
    segment["avg_rx_busy"] = _avg(rx)
    segment["max_rx_busy"] = _max(rx)
    segment["available_backup_ratio"] = round(len([s for s in samples if int(s.get("available_backup_count") or 0) > 0]) / max(len(samples), 1), 4)
    segment["strong_backup_ratio"] = round(len([s for s in samples if int(s.get("strong_backup_count") or 0) > 0]) / max(len(samples), 1), 4)
    segment["no_backup_seconds"] = len([s for s in samples if int(s.get("available_backup_count") or 0) == 0])
    segment["weak_rssi_seconds"] = len([s for s in samples if _num(s.get("active_mr_rssi")) is not None and _num(s.get("active_mr_rssi")) < rules.rssi_good_threshold])
    segment["busy_seconds"] = len([s for s in samples if max(_num(s.get("active_tx_busy")) or 0, _num(s.get("active_rx_busy")) or 0) >= rules.busy_warning_threshold])
    segment["link_count_delta_count"] = _increase_count([_num(row.get("link_count")) for row in row_matches])
    segment["duration_reset_count"] = _decrease_count([_num(row.get("duration_seconds")) for row in row_matches])
    segment["establish_reset_count"] = _change_count([row.get("establish_time") for row in row_matches if row.get("establish_time")])
    tags = []
    if segment["weak_rssi_seconds"]:
        tags.append("弱覆盖")
    if segment["no_backup_seconds"]:
        tags.append("无备份链路")
    if segment["busy_seconds"]:
        tags.append("空口繁忙")
    if segment["link_count_delta_count"] or segment["duration_reset_count"] or segment["establish_reset_count"]:
        tags.append("链路重建异常")
    segment["segment_quality_score"] = max(0, 100 - len(tags) * 20)
    segment["segment_level"] = _score_level(int(segment["segment_quality_score"]))
    segment["segment_problem_tags"] = "; ".join(tags)
    segment["source_files"] = ", ".join(sorted({str(row.get("archived_filename") or row.get("source_file") or "") for row in row_matches if row.get("archived_filename") or row.get("source_file")}))


def _group_by_radio_time(rows: list[dict[str, object]]) -> list[tuple[tuple[object, str], list[dict[str, object]]]]:
    grouped: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((row.get("radio"), str(row.get("sample_time") or "")), []).append(row)
    return sorted(grouped.items(), key=lambda item: (item[0][1], str(item[0][0])))


def _group_by_peer(rows: list[dict[str, object]]) -> dict[tuple[object, str], list[dict[str, object]]]:
    grouped: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        peer = str(row.get("peer_mac") or "")
        if peer:
            grouped.setdefault((row.get("radio"), peer), []).append(row)
    return {key: sorted(value, key=lambda row: str(row.get("sample_time") or "")) for key, value in grouped.items()}


def _merge_samples(samples: list[dict[str, object]], predicate, rules: MeshQualityRules) -> list[list[dict[str, object]]]:
    result: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for sample in samples:
        if predicate(sample):
            if current and (current[-1].get("radio") != sample.get("radio") or (_seconds_between(current[-1].get("sample_time"), sample.get("sample_time")) or 0) > 2):
                result.append(current)
                current = []
            current.append(sample)
        elif current:
            result.append(current)
            current = []
    if current:
        result.append(current)
    return result


def _samples_between(samples: list[dict[str, object]], radio: object, anchor: object, seconds: int, *, before: bool) -> list[dict[str, object]]:
    result = []
    for sample in samples:
        if sample.get("radio") != radio:
            continue
        delta = _seconds_between(sample.get("sample_time"), anchor)
        if delta is None:
            continue
        if before and 0 <= delta <= seconds:
            result.append(sample)
        if not before and -seconds <= delta <= 0:
            result.append(sample)
    return result


def _build_radio_time_index(samples: list[dict[str, object]]) -> dict[object, tuple[list[datetime], list[dict[str, object]]]]:
    grouped: dict[object, list[dict[str, object]]] = {}
    for sample in samples:
        grouped.setdefault(sample.get("radio"), []).append(sample)
    result: dict[object, tuple[list[datetime], list[dict[str, object]]]] = {}
    for radio, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: _dt(row.get("sample_time")))
        result[radio] = ([_dt(row.get("sample_time")) for row in ordered], ordered)
    return result


def _build_source_radio_time_index(samples: list[dict[str, object]]) -> dict[tuple[object, object], tuple[list[datetime], list[dict[str, object]]]]:
    grouped: dict[tuple[object, object], list[dict[str, object]]] = {}
    for sample in samples:
        grouped.setdefault((sample.get("source_file_id"), sample.get("radio")), []).append(sample)
    result: dict[tuple[object, object], tuple[list[datetime], list[dict[str, object]]]] = {}
    for scope, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: _dt(row.get("sample_time")))
        result[scope] = ([_dt(row.get("sample_time")) for row in ordered], ordered)
    return result


def _sample_interval_by_scope(samples: list[dict[str, object]]) -> dict[tuple[object, object], float]:
    grouped: dict[tuple[object, object], list[datetime]] = {}
    for sample in samples:
        parsed = _dt_or_none(sample.get("sample_time"))
        if parsed is not None:
            grouped.setdefault((sample.get("source_file_id"), sample.get("radio")), []).append(parsed)
    result: dict[tuple[object, object], float] = {}
    for scope, times in grouped.items():
        ordered = sorted(set(times))
        deltas = [(current - previous).total_seconds() for previous, current in zip(ordered, ordered[1:])]
        positive = [delta for delta in deltas if delta > 0]
        result[scope] = float(median(positive)) if positive else 1.0
    return result


def _build_peer_time_index(rows: list[dict[str, object]]) -> dict[tuple[object, str], tuple[list[datetime], list[dict[str, object]]]]:
    grouped: dict[tuple[object, str], list[dict[str, object]]] = {}
    for row in rows:
        peer = _peer(row)
        if peer:
            grouped.setdefault((row.get("radio"), peer), []).append(row)
    result: dict[tuple[object, str], tuple[list[datetime], list[dict[str, object]]]] = {}
    for key, peer_rows in grouped.items():
        ordered = sorted(peer_rows, key=lambda row: _dt(row.get("sample_time")))
        result[key] = ([_dt(row.get("sample_time")) for row in ordered], ordered)
    return result


def _samples_between_indexed(
    sample_index: dict[object, tuple[list[datetime], list[dict[str, object]]]],
    samples: list[dict[str, object]],
    radio: object,
    anchor: object,
    seconds: int,
    *,
    before: bool,
) -> list[dict[str, object]]:
    anchor_dt = _dt_or_none(anchor)
    indexed = sample_index.get(radio)
    if anchor_dt is None or indexed is None:
        return _samples_between(samples, radio, anchor, seconds, before=before)
    times, rows = indexed
    if before:
        start, end = anchor_dt - timedelta(seconds=seconds), anchor_dt
    else:
        start, end = anchor_dt, anchor_dt + timedelta(seconds=seconds)
    left = bisect_left(times, start)
    right = bisect_right(times, end)
    return rows[left:right]


def _rows_around(
    time_index: dict[object, tuple[list[datetime], list[dict[str, object]]]],
    radio: object,
    anchor: object,
    seconds: int,
) -> list[dict[str, object]]:
    anchor_dt = _dt_or_none(anchor)
    if anchor_dt is None:
        return []
    return _rows_between_dt(time_index, radio, anchor_dt - timedelta(seconds=seconds), anchor_dt + timedelta(seconds=seconds))


def _rows_between_time(
    time_index: dict[object, tuple[list[datetime], list[dict[str, object]]]],
    radio: object,
    start_time: object,
    end_time: object,
) -> list[dict[str, object]]:
    start = _dt_or_none(start_time)
    end = _dt_or_none(end_time)
    if start is None or end is None:
        return []
    return _rows_between_dt(time_index, radio, start, end)


def _rows_between_dt(
    time_index: dict[object, tuple[list[datetime], list[dict[str, object]]]],
    radio: object,
    start: datetime,
    end: datetime,
) -> list[dict[str, object]]:
    indexed = time_index.get(radio)
    if indexed is None:
        return []
    times, rows = indexed
    left = bisect_left(times, start)
    right = bisect_right(times, end)
    return rows[left:right]


def _peer_rows_between(
    row_index: dict[tuple[object, str], tuple[list[datetime], list[dict[str, object]]]],
    radio: object,
    peer: str,
    start_time: object,
    end_time: object,
) -> list[dict[str, object]]:
    indexed = row_index.get((radio, peer))
    start = _dt_or_none(start_time)
    end = _dt_or_none(end_time)
    if indexed is None or start is None or end is None:
        return []
    times, rows = indexed
    left = bisect_left(times, start)
    right = bisect_right(times, end)
    return rows[left:right]


def _dt(value: object) -> datetime:
    parsed = _dt_or_none(value)
    return parsed or datetime.min


def _dt_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration(samples: list[dict[str, object]]) -> float:
    if not samples:
        return 0.0
    return _seconds_between(samples[0].get("sample_time"), samples[-1].get("sample_time")) or 0.0


def _classify_pingpong_switch(segments: list[dict[str, object]], index: int, rules: MeshQualityRules) -> dict[str, object]:
    if index + 2 >= len(segments):
        return {}
    previous, middle, returned = segments[index], segments[index + 1], segments[index + 2]
    return_duration_seconds = _seconds_between(previous.get("end_time"), returned.get("start_time"))
    if return_duration_seconds is None or return_duration_seconds < 0:
        return {}
    return_duration_ms = int(round(return_duration_seconds * 1000))
    if return_duration_ms > _pingpong_return_window_ms(rules):
        return {}
    previous_key = _segment_physical_ap_key(previous)
    middle_key = _segment_physical_ap_key(middle)
    returned_key = _segment_physical_ap_key(returned)
    if not previous_key or not middle_key or not returned_key:
        return {}
    middle_dwell_ms = max(int(round(_segment_duration_seconds(middle) * 1000)), 0)
    group_id = f"PP{index + 1:04d}"
    if previous_key == middle_key == returned_key and previous.get("active_peer_key") != middle.get("active_peer_key"):
        return {
            "is_ap_return_event": False,
            "is_pingpong_abnormal": False,
            "pingpong_type": "同AP射频往返",
            "pingpong_group_id": group_id,
            "pingpong_return_duration_ms": return_duration_ms,
            "middle_ap_dwell_ms": middle_dwell_ms,
            "previous_ap": _segment_ap_label(previous),
            "middle_ap": _segment_ap_label(middle),
            "return_ap": _segment_ap_label(returned),
            "judgment_reason": f"同一物理 AP 内 {previous.get('peer_radio') or '-'} -> {middle.get('peer_radio') or '-'} -> {returned.get('peer_radio') or '-'}，不计入 AP 乒乓。",
        }
    if previous_key != returned_key or previous_key == middle_key:
        return {}
    pingpong_type, is_abnormal, reason = _classify_pingpong_return(
        previous,
        middle,
        returned,
        middle_dwell_ms,
        rules,
    )
    return {
        "is_ap_return_event": True,
        "is_pingpong_abnormal": is_abnormal,
        "pingpong_type": pingpong_type,
        "pingpong_group_id": group_id,
        "pingpong_return_duration_ms": return_duration_ms,
        "middle_ap_dwell_ms": middle_dwell_ms,
        "previous_ap": _segment_ap_label(previous),
        "middle_ap": _segment_ap_label(middle),
        "return_ap": _segment_ap_label(returned),
        "judgment_reason": reason,
    }


def _classify_pingpong_return(
    previous: dict[str, object],
    middle: dict[str, object],
    returned: dict[str, object],
    middle_dwell_ms: int,
    rules: MeshQualityRules,
) -> tuple[str, bool, str]:
    switch_ms = max(int(rules.main_link_switch_time_ms or 2500), 1)
    tolerance_ms = max(int(rules.pingpong_tolerance_ms or 0), 0)
    abnormal_threshold = max(switch_ms - tolerance_ms, 0)
    critical_upper = switch_ms + tolerance_ms
    sequence = f"{_segment_ap_label(previous)} -> {_segment_ap_label(middle)} -> {_segment_ap_label(returned)}"
    dwell_text = f"{middle_dwell_ms / 1000.0:.2f}s"
    if middle_dwell_ms < abnormal_threshold:
        return "AP乒乓切换异常", True, f"{sequence}，中间 AP 驻留 {dwell_text}，明显小于配置切换时间 {switch_ms}ms。"
    if middle_dwell_ms <= critical_upper:
        return "临界回切", False, f"{sequence}，中间 AP 驻留 {dwell_text}，接近配置切换时间 {switch_ms}ms，不计入乒乓异常。"
    return "普通回切事件", False, f"{sequence}，中间 AP 驻留 {dwell_text}，已超过配置切换时间 {switch_ms}ms，不计入乒乓异常。"


def _pingpong_return_window_ms(rules: MeshQualityRules) -> int:
    if rules.pingpong_return_window_ms:
        return max(int(rules.pingpong_return_window_ms), 1)
    return max(8000, 3 * (int(rules.main_link_switch_time_ms or 2500) + int(rules.pingpong_tolerance_ms or 500)))


def _segment_ap_label(segment: dict[str, object]) -> str:
    label = str(segment.get("peer_ap_name") or "").strip() or format_mac_h3c(segment.get("active_peer_key")) or "-"
    station = str(segment.get("peer_site") or "").strip()
    return f"{label} / {station}" if station else label


def _segment_physical_ap_key(segment: dict[str, object]) -> str:
    return str(segment.get("physical_ap_key") or "") or _physical_ap_key(segment)


def _segment_duration_seconds(segment: dict[str, object]) -> float:
    value = _num(segment.get("duration_seconds"))
    if value is not None:
        return max(value, 0.0)
    return max(_seconds_between(segment.get("start_time"), segment.get("end_time")) or 0.0, 0.0)


def _physical_ap_key(row: dict[str, object]) -> str:
    ap_mac = _canonical(row.get("peer_ap_mac"))
    if ap_mac:
        return f"ap_mac:{ap_mac}"
    ap_name = str(row.get("peer_ap_name") or "").strip().lower()
    if ap_name:
        return f"ap_name:{ap_name}"
    peer_radio_mac = _canonical(row.get("peer_radio_mac"))
    if peer_radio_mac:
        return f"peer_radio_mac:{peer_radio_mac}"
    peer = _peer(row) or _canonical(row.get("active_peer_key") or row.get("active_peer_mac"))
    return f"peer_mac:{peer}" if peer else ""


def _is_pingpong_abnormal_event(event: dict[str, object]) -> bool:
    return bool(event.get("is_pingpong_abnormal")) or str(event.get("switch_type") or "") == "FLAP_SWITCH"


def _all_low(samples: list[dict[str, object]], threshold: float) -> bool:
    values = [_num(row.get("active_mr_rssi")) for row in samples]
    finite = [value for value in values if value is not None]
    return bool(finite) and all(value < threshold for value in finite)


def _has_better_backup(samples: list[dict[str, object]]) -> bool:
    for sample in samples:
        active = _num(sample.get("active_mr_rssi"))
        backup = _num(sample.get("best_backup_rssi"))
        if active is not None and backup is not None and backup > active:
            return True
    return False


def _problem_tags(samples, switches, anomalies, rebuilds, parse_issues) -> list[str]:
    tags = []
    mapping = {
        "NO_BACKUP": "无备份链路",
        "HIGH_BUSY": "空口繁忙",
        "BUSY_WARNING": "空口繁忙",
        "NO_ACTIVE": "无 Active",
        "MULTI_ACTIVE": "多 Active",
        "WEAK_ACTIVE": "弱覆盖",
        "BAD_ACTIVE": "弱覆盖",
    }
    for event in anomalies:
        tag = mapping.get(str(event.get("event_type")))
        if tag and tag not in tags:
            tags.append(tag)
    for switch in switches:
        tag = {"LATE_SWITCH": "切换滞后", "WEAK_TARGET_SWITCH": "切入质量差", "FLAP_SWITCH": "乒乓切换", "SHORT_SEGMENT_SWITCH": "短时建链"}.get(str(switch.get("switch_type")))
        if _is_pingpong_abnormal_event(switch):
            tag = "乒乓切换"
        if tag and tag not in tags:
            tags.append(tag)
    if rebuilds:
        tags.append("链路重建异常")
    if parse_issues:
        tags.append("解析异常")
    return tags


def _peer(row: dict[str, object]) -> str:
    return _canonical(row.get("peer_mac_normalized") or row.get("peer_mac") or row.get("peer_mac_raw"))


def _canonical(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch in "0123456789abcdef")


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


def _num(*values: object) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _avg(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return round(mean(finite), 3) if finite else ""


def _min(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return min(finite) if finite else ""


def _max(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return max(finite) if finite else ""


def _jitter(values: list[float | None]) -> float | str:
    finite = [value for value in values if value is not None]
    return round(max(finite) - min(finite), 3) if finite else ""


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _seconds_between(start: object, end: object) -> float | None:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds()


def _increase_count(values: list[float | None]) -> int:
    finite = [value for value in values if value is not None]
    return sum(1 for previous, current in zip(finite, finite[1:]) if current > previous)


def _decrease_count(values: list[float | None]) -> int:
    finite = [value for value in values if value is not None]
    return sum(1 for previous, current in zip(finite, finite[1:]) if current < previous)


def _change_count(values: list[object]) -> int:
    clean = [value for value in values if value not in (None, "")]
    return sum(1 for previous, current in zip(clean, clean[1:]) if current != previous)


def _score_from_level(level: str) -> int:
    return {"EXCELLENT": 100, "GOOD": 85, "WARNING": 70, "BAD": 50, "CRITICAL": 20}.get(level, 60)


def _score_level(score: int) -> str:
    if score >= 90:
        return "优秀"
    if score >= 75:
        return "良好"
    if score >= 60:
        return "关注"
    if score >= 40:
        return "异常"
    return "严重"


def _worse(current: str, candidate: str) -> str:
    order = {"EXCELLENT": 0, "GOOD": 1, "WARNING": 2, "BAD": 3, "CRITICAL": 4}
    return candidate if order.get(candidate, 0) > order.get(current, 0) else current


def _switch_suggestion(switch_type: str) -> str:
    return {
        "LATE_SWITCH": "建议复核切换前窗口内的备份链路、轨旁 AP 覆盖和车载 MR 射频状态。",
        "WEAK_TARGET_SWITCH": "建议检查切入目标 AP 覆盖、天线方向、安装位置或车载 MR 射频状态。",
        "FLAP_SWITCH": "建议复核切换边界和相邻 Peer 覆盖重叠区域。",
        "SHORT_SEGMENT_SWITCH": "建议关注短时建链对应 Peer 的链路稳定性。",
    }.get(switch_type, "")


def _anomaly_suggestion(event_type: str) -> str:
    return {
        "NO_ACTIVE": "建议重点检查对应时段 MR Mesh 主链路和轨旁 AP 覆盖连续性。",
        "MULTI_ACTIVE": "建议检查解析结果和设备侧 Active 状态是否异常。",
        "WEAK_ACTIVE": "建议检查对应轨旁 AP 覆盖、天线方向、安装位置或车载 MR 射频状态。",
        "BAD_ACTIVE": "建议优先复核严重弱信号时间段的原始日志和 AP 覆盖。",
        "NO_BACKUP": "建议检查备份链路覆盖余量，降低后续切换风险。",
        "HIGH_BUSY": "建议排查空口干扰、同频竞争或业务负载。",
        "BUSY_WARNING": "建议复核对应时间段空口繁忙来源。",
    }.get(event_type, "")


def _peer_suggestion(tags: list[str]) -> str:
    if "弱覆盖" in tags:
        return "该 Peer 主链路 RSSI 偏低，建议检查对应轨旁 AP 覆盖、天线方向、安装位置或车载 MR 射频状态。"
    if "无备份链路" in tags:
        return "该 Peer Active 时无可用备份比例较高，后续切换风险较大。"
    if "链路重建异常" in tags:
        return "该 Peer 出现 LinkCnt 增量或 DurationTime 回退，疑似 Mesh 链路发生重建。"
    return ""


def _overall_conclusion(score: int, tags: list[str]) -> str:
    if score >= 90 and not tags:
        return "主链路 RSSI、备份链路、切换质量和空口繁忙度整体正常。"
    if score >= 60:
        return "存在短时无备份、局部 RSSI 偏低或空口繁忙，建议复核对应时间段和 Peer 链路。"
    if score >= 40:
        return "存在连续弱信号、无 Active、切换滞后、切入质量差或链路重建异常，建议重点检查对应 Peer、轨旁 AP 覆盖、天线方向、车载 MR 射频状态和空口干扰。"
    return "存在长时间无 Active、RSSI 严重低于阈值、多 Active 异常或频繁链路重建，可能影响业务连续性。"


def _cancel(should_cancel: Callable[[], bool]) -> None:
    if should_cancel():
        raise RuntimeError("cancelled")
