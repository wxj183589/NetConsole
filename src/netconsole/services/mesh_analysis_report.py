from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Callable, Mapping

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, LINK_STATE_STANDBY, PAIRED_METRICS, format_mac_h3c, normalize_link_state
from netconsole.models.mesh_analysis_params import DEFAULT_MESH_ANALYSIS_PARAMS, MeshAnalysisParams, normalize_mesh_analysis_params
from netconsole.repositories.mesh_mr_repository import DERIVED_ANALYSIS_VERSION, MIN_NORMAL_ACTIVE_SAMPLE_COUNT, PARSER_VERSION, MeshMrRepository
from netconsole.services.mesh_chart_payload import build_chart_payload
from netconsole.services.mesh_rssi_stats import calc_numeric_stats
from netconsole.services.mesh_quality_analysis import (
    MR_RAW_MESH_LOG,
    MeshQualityRules,
    build_quality_report,
    get_threshold_template,
    load_default_rules,
)
from netconsole.services.rail_transit.mesh_ap_location_service import MeshApLocationSnapshot


ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]
_REPORT_METRIC_COLUMNS = tuple(dict.fromkeys(column for _name, left, right in PAIRED_METRICS for column in (left, right)))
MESH_REPORT_RULE_VERSION = "qt_business_v1"
_CURRENT_VALUE_UNSET = object()


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
    main_link_switch_time_ms: int = 4000
    short_link_tolerance_ms: int = 500
    pingpong_tolerance_ms: int = 500
    pingpong_return_window_ms: int | None = 500
    merge_same_physical_ap_dual_radio: bool = True
    include_log_boundary_segments: bool = False
    sample_interval_ms: int | None = None
    short_active_segment_seconds: float = 3.5
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
    analysis_params_override: dict[str, object] | None = None
    site_analysis_params: dict[str, object] | None = None
    ap_location_snapshot: tuple[dict[str, str], ...] = ()


@dataclass
class MeshAnalysisReportModel:
    mr_name: str
    report_name: str
    generated_at: datetime
    options: MeshReportOptions
    overview: dict[str, object] = field(default_factory=dict)
    analysis_parameters: list[dict[str, object]] = field(default_factory=list)
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
    switch_events: list[dict[str, object]] = field(default_factory=list)
    anomaly_events: list[dict[str, object]] = field(default_factory=list)
    no_backup_risks: list[dict[str, object]] = field(default_factory=list)
    busy_analysis: list[dict[str, object]] = field(default_factory=list)
    link_rebuild_events: list[dict[str, object]] = field(default_factory=list)
    raw_evidence: list[dict[str, object]] = field(default_factory=list)
    active_build_order: list[dict[str, object]] = field(default_factory=list)
    link_details: list[dict[str, object]] = field(default_factory=list)
    active_path_rssi: list[dict[str, object]] = field(default_factory=list)
    peer_visit_statistics: list[dict[str, object]] = field(default_factory=list)
    active_path_busy: list[dict[str, object]] = field(default_factory=list)


class MeshReportCancelled(RuntimeError):
    """Raised when report generation is cancelled before export completes."""


class MeshAnalysisReportService:
    def __init__(self, db_path: Path, mr_name: str = "") -> None:
        self.db_path = Path(db_path)
        self._active_db_path = self.db_path
        self.mr_name = mr_name or self.db_path.parent.name

    def build_report(
        self,
        options: MeshReportOptions | None = None,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> MeshAnalysisReportModel:
        options = options or MeshReportOptions()
        options = self._resolve_report_options(options)
        progress = progress or (lambda _value, _message: None)
        should_cancel = should_cancel or (lambda: False)
        self._raise_if_cancelled(should_cancel)
        progress(5, "loading")
        repository = MeshMrRepository(self._active_db_path, read_only=True)
        location_snapshot = MeshApLocationSnapshot.from_serializable(options.ap_location_snapshot)
        links = [_with_ap_location(row, location_snapshot) for row in self._load_links(options, repository)]
        events = self._load_events(options) if options.include_raw_events else []
        parse_issues = self._load_parse_issues(options) if options.include_parse_issues else []
        source_files = self._load_source_files(options)
        self._raise_if_cancelled(should_cancel)

        rules = self._rules_from_options(options)
        analysis_parameters = build_analysis_parameter_rows(options, source_files, rules, links)
        quality_report = build_quality_report(
            links,
            source_files,
            parse_issues,
            self.mr_name,
            options.report_name or self.mr_name,
            options.data_source_type,
            rules,
            include_raw_evidence=options.include_raw_evidence,
            include_all_link_details=False,
            include_parse_issues=options.include_parse_issues,
            include_busy_analysis=options.include_busy_analysis,
            threshold_template_key=options.threshold_template_key,
            excluded_region_keywords=options.excluded_region_keywords,
            progress=progress,
            should_cancel=should_cancel,
        )
        self._raise_if_cancelled(should_cancel)

        progress(25, "active_segments")
        active_build_order = repository.query_active_link_build_order(
            options.source_file_id,
            options.radio_filter,
            options.analysis_params_override,
            options.site_analysis_params,
        )
        active_build_order = [_with_ap_location(row, location_snapshot) for row in active_build_order]
        active_build_order = _filter_active_build_order(active_build_order, options.start_time, options.end_time)
        active_segments = _active_build_order_segments(active_build_order)
        switch_sequence = build_switch_sequence(active_segments)
        chart_segments = repository.query_active_link_chart_segments(
            options.source_file_id,
            options.radio_filter,
            options.start_time or "",
            options.end_time or "",
        )
        chart_payload = build_chart_payload(
            dict(chart_segments.get("peer_segment") or {}),
            dict(chart_segments.get("run_segment") or {}),
        )
        active_path_rssi, active_path_busy = _active_path_report_rows(
            chart_payload,
            source_files,
        )
        active_path_rssi = [_with_ap_location(row, location_snapshot) for row in active_path_rssi]
        active_path_busy = [_with_ap_location(row, location_snapshot) for row in active_path_busy]
        peer_visit_statistics = _peer_visit_statistics(active_build_order)
        self._raise_if_cancelled(should_cancel)

        progress(45, "flap")
        flap_events = (
            detect_flap_switches(
                active_segments,
                options.flap_window_seconds,
                main_link_switch_time_ms=options.main_link_switch_time_ms,
                pingpong_tolerance_ms=options.pingpong_tolerance_ms,
                pingpong_return_window_ms=options.pingpong_return_window_ms,
            )
            if options.include_flap_analysis
            else []
        )
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
            analysis_parameters=analysis_parameters,
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
            active_segments=active_segments,
            switch_events=quality_report.switch_events,
            anomaly_events=quality_report.anomaly_events,
            no_backup_risks=quality_report.no_backup_risks,
            busy_analysis=quality_report.busy_analysis,
            link_rebuild_events=quality_report.link_rebuild_events,
            raw_evidence=quality_report.raw_evidence,
            active_build_order=active_build_order,
            link_details=links,
            active_path_rssi=active_path_rssi,
            peer_visit_statistics=peer_visit_statistics,
            active_path_busy=active_path_busy,
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
            main_link_switch_time_ms=options.main_link_switch_time_ms or defaults.main_link_switch_time_ms,
            pingpong_tolerance_ms=options.pingpong_tolerance_ms or defaults.pingpong_tolerance_ms,
            pingpong_return_window_ms=options.pingpong_return_window_ms or defaults.pingpong_return_window_ms,
            short_active_segment_seconds=options.short_active_segment_seconds or defaults.short_active_segment_seconds,
            score_weights=weights,
        )

    def _load_links(self, options: MeshReportOptions, repository: MeshMrRepository) -> list[dict[str, object]]:
        filters: dict[str, object] = {}
        if options.radio_filter is not None:
            filters["radio"] = options.radio_filter
        if options.source_file_id is not None:
            filters["source_file_id"] = options.source_file_id
        rows: list[dict[str, object]] = []
        for row in repository.iter_link_details(filters, batch_size=2000):
            sample_time = str(row.get("sample_time") or "")
            if options.start_time and sample_time < options.start_time:
                continue
            if options.end_time and sample_time > options.end_time:
                continue
            rows.append(_normalize_link_row(_report_row_payload(dict(row))))
        return rows

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
            rows = conn.execute(f"SELECT * FROM switch_events {where} ORDER BY event_time ASC, id ASC", values).fetchall()
        return [dict(row) for row in rows]

    def _load_parse_issues(self, options: MeshReportOptions) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if options.source_file_id is not None:
            clauses.append("source_file_id = ?")
            values.append(options.source_file_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *,
                       ('raw定位:' || COALESCE(source_file, '') || ':' || COALESCE(raw_line_start, line_number)) AS raw_line
                FROM parse_issues
                {where}
                ORDER BY source_file ASC, line_number ASC, id ASC
                """,
                values,
            ).fetchall()
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
        conn = sqlite3.connect(self._active_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_report_options(self, options: MeshReportOptions) -> MeshReportOptions:
        self._active_db_path = self.db_path
        if self.db_path.name != "mesh.sqlite" or not self.db_path.exists():
            return options
        try:
            repo = MeshMrRepository(self.db_path, read_only=True)
            sources = repo.list_source_files()
        except Exception:
            return options
        selected = None
        if options.source_file_id is not None:
            selected = next((row for row in sources if int(row.get("id") or 0) == int(options.source_file_id)), None)
        elif len(sources) == 1:
            selected = sources[0]
        if selected is None:
            return options
        options = with_report_analysis_params(
            options,
            resolve_report_analysis_params(options, selected.get("analysis_params_json")),
        )
        parsed_db_path = Path(str(selected.get("parsed_db_path") or ""))
        if parsed_db_path.exists():
            self._active_db_path = parsed_db_path
            return replace(options, source_file_id=None)
        return options

    @staticmethod
    def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
        if should_cancel():
            raise MeshReportCancelled()


def resolve_report_analysis_params(
    options: MeshReportOptions,
    source_snapshot: object | None,
) -> MeshAnalysisParams:
    merged = DEFAULT_MESH_ANALYSIS_PARAMS.to_dict()
    for candidate in (
        _mapping(options.site_analysis_params),
        _mapping(source_snapshot),
        _mapping(options.analysis_params_override),
    ):
        merged.update(candidate)
    return normalize_mesh_analysis_params(merged)


def with_report_analysis_params(options: MeshReportOptions, params: MeshAnalysisParams) -> MeshReportOptions:
    return replace(
        options,
        short_active_segment_seconds=params.short_link_threshold_ms / 1000.0,
        main_link_switch_time_ms=params.main_link_switch_time_ms,
        short_link_tolerance_ms=params.short_link_tolerance_ms,
        pingpong_tolerance_ms=params.pingpong_tolerance_ms,
        pingpong_return_window_ms=params.effective_pingpong_return_window_ms,
        flap_window_seconds=max(1, int(round(params.effective_pingpong_return_window_ms / 1000.0))),
        merge_same_physical_ap_dual_radio=params.merge_same_physical_ap_dual_radio,
        include_log_boundary_segments=params.include_log_boundary_segments,
        sample_interval_ms=params.sample_interval_ms,
        business_type=params.service_type,
        working_mode=params.wifi_type,
    )


def build_analysis_parameter_rows(
    options: MeshReportOptions,
    source_files: list[dict[str, object]],
    rules: MeshQualityRules,
    links: list[dict[str, object]],
) -> list[dict[str, object]]:
    override = _mapping(options.analysis_params_override)
    option_defaults = MeshReportOptions()
    for key in (
        "rssi_excellent_threshold",
        "rssi_good_threshold",
        "rssi_warning_threshold",
        "rssi_bad_threshold",
        "backup_available_threshold",
        "backup_strong_threshold",
        "busy_warning_threshold",
        "busy_bad_threshold",
        "no_backup_min_seconds",
        "weak_active_min_seconds",
        "bandwidth",
        "ap_spacing",
        "threshold_template_key",
    ):
        value = getattr(options, key)
        if value != getattr(option_defaults, key):
            override.setdefault(key, value)
    source = _mapping(source_files[0].get("analysis_params_json")) if source_files else {}
    site = _mapping(options.site_analysis_params)
    defaults = DEFAULT_MESH_ANALYSIS_PARAMS.to_dict()
    params = resolve_report_analysis_params(options, source)
    template = get_threshold_template(options.threshold_template_key)
    estimated_interval_ms = _report_sample_interval_ms(links, params.sample_interval_ms)
    continuous_gap_ms = (
        int(round(min(max((estimated_interval_ms or 1000) * 5, 5000), 60000)))
        if estimated_interval_ms is not None
        else None
    )

    rows: list[dict[str, object]] = []

    def add(
        category: str,
        name: str,
        key: str,
        unit: str,
        effective: object,
        meaning: str,
        *,
        default_value: object = None,
        current_value: object = _CURRENT_VALUE_UNSET,
        source_key: str | None = None,
        remark: str = "",
    ) -> None:
        candidate_key = source_key or key
        candidate_default = defaults.get(candidate_key) if default_value is None and candidate_key in defaults else default_value
        chosen, origin = _parameter_choice(candidate_key, override, source, site, candidate_default)
        rows.append(
            {
                "category": category,
                "parameter_name": name,
                "current_value": chosen if current_value is _CURRENT_VALUE_UNSET else current_value,
                "unit": unit,
                "effective_value": effective,
                "meaning": meaning,
                "parameter_source": origin,
                "report_override": override.get(candidate_key) if candidate_key in override else None,
                "source_snapshot": source.get(candidate_key) if candidate_key in source else None,
                "site_config": site.get(candidate_key) if candidate_key in site else None,
                "global_default": candidate_default,
                "remark": remark,
            }
        )

    add("统一链路模型", "基准时间", "link_time_window", "ms", params.link_time_window, "判断一次链路事件持续范围")
    add("统一链路模型", "切换阈值", "link_switch_threshold", "RSSI", params.link_switch_threshold, "主链路候选切换的信号差阈值")
    add("统一链路模型", "维持链路阈值", "link_hold_rssi", "RSSI", params.link_hold_rssi, "维持当前链路的信号基线")
    add("统一链路模型", "发现链路阈值", "link_establish_threshold", "RSSI", params.link_establish_threshold, "发现新链路所需的附加信号")
    add(
        "统一链路模型",
        "建链信号阈值",
        "link_establish_rssi",
        "RSSI",
        params.link_establish_rssi,
        "除第一个主链路外，实际信号需达到维持阈值与发现阈值之和",
        current_value=None,
        remark="link_hold_rssi + link_establish_threshold",
    )
    add("主链路与切换", "主链路切换基准时间", "main_link_switch_time_ms", "ms", params.main_link_switch_time_ms, "主链路正常切换的基准时间")
    add("主链路与切换", "短时判定容差", "short_link_tolerance_ms", "ms", params.short_link_tolerance_ms, "从切换基准中扣除的短时容差")
    add(
        "主链路与切换",
        "实际短时建链阈值",
        "main_link_switch_time_ms",
        "ms",
        params.short_link_threshold_ms,
        "持续时间低于此值判定为短时建链",
        current_value=None,
        remark="max(主链路切换基准时间 - 短时判定容差, 0)",
    )
    rows[-1]["parameter_source"] = _higher_priority_source(
        rows[-1]["parameter_source"],
        _parameter_choice("short_link_tolerance_ms", override, source, site, defaults["short_link_tolerance_ms"])[1],
    )
    add("主链路与切换", "乒乓判定容差", "pingpong_tolerance_ms", "ms", params.pingpong_tolerance_ms, "区分异常、临界和普通回切")
    add(
        "主链路与切换",
        "乒乓返回窗口",
        "pingpong_return_window_ms",
        "ms",
        params.effective_pingpong_return_window_ms,
        "A-B-A 返回事件的最大有效窗口",
        remark="未配置时按业务下限和 3 x (切换基准 + 乒乓容差)计算",
    )
    add("主链路与切换", "同物理 AP 双射频合并", "merge_same_physical_ap_dual_radio", "", params.merge_same_physical_ap_dual_radio, "同一物理 AP 的双射频切换是否合并")
    add("主链路与切换", "日志边界区段是否纳入异常", "include_log_boundary_segments", "", params.include_log_boundary_segments, "首尾边界区段是否参与异常判定")
    add(
        "主链路与切换",
        "估算/配置采样间隔",
        "sample_interval_ms",
        "ms",
        estimated_interval_ms,
        "主链路区段持续时间与连续性判断使用的采样间隔",
        remark="优先使用配置值；未配置时按当前来源有效采样时间估算",
    )
    add(
        "主链路与切换",
        "主链路连续间隙阈值",
        "sample_interval_ms",
        "ms",
        continuous_gap_ms,
        "超过该间隙时断开主链路区段",
        current_value=None,
        remark="min(max(5 x 采样间隔, 5000), 60000)",
    )
    add(
        "主链路与切换",
        "正常区段最小采样点数",
        "min_normal_sample_count",
        "个",
        MIN_NORMAL_ACTIVE_SAMPLE_COUNT,
        "持续时间正常但采样点偏少时用于诊断",
        default_value=MIN_NORMAL_ACTIVE_SAMPLE_COUNT,
    )

    threshold_rows = (
        ("RSSI 阈值", "RSSI 优", "rssi_excellent_threshold", "原始值", rules.rssi_excellent_threshold, "达到或高于该值判定为优"),
        ("RSSI 阈值", "RSSI 良", "rssi_good_threshold", "原始值", rules.rssi_good_threshold, "达到或高于该值判定为良"),
        ("RSSI 阈值", "RSSI 警告", "rssi_warning_threshold", "原始值", rules.rssi_warning_threshold, "低于良好线时进入警告区间"),
        ("RSSI 阈值", "RSSI 差", "rssi_bad_threshold", "原始值", rules.rssi_bad_threshold, "低于该值判定为差"),
        ("RSSI 阈值", "备份链路可用阈值", "backup_available_threshold", "原始值", rules.backup_available_threshold, "备份链路达到该值视为可用"),
        ("RSSI 阈值", "强备份链路阈值", "backup_strong_threshold", "原始值", rules.backup_strong_threshold, "备份链路达到该值视为强备份"),
        ("RSSI 阈值", "弱主链路持续时间", "weak_active_min_seconds", "s", rules.weak_active_min_seconds, "弱主链路持续达到该时长后记录异常"),
        ("空口负载阈值", "Busy 警告阈值", "busy_warning_threshold", "%", rules.busy_warning_threshold, "Tx/Rx Busy 达到该值进入警告"),
        ("空口负载阈值", "Busy 差阈值", "busy_bad_threshold", "%", rules.busy_bad_threshold, "Tx/Rx Busy 达到该值判定为差"),
        ("空口负载阈值", "无备份链路最短持续时间", "no_backup_min_seconds", "s", rules.no_backup_min_seconds, "无可用备份持续达到该时长后记录风险"),
    )
    for category, name, key, unit, value, meaning in threshold_rows:
        add(category, name, key, unit, value, meaning, default_value=getattr(option_defaults, key))

    add("项目和环境", "业务类型", "service_type", "", params.service_type, "当前报告使用的业务类型")
    add("项目和环境", "WiFi 类型", "wifi_type", "", params.wifi_type, "当前报告使用的无线制式")
    add("项目和环境", "频宽", "bandwidth", "", options.bandwidth, "报告评估场景的信道频宽", default_value=option_defaults.bandwidth)
    add("项目和环境", "典型 AP 间隔", "ap_spacing", "", options.ap_spacing, "报告评估场景的典型 AP 间隔", default_value=option_defaults.ap_spacing)
    add("项目和环境", "质量模板名称", "threshold_template_key", "", template.label, "质量阈值模板", default_value=option_defaults.threshold_template_key)
    add("项目和环境", "质量模板版本", "threshold_template_version", "", None, "质量模板的独立版本标识", default_value=None, remark="当前模板未提供独立版本字段")
    add("项目和环境", "Parser 版本", "parser_version", "", PARSER_VERSION, "MESH compact 数据解析版本", default_value=PARSER_VERSION)
    add("项目和环境", "Derived analysis 版本", "derived_analysis_version", "", DERIVED_ANALYSIS_VERSION, "主链路派生分析版本", default_value=DERIVED_ANALYSIS_VERSION)
    add("项目和环境", "报告规则版本", "report_rule_version", "", MESH_REPORT_RULE_VERSION, "综合分析报告结构和规则版本", default_value=MESH_REPORT_RULE_VERSION)
    return rows


_SOURCE_PRIORITY = {"global_default": 0, "site_config": 1, "source_snapshot": 2, "report_override": 3}


def _higher_priority_source(left: object, right: object) -> str:
    left_text = str(left or "global_default")
    right_text = str(right or "global_default")
    return left_text if _SOURCE_PRIORITY.get(left_text, 0) >= _SOURCE_PRIORITY.get(right_text, 0) else right_text


def _parameter_choice(
    key: str,
    override: Mapping[str, object],
    source: Mapping[str, object],
    site: Mapping[str, object],
    default: object,
) -> tuple[object, str]:
    for values, source_name in (
        (override, "report_override"),
        (source, "source_snapshot"),
        (site, "site_config"),
    ):
        if key in values:
            return values[key], source_name
    return default, "global_default"


def _mapping(value: object | None) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _report_sample_interval_ms(rows: list[dict[str, object]], configured_ms: int | None) -> int | None:
    if configured_ms is not None:
        return int(configured_ms)
    intervals = _sample_interval_by_scope(rows).values()
    values = [interval for interval in intervals if interval > 0]
    return int(round(median(values) * 1000)) if values else None


def _active_build_order_segments(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Project the shared active-build result into the report segment contract."""
    segments: list[dict[str, object]] = []
    for index, row in enumerate(rows, 1):
        segments.append(
            {
                "segment_id": index,
                "source_file_id": row.get("source_file_id"),
                "radio": row.get("radio"),
                "active_peer_mac": row.get("active_peer_mac") or "",
                "active_peer": format_mac_h3c(str(row.get("active_peer_mac") or "")),
                "peer_ap_name": row.get("peer_ap_name") or "",
                "peer_ap_mac": row.get("peer_ap_mac") or "",
                "peer_site": row.get("peer_site") or "",
                "peer_radio": row.get("peer_radio") or "",
                "peer_radio_mac": row.get("peer_radio_mac") or "",
                "physical_ap_key": row.get("physical_ap_key") or "",
                "sample_interval_seconds": row.get("main_link_duration_seconds") or 1.0,
                "start_time": row.get("build_start_time") or "",
                "end_time": row.get("build_end_time") or "",
                "sample_count": row.get("sample_count") or 0,
                "duration_seconds": row.get("main_link_duration_seconds"),
                "avg_mr_rssi": row.get("avg_mr_rssi"),
                "min_mr_rssi": row.get("min_mr_rssi"),
                "max_mr_rssi": row.get("max_mr_rssi"),
                "p10_mr_rssi": row.get("p10_mr_rssi"),
                "avg_tx_busy": row.get("avg_tx_busy"),
                "avg_rx_busy": row.get("avg_rx_busy"),
                "avg_peer_tx_busy": row.get("avg_peer_tx_busy"),
                "avg_peer_rx_busy": row.get("avg_peer_rx_busy"),
                "build_result": row.get("build_result") or "",
                "judge_reason": row.get("judge_reason") or "",
                "link_establishment_accepted": row.get("link_establishment_accepted"),
                "link_establishment_reason": row.get("link_establishment_reason") or "",
            }
        )
    return segments


def build_active_segments(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = _group_by_source_radio_time(rows)
    interval_by_radio = _sample_interval_by_scope(rows)
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_rows: list[dict[str, object]] = []
    for (source_file_id, radio, sample_time), sample_rows in grouped:
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
        if current is not None and current.get("source_file_id") == source_file_id and current.get("radio") == radio and current.get("active_peer_mac") == peer:
            current["end_time"] = sample_time
            current["sample_count"] = int(current.get("sample_count") or 0) + 1
            current_rows.append(active)
            continue
        if current is not None:
            _finish_segment(current, current_rows)
            segments.append(current)
        current = {
            "segment_id": len(segments) + 1,
            "source_file_id": active.get("source_file_id"),
            "radio": radio,
            "active_peer_mac": peer,
            "active_peer": format_mac_h3c(peer),
            "peer_ap_name": active.get("peer_ap_name") or "",
            "peer_ap_mac": active.get("peer_ap_mac") or "",
            "peer_site": active.get("peer_site") or "",
            "peer_radio": active.get("peer_radio") or active.get("peer_radio_label") or "",
            "peer_radio_mac": active.get("peer_radio_mac") or "",
            "physical_ap_key": _physical_ap_key(active),
            "sample_interval_seconds": interval_by_radio.get((source_file_id, radio), 1.0),
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


def detect_flap_switches(
    segments: list[dict[str, object]],
    flap_window_seconds: int = 5,
    *,
    main_link_switch_time_ms: int = 2500,
    pingpong_tolerance_ms: int = 500,
    pingpong_return_window_ms: int | None = None,
) -> list[dict[str, object]]:
    flaps: list[dict[str, object]] = []
    by_radio: dict[tuple[object, object], list[dict[str, object]]] = {}
    return_window_ms = _effective_pingpong_return_window_ms(
        main_link_switch_time_ms,
        pingpong_tolerance_ms,
        pingpong_return_window_ms,
        flap_window_seconds,
    )
    for segment in segments:
        by_radio.setdefault((segment.get("source_file_id"), segment.get("radio")), []).append(segment)
    for (_source_file_id, radio), radio_segments in by_radio.items():
        ordered = sorted(radio_segments, key=lambda item: str(item.get("start_time") or ""))
        for index in range(len(ordered) - 2):
            a, b, c = ordered[index], ordered[index + 1], ordered[index + 2]
            return_duration_seconds = _seconds_between(a.get("end_time"), c.get("start_time"))
            if return_duration_seconds is None or return_duration_seconds * 1000 > return_window_ms:
                continue
            a_key, b_key, c_key = _segment_physical_ap_key(a), _segment_physical_ap_key(b), _segment_physical_ap_key(c)
            if not a_key or not b_key or not c_key:
                continue
            middle_dwell_seconds = _segment_duration_seconds(b)
            if a_key == b_key == c_key and a.get("active_peer_mac") != b.get("active_peer_mac"):
                flap_type = "同AP射频往返"
                is_ap_return_event = False
                is_abnormal = False
                reason = f"同一物理 AP 内 {a.get('peer_radio') or '-'} -> {b.get('peer_radio') or '-'} -> {c.get('peer_radio') or '-'}，不计入 AP 乒乓。"
            elif a_key == c_key and a_key != b_key:
                flap_type, is_abnormal, reason = _classify_pingpong_return_for_report(
                    a,
                    b,
                    c,
                    int(round(middle_dwell_seconds * 1000)),
                    main_link_switch_time_ms,
                    pingpong_tolerance_ms,
                )
                is_ap_return_event = True
            else:
                continue
            flaps.append(
                {
                    "sequence": len(flaps) + 1,
                    "radio": radio,
                    "source_file_id": a.get("source_file_id"),
                    "flap_type": flap_type,
                    "is_ap_return_event": is_ap_return_event,
                    "is_pingpong_abnormal": is_abnormal,
                    "start_time": a.get("start_time"),
                    "return_time": c.get("start_time"),
                    "peer_a": a.get("active_peer"),
                    "peer_b": b.get("active_peer"),
                    "peer_a_mac": a.get("active_peer_mac"),
                    "peer_b_mac": b.get("active_peer_mac"),
                    "previous_ap": _segment_ap_label(a),
                    "middle_ap": _segment_ap_label(b),
                    "return_ap": _segment_ap_label(c),
                    "window_seconds": return_duration_seconds,
                    "pingpong_return_duration_ms": int(round(return_duration_seconds * 1000)),
                    "middle_ap_dwell_ms": int(round(middle_dwell_seconds * 1000)),
                    "main_link_switch_time_ms": main_link_switch_time_ms,
                    "pingpong_tolerance_ms": pingpong_tolerance_ms,
                    "judgment_reason": reason,
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


def _active_path_report_rows(
    payload: dict[str, object],
    source_files: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    timestamps = _as_list(payload.get("timestamp_labels"))
    timestamp_tags = _as_list(payload.get("timestamp_tags"))
    sample_source_ids = _as_list(payload.get("sample_source_file_ids"))
    sample_radios = _as_list(payload.get("sample_radios"))
    active_series = dict(payload.get("active_series") or {})
    local_rssi = _as_list(active_series.get("active_local_rssi"))
    peer_rssi = _as_list(payload.get("active_peer_rssi"))
    peer_tx_busy = _as_list(payload.get("active_peer_tx_busy"))
    peer_rx_busy = _as_list(payload.get("active_peer_rx_busy"))
    local_tx_busy = _as_list(active_series.get("active_local_tx_busy"))
    local_rx_busy = _as_list(active_series.get("active_local_rx_busy"))
    peer_macs = _as_list(payload.get("active_peer_macs"))
    peer_ap_names = _as_list(payload.get("active_peer_ap_names"))
    peer_sites = _as_list(payload.get("active_peer_sites"))
    peer_radios = _as_list(payload.get("active_peer_radios"))
    source_ids = _as_list(payload.get("active_source_file_ids"))
    main_links = _as_list(payload.get("main_links_by_index"))
    source_names = {
        str(row.get("id") or ""): str(row.get("archived_filename") or row.get("original_filename") or "")
        for row in source_files
    }
    important_values = payload.get("important_indices")
    important_indices = {int(value) for value in (important_values if important_values is not None else [])}
    rssi_rows: list[dict[str, object]] = []
    busy_rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        main = main_links[index] if index < len(main_links) and isinstance(main_links[index], dict) else {}
        source_id = str(_at(sample_source_ids, index) or _at(source_ids, index) or main.get("source_file_id") or "")
        peer_mac = _at(peer_macs, index)
        common = {
            "sequence": index + 1,
            "sample_time": timestamp,
            "timestamp_tag": _at(timestamp_tags, index),
            "radio": _at(sample_radios, index) or main.get("radio") or "",
            "active_peer_mac": peer_mac,
            "peer_ap_name": _at(peer_ap_names, index),
            "peer_ap_mac": main.get("ap_mac") or "",
            "peer_site": _at(peer_sites, index),
            "peer_radio": _at(peer_radios, index),
            "peer_radio_mac": main.get("peer_radio_mac") or "",
            "source_file": source_names.get(source_id, source_id),
            "chart_key_point": index in important_indices,
        }
        rssi_rows.append(
            {
                **common,
                "mr_rssi": _finite_or_blank(_at(local_rssi, index)),
                "peer_rssi": _finite_or_blank(_at(peer_rssi, index)),
            }
        )
        busy_rows.append(
            {
                **common,
                "local_tx_busy": _finite_or_blank(_at(local_tx_busy, index)),
                "local_rx_busy": _finite_or_blank(_at(local_rx_busy, index)),
                "peer_tx_busy": _finite_or_blank(_at(peer_tx_busy, index)),
                "peer_rx_busy": _finite_or_blank(_at(peer_rx_busy, index)),
            }
        )
    return rssi_rows, busy_rows


def _peer_visit_statistics(active_build_order: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for segment in sorted(active_build_order, key=lambda item: str(item.get("build_start_time") or "")):
        identity = str(
            segment.get("peer_ap_mac")
            or segment.get("physical_ap_key")
            or segment.get("peer_ap_name")
            or segment.get("active_peer_mac")
            or "未识别AP"
        )
        counts[identity] = counts.get(identity, 0) + 1
        rows.append({**segment, "visit_sequence": counts[identity]})
    return rows


def _filter_active_build_order(
    rows: list[dict[str, object]],
    time_from: str | None,
    time_to: str | None,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for row in rows:
        start_time = str(row.get("build_start_time") or "")
        end_time = str(row.get("build_end_time") or "")
        if time_from and end_time < time_from:
            continue
        if time_to and start_time > time_to:
            continue
        filtered.append(row)
    return filtered


def _with_ap_location(
    row: dict[str, object],
    snapshot: MeshApLocationSnapshot,
) -> dict[str, object]:
    location = snapshot.resolve(row)
    result = dict(row)
    result["peer_ap_name"] = str(result.get("peer_ap_name") or location.name or "")
    result["peer_ap_mac"] = str(result.get("peer_ap_mac") or location.mac or "")
    result["peer_site"] = location.station or str(result.get("peer_site") or "")
    result["station"] = location.station or str(result.get("station") or result.get("peer_site") or "")
    result["belong_section"] = location.section or str(result.get("belong_section") or result.get("peer_section") or "")
    result["peer_section"] = result["belong_section"]
    result["section"] = result["belong_section"]
    result["peer_location"] = location.mileage or str(result.get("peer_location") or result.get("mileage") or "")
    result["mileage"] = result["peer_location"]
    result["peer_direction"] = location.line_side or str(result.get("peer_direction") or result.get("line_side") or "")
    result["line_side"] = result["peer_direction"]
    return result


def _at(values: list[object], index: int) -> object:
    return values[index] if index < len(values) else ""


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    return list(value)  # type: ignore[arg-type]


def _finite_or_blank(value: object) -> object:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return number if math.isfinite(number) else ""


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
            values = [
                value
                for value in values
                if value is not None and (metric_group != "rssi" or value != 0)
            ]
            item[f"{field_name}_avg"] = round(mean(values), 2) if values else ""
            item[f"{field_name}_min"] = min(values) if values else ""
            item[f"{field_name}_max"] = max(values) if values else ""
        result.append(item)
    return sorted(result, key=lambda item: (str(item.get("radio") or ""), str(item.get("peer_mac") or "")))


def _report_row_payload(row: dict[str, object]) -> dict[str, object]:
    metrics = {column: row.get(column) for column in _REPORT_METRIC_COLUMNS if row.get(column) is not None}
    row.setdefault("metrics_json", json.dumps(metrics, ensure_ascii=False))
    row.setdefault("deltas_json", "{}")
    return row


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
    base_duration = _seconds_between(segment.get("start_time"), segment.get("end_time")) or 0
    segment["duration_seconds"] = round(base_duration + max(float(segment.get("sample_interval_seconds") or 0), 0.0), 3)
    if rows:
        first = rows[0]
        segment["source_file_id"] = first.get("source_file_id")
        segment["peer_ap_name"] = first.get("peer_ap_name") or segment.get("peer_ap_name") or ""
        segment["peer_ap_mac"] = first.get("peer_ap_mac") or segment.get("peer_ap_mac") or ""
        segment["peer_site"] = first.get("peer_site") or segment.get("peer_site") or ""
        segment["peer_radio"] = first.get("peer_radio") or first.get("peer_radio_label") or segment.get("peer_radio") or ""
        segment["peer_radio_mac"] = first.get("peer_radio_mac") or segment.get("peer_radio_mac") or ""
        segment["identity_status"] = first.get("peer_identity_status") or first.get("identity_status") or "unresolved"
        segment["identity_source"] = first.get("peer_identity_source") or first.get("identity_source") or ""
        segment["identity_rule"] = first.get("peer_match_rule") or first.get("identity_rule") or ""
        segment["identity_confidence"] = first.get("peer_match_confidence") or first.get("identity_confidence") or 0
        segment["identity_reason"] = first.get("peer_identity_reason") or first.get("identity_reason") or ""
        segment["physical_ap_key"] = _physical_ap_key(first) or segment.get("physical_ap_key") or ""
    mr_values = [_number(row.get("mr_rssi")) for row in rows]
    mr_stats = calc_numeric_stats(mr_values, precision=2)
    segment["avg_mr_rssi"] = mr_stats["avg"]
    segment["min_mr_rssi"] = mr_stats["min"]
    segment["p10_mr_rssi"] = mr_stats["p10"]
    segment["max_mr_rssi"] = mr_stats["max"]
    for output_key, input_key in (
        ("peer_rssi", "peer_rssi"),
        ("tx_busy", "local_tx_busy"),
        ("rx_busy", "local_rx_busy"),
        ("rate_raw", "local_rate_raw"),
    ):
        values = [_number(row.get(input_key)) for row in rows]
        values = [
            value
            for value in values
            if value is not None and (input_key != "peer_rssi" or value != 0)
        ]
        segment[f"avg_{output_key}"] = round(mean(values), 2) if values else ""
        segment[f"min_{output_key}"] = min(values) if values else ""
        segment[f"max_{output_key}"] = max(values) if values else ""
    segment["first_mr_rssi"] = rows[0].get("mr_rssi") if rows else ""
    segment["source_files"] = ", ".join(sorted({str(row.get("archived_filename") or row.get("source_file") or "") for row in rows if row.get("archived_filename") or row.get("source_file")}))


def _sample_interval_by_scope(rows: list[dict[str, object]]) -> dict[tuple[object, object], float]:
    grouped: dict[tuple[object, object], list[datetime]] = {}
    for row in rows:
        parsed = _parse_time(row.get("sample_time"))
        if parsed is not None:
            grouped.setdefault((row.get("source_file_id"), row.get("radio")), []).append(parsed)
    result: dict[tuple[object, object], float] = {}
    for scope, times in grouped.items():
        ordered = sorted(set(times))
        deltas = [(current - previous).total_seconds() for previous, current in zip(ordered, ordered[1:])]
        positive = [delta for delta in deltas if delta > 0]
        result[scope] = float(median(positive)) if positive else 1.0
    return result


def _effective_pingpong_return_window_ms(
    main_link_switch_time_ms: int,
    pingpong_tolerance_ms: int,
    pingpong_return_window_ms: int | None,
    fallback_window_seconds: int,
) -> int:
    if pingpong_return_window_ms:
        return max(int(pingpong_return_window_ms), 1)
    fallback = max(int(fallback_window_seconds or 0) * 1000, 0)
    auto = max(8000, 3 * (int(main_link_switch_time_ms) + int(pingpong_tolerance_ms)))
    return max(fallback, auto)


def _classify_pingpong_return_for_report(
    previous: dict[str, object],
    middle: dict[str, object],
    returned: dict[str, object],
    middle_dwell_ms: int,
    main_link_switch_time_ms: int,
    pingpong_tolerance_ms: int,
) -> tuple[str, bool, str]:
    abnormal_threshold = max(main_link_switch_time_ms - pingpong_tolerance_ms, 0)
    critical_upper = main_link_switch_time_ms + pingpong_tolerance_ms
    sequence = f"{_segment_ap_label(previous)} -> {_segment_ap_label(middle)} -> {_segment_ap_label(returned)}"
    dwell_text = f"{middle_dwell_ms / 1000.0:.2f}s"
    if middle_dwell_ms < abnormal_threshold:
        return "AP乒乓切换异常", True, f"{sequence}，中间 AP 驻留 {dwell_text}，明显小于配置切换时间 {main_link_switch_time_ms}ms。"
    if middle_dwell_ms <= critical_upper:
        return "临界回切", False, f"{sequence}，中间 AP 驻留 {dwell_text}，接近配置切换时间 {main_link_switch_time_ms}ms，不计入乒乓异常。"
    return "普通回切事件", False, f"{sequence}，中间 AP 驻留 {dwell_text}，已超过配置切换时间 {main_link_switch_time_ms}ms，不计入乒乓异常。"


def _segment_ap_label(row: dict[str, object]) -> str:
    label = str(row.get("peer_ap_name") or "").strip() or str(row.get("active_peer") or row.get("active_peer_mac") or "-")
    station = str(row.get("peer_site") or "").strip()
    return f"{label} / {station}" if station else label


def _segment_physical_ap_key(segment: dict[str, object]) -> str:
    return str(segment.get("physical_ap_key") or "") or _physical_ap_key(segment)


def _segment_duration_seconds(segment: dict[str, object]) -> float:
    value = _number(segment.get("duration_seconds"))
    if value is not None:
        return max(value, 0.0)
    return max(_seconds_between(segment.get("start_time"), segment.get("end_time")) or 0.0, 0.0)


def _physical_ap_key(row: dict[str, object]) -> str:
    ap_mac = _canonical(row.get("peer_ap_mac"))
    if ap_mac:
        return f"ap_mac:{ap_mac}"
    peer = (
        _peer(row)
        or _canonical(row.get("peer_radio_mac"))
        or _canonical(row.get("active_peer_mac"))
    )
    return f"peer_mac:{peer}" if peer else ""


def _group_by_radio_time(rows: list[dict[str, object]]) -> list[tuple[tuple[object, str], list[dict[str, object]]]]:
    grouped: dict[tuple[object, object, str], list[dict[str, object]]] = {}
    for row in rows:
        sample_identity = row.get("sample_id") or row.get("timestamp_tag") or str(row.get("sample_time") or "")
        grouped.setdefault((row.get("radio"), sample_identity, str(row.get("sample_time") or "")), []).append(row)
    return [
        ((radio, sample_time), sample_rows)
        for (radio, _sample_identity, sample_time), sample_rows in sorted(
            grouped.items(), key=lambda item: (item[0][2], str(item[0][0]), str(item[0][1]))
        )
    ]


def _group_by_source_radio_time(rows: list[dict[str, object]]) -> list[tuple[tuple[object, object, str], list[dict[str, object]]]]:
    grouped: dict[tuple[object, object, object, str], list[dict[str, object]]] = {}
    for row in rows:
        sample_identity = row.get("sample_id") or row.get("timestamp_tag") or str(row.get("sample_time") or "")
        grouped.setdefault(
            (row.get("source_file_id"), row.get("radio"), sample_identity, str(row.get("sample_time") or "")),
            [],
        ).append(row)
    return [
        ((source_file_id, radio, sample_time), sample_rows)
        for (source_file_id, radio, _sample_identity, sample_time), sample_rows in sorted(
            grouped.items(), key=lambda item: (str(item[0][0]), item[0][3], str(item[0][1]), str(item[0][2]))
        )
    ]


def _peer(row: dict[str, object]) -> str:
    return str(row.get("peer_mac_normalized") or row.get("peer_mac") or row.get("peer_mac_raw") or "").replace("-", "").replace(":", "").lower()


def _canonical(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch in "0123456789abcdef")


def _state(row: dict[str, object]) -> str:
    return normalize_link_state(row.get("link_state") or row.get("state") or row.get("link_state_raw") or "")


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
