from __future__ import annotations

import json
from itertools import chain
import time
from pathlib import Path
from typing import Callable, Iterable

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, LINK_STATE_STANDBY, format_mac_h3c, normalize_link_state
from netconsole.services.excel_autosize import excel_column_width
from netconsole.services.excel_stream_exporter import XlsxColumn, fixed_or_sampled_width, write_row
from netconsole.services.excel_report_utils import format_link_state
from netconsole.services.export_identity_diagnostics import (
    ExportIdentityDiagnostics,
    unavailable_export_identity_diagnostics,
)

MESH_LINK_EXPORT_ACTIVE_FONT_COLOR = "15803D"
MESH_LINK_EXPORT_STANDBY_FONT_COLOR = "1D4ED8"
MESH_LINK_EXPORT_WARNING_FONT_COLOR = "C2410C"
MESH_LINK_EXPORT_HEADER_FILL = "D9EAF7"
MESH_LINK_EXPORT_GROUP_FILL_1 = "FFFFFF"
MESH_LINK_EXPORT_GROUP_FILL_2 = "F3F4F6"
MESH_LINK_EXPORT_STATUS_ACTIVE_FILL = "DCFCE7"
MESH_LINK_EXPORT_STATUS_STANDBY_FILL = "DBEAFE"
MESH_LINK_EXPORT_STATUS_WARNING_FILL = "FFEDD5"
MAX_EXCEL_WIDTH = 80.0
LINK_DETAIL_FAST_MODE_THRESHOLD = 50000
LINK_DETAIL_WIDTH_SAMPLE_ROWS = 2000

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


class MeshLinkDetailExportCancelled(Exception):
    pass


LINK_DETAIL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "record_seq"),
    ("采样时间", "sample_time"),
    ("采样标识", "timestamp_tag"),
    ("Radio", "radio"),
    ("状态", "link_state"),
    ("原始 Peer MAC", "peer_mac_raw"),
    ("解析 AP 名称", "peer_ap_name"),
    ("物理 AP MAC", "peer_ap_mac"),
    ("归属站点", "peer_site"),
    ("归属区间", "belong_section"),
    ("里程", "peer_location"),
    ("方向", "peer_direction"),
    ("Peer Radio MAC", "peer_radio_mac"),
    ("PEER Radio", "peer_radio"),
    ("建链时间", "establish_time"),
    ("链路时长", "duration_text"),
    ("LinkCnt", "link_count"),
    ("MR 侧 RSSI 差值", "local_rssi_db"),
    ("Peer 侧 RSSI 差值", "peer_rssi_db"),
    ("MR 侧底噪", "local_noise_dbm"),
    ("Peer 侧底噪", "peer_noise_dbm"),
    ("MR 接收信号", "local_signal_dbm"),
    ("Peer 接收信号", "peer_signal_dbm"),
    ("MR 侧协商速率原始值", "local_rate_raw"),
    ("Peer 侧协商速率原始值", "peer_rate_raw"),
    ("L_TxBusy", "local_tx_busy"),
    ("P_TxBusy", "peer_tx_busy"),
    ("L_RxBusy", "local_rx_busy"),
    ("P_RxBusy", "peer_rx_busy"),
    ("来源文件", "archived_filename"),
    ("行号", "source_line_number"),
    ("MR CPU", "local_cpu_percent"),
    ("Peer CPU", "peer_cpu_percent"),
    ("MR 内存", "local_mem_percent"),
    ("Peer 内存", "peer_mem_percent"),
    ("MR TxDesFreeCnt", "local_tx_des_free_cnt"),
    ("Peer TxDesFreeCnt", "peer_tx_des_free_cnt"),
    ("LocalTx", "local_tx"),
    ("PeerTx", "peer_tx"),
    ("LocalRx", "local_rx"),
    ("PeerRx", "peer_rx"),
    ("LocalRetry", "local_retry"),
    ("PeerRetry", "peer_retry"),
    ("LocalErr", "local_err"),
    ("PeerErr", "peer_err"),
    ("GARP", "local_tx_garp"),
    ("Multicast Join", "local_tx_mul_join"),
    ("匹配规则", "peer_match_rule"),
    ("身份来源", "peer_identity_source"),
    ("原始行起点", "raw_line_start"),
    ("原始行终点", "raw_line_end"),
    ("备注", "remark"),
)

EVENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "sequence"),
    ("事件类型", "event_type"),
    ("开始时间", "start_time"),
    ("结束时间", "end_time"),
    ("持续时长", "duration"),
    ("Radio", "radio"),
    ("Peer MAC", "peer_mac"),
    ("对端AP", "peer_ap_name"),
    ("对端射频", "peer_radio"),
    ("原状态", "old_state"),
    ("新状态", "new_state"),
    ("MR RSSI", "mr_rssi"),
    ("对端 RSSI", "peer_rssi"),
    ("发送繁忙度", "tx_busy"),
    ("接收繁忙度", "rx_busy"),
    ("说明", "description"),
)


ACTIVE_BUILD_ORDER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "sequence"),
    ("Radio", "radio"),
    ("原始 Peer MAC", "peer_mac_raw"),
    ("解析 AP 名称", "peer_ap_name"),
    ("物理 AP MAC", "peer_ap_mac"),
    ("归属站点", "peer_site"),
    ("归属区间", "belong_section"),
    ("里程", "mileage"),
    ("线路方向", "line_side"),
    ("对端射频口", "peer_radio"),
    ("Peer Radio MAC", "peer_radio_mac"),
    ("匹配规则", "identity_rule"),
    ("身份来源", "identity_source"),
    ("建链开始时间", "build_start_time"),
    ("建链结束时间", "build_end_time"),
    ("主链路持续时长(秒)", "main_link_duration_seconds"),
    ("日志上报时长(秒)", "reported_duration_seconds"),
    ("采样点数", "sample_count"),
    ("MR侧平均RSSI", "avg_mr_rssi"),
    ("MR侧最低RSSI", "min_mr_rssi"),
    ("MR侧最高RSSI", "max_mr_rssi"),
    ("MR侧P10 RSSI", "p10_mr_rssi"),
    ("发送繁忙度", "avg_tx_busy"),
    ("接收繁忙度", "avg_rx_busy"),
    ("Peer发送繁忙度", "avg_peer_tx_busy"),
    ("Peer接收繁忙度", "avg_peer_rx_busy"),
    ("切换稳定基准(ms)", "main_link_switch_time_ms"),
    ("兼容短时容差(ms)", "short_link_tolerance_ms"),
    ("建链门限通过", "link_establishment_accepted"),
    ("建链信号", "link_establishment_signal"),
    ("建链门限原因", "link_establishment_reason"),
    ("是否同AP射频切换", "is_same_physical_ap_radio_switch"),
    ("建链结果", "build_result"),
    ("判定原因", "judge_reason"),
    ("是否AP回切", "is_ap_return_event"),
    ("是否乒乓异常", "is_pingpong_abnormal"),
    ("乒乓类型", "pingpong_type"),
    ("乒乓组ID", "pingpong_group_id"),
    ("乒乓返回耗时(ms)", "pingpong_return_duration_ms"),
    ("中间AP驻留时长(ms)", "middle_ap_dwell_ms"),
    ("前一AP", "previous_ap"),
    ("中间AP", "middle_ap"),
    ("返回AP", "return_ap"),
    ("乒乓次数", "pingpong_count"),
    ("乒乓判定原因", "pingpong_judgment_reason"),
    ("源文件", "source_file"),
)

# 独立“导出链路明细”契约。综合分析报告仍使用上面的扩展字段集合。
LINK_DETAIL_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "record_seq"),
    ("采样时间", "sample_time"),
    ("采样标识", "timestamp_tag"),
    ("Radio", "radio"),
    ("状态", "link_state"),
    ("原始 Peer MAC", "peer_mac_raw"),
    ("解析 AP 名称", "peer_ap_name"),
    ("物理 AP MAC", "peer_ap_mac"),
    ("归属站点", "peer_site"),
    ("归属区间", "belong_section"),
    ("里程", "peer_location"),
    ("方向", "peer_direction"),
    ("Peer Radio MAC", "peer_radio_mac"),
    ("PEER Radio", "peer_radio"),
    ("匹配规则", "peer_match_rule"),
    ("身份来源", "peer_identity_source"),
    ("建链时间", "establish_time"),
    ("链路时长", "duration_text"),
    ("LinkCnt", "link_count"),
    ("MR 侧 RSSI 差值", "local_rssi_db"),
    ("Peer 侧 RSSI 差值", "peer_rssi_db"),
    ("MR 侧底噪", "local_noise_dbm"),
    ("Peer 侧底噪", "peer_noise_dbm"),
    ("MR 接收信号", "local_signal_dbm"),
    ("Peer 接收信号", "peer_signal_dbm"),
    ("MR 侧协商速率原始值", "local_rate_raw"),
    ("Peer 侧协商速率原始值", "peer_rate_raw"),
    ("L_TxBusy", "local_tx_busy"),
    ("P_TxBusy", "peer_tx_busy"),
    ("L_RxBusy", "local_rx_busy"),
    ("P_RxBusy", "peer_rx_busy"),
    ("MR CPU", "local_cpu_percent"),
    ("Peer CPU", "peer_cpu_percent"),
    ("MR 内存", "local_mem_percent"),
    ("Peer 内存", "peer_mem_percent"),
    ("LocalTx", "local_tx"),
    ("PeerTx", "peer_tx"),
    ("LocalRx", "local_rx"),
    ("PeerRx", "peer_rx"),
    ("LocalRetry", "local_retry"),
    ("PeerRetry", "peer_retry"),
    ("LocalErr", "local_err"),
    ("PeerErr", "peer_err"),
    ("来源文件", "archived_filename"),
    ("行号", "source_line_number"),
)

ACTIVE_BUILD_ORDER_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "sequence"),
    ("Radio", "radio"),
    ("原始 Peer MAC", "peer_mac_raw"),
    ("解析 AP 名称", "peer_ap_name"),
    ("物理 AP MAC", "peer_ap_mac"),
    ("归属站点", "peer_site"),
    ("归属区间", "belong_section"),
    ("Peer Radio", "peer_radio"),
    ("Peer Radio MAC", "peer_radio_mac"),
    ("匹配规则", "identity_rule"),
    ("身份来源", "identity_source"),
    ("建链开始时间", "build_start_time"),
    ("建链结束时间", "build_end_time"),
    ("主链路持续时长(s)", "main_link_duration_seconds"),
    ("日志上报时长(s)", "reported_duration_seconds"),
    ("采样点数", "sample_count"),
    ("MR 平均 RSSI", "avg_mr_rssi"),
    ("最小 RSSI", "min_mr_rssi"),
    ("最大 RSSI", "max_mr_rssi"),
    ("P10 RSSI", "p10_mr_rssi"),
    ("平均 TxBusy", "avg_tx_busy"),
    ("平均 RxBusy", "avg_rx_busy"),
    ("建链门限通过", "link_establishment_accepted"),
    ("建链门限原因", "link_establishment_reason"),
    ("建链结果", "build_result"),
    ("判定原因", "judge_reason"),
    ("乒乓类型", "pingpong_type"),
    ("来源文件", "source_file"),
)


def link_detail_row_values(row: dict[str, object]) -> list[object]:
    metrics = _json_dict(row.get("metrics_json"))
    peer = format_mac_h3c(row.get("peer_mac_normalized")) if row.get("peer_mac_normalized") else row.get("peer_mac_raw")
    local_tx_busy = metrics.get("local_tx_busy")
    peer_tx_busy = metrics.get("peer_tx_busy")
    local_rx_busy = metrics.get("local_rx_busy")
    peer_rx_busy = metrics.get("peer_rx_busy")
    return [
        row.get("record_seq") or row.get("source_line_number"),
        _excel_time_text(row.get("sample_time")),
        row.get("timestamp_tag") or "",
        row.get("radio"),
        format_link_state(row.get("link_state")),
        row.get("peer_mac_raw") or peer,
        row.get("peer_ap_name") or "-",
        format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "-",
        row.get("peer_site") or "-",
        row.get("belong_section") or row.get("peer_section") or "-",
        row.get("peer_location") or row.get("mileage") or "-",
        row.get("peer_direction") or row.get("direction") or "-",
        format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "-",
        row.get("peer_radio") or row.get("peer_radio_label") or "-",
        _excel_time_text(row.get("establish_time")),
        row.get("duration_text"),
        row.get("link_count"),
        _dash(_metric(row, metrics, "local_rssi_db")),
        _dash(_metric(row, metrics, "peer_rssi_db")),
        _dash(_metric(row, metrics, "local_noise_dbm", "local_noise_raw")),
        _dash(_metric(row, metrics, "peer_noise_dbm", "peer_noise_raw")),
        _dash(_metric(row, metrics, "local_signal_dbm")),
        _dash(_metric(row, metrics, "peer_signal_dbm")),
        _dash(_metric(row, metrics, "local_rate_raw")),
        _dash(_metric(row, metrics, "peer_rate_raw")),
        _dash(local_tx_busy),
        _dash(peer_tx_busy),
        _dash(local_rx_busy),
        _dash(peer_rx_busy),
        row.get("archived_filename") or row.get("source_file") or "-",
        _dash(row.get("source_line_number")),
        _dash(_metric(row, metrics, "local_cpu_percent")),
        _dash(_metric(row, metrics, "peer_cpu_percent")),
        _dash(_metric(row, metrics, "local_mem_percent")),
        _dash(_metric(row, metrics, "peer_mem_percent")),
        _dash(_metric(row, metrics, "local_tx_des_free_cnt")),
        _dash(_metric(row, metrics, "peer_tx_des_free_cnt")),
        _dash(_metric(row, metrics, "local_tx")),
        _dash(_metric(row, metrics, "peer_tx")),
        _dash(_metric(row, metrics, "local_rx")),
        _dash(_metric(row, metrics, "peer_rx")),
        _dash(_metric(row, metrics, "local_retry")),
        _dash(_metric(row, metrics, "peer_retry")),
        _dash(_metric(row, metrics, "local_err")),
        _dash(_metric(row, metrics, "peer_err")),
        _dash(_metric(row, metrics, "local_tx_garp")),
        _dash(_metric(row, metrics, "local_tx_mul_join")),
        row.get("peer_match_rule") or "-",
        row.get("peer_identity_source") or row.get("identity_source") or row.get("peer_resolve_source") or "-",
        _dash(row.get("raw_line_start")),
        _dash(row.get("raw_line_end")),
        _link_detail_remark(row, metrics),
    ]


def active_build_order_row_values(row: dict[str, object]) -> list[object]:
    result = str(row.get("build_result") or "")
    return [
        row.get("sequence"),
        row.get("radio"),
        row.get("peer_mac_raw") or (
            format_mac_h3c(row.get("active_peer_mac"))
            if row.get("active_peer_mac")
            else ""
        ),
        row.get("peer_ap_name") or "",
        format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "",
        row.get("peer_site") or "",
        row.get("belong_section") or row.get("peer_section") or "",
        row.get("mileage") or row.get("peer_location") or "",
        row.get("line_side") or row.get("peer_direction") or "",
        row.get("peer_radio") or "",
        format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "",
        row.get("identity_rule") or row.get("peer_match_rule") or "",
        row.get("identity_source") or row.get("peer_identity_source") or "",
        row.get("build_start_time") or "",
        row.get("build_end_time") or "",
        row.get("main_link_duration_seconds") or "",
        row.get("reported_duration_seconds") or "",
        row.get("sample_count") or "",
        _rssi_stat_value(row.get("avg_mr_rssi")),
        _rssi_stat_value(row.get("min_mr_rssi")),
        _rssi_stat_value(row.get("max_mr_rssi")),
        _rssi_stat_value(row.get("p10_mr_rssi")),
        row.get("avg_tx_busy") or "",
        row.get("avg_rx_busy") or "",
        row.get("avg_peer_tx_busy") or "",
        row.get("avg_peer_rx_busy") or "",
        row.get("main_link_switch_time_ms") or "",
        row.get("short_link_tolerance_ms") or "",
        "是" if row.get("link_establishment_accepted") else "否",
        _rssi_stat_value(row.get("link_establishment_signal")),
        row.get("link_establishment_reason") or "",
        "是" if row.get("is_same_physical_ap_radio_switch") else "否",
        _build_result_text(result),
        row.get("judge_reason") or "",
        "是" if row.get("is_ap_return_event") else "否",
        "是" if row.get("is_pingpong_abnormal") else "否",
        row.get("pingpong_type") or "",
        row.get("pingpong_group_id") or "",
        row.get("pingpong_return_duration_ms") or "",
        row.get("middle_ap_dwell_ms") or "",
        row.get("previous_ap") or "",
        row.get("middle_ap") or "",
        row.get("return_ap") or "",
        row.get("pingpong_count") or "",
        row.get("pingpong_judgment_reason") or "",
        row.get("source_file") or "",
    ]


def link_detail_export_row_values(row: dict[str, object]) -> list[object]:
    metrics = _json_dict(row.get("metrics_json"))
    peer = format_mac_h3c(row.get("peer_mac_normalized")) if row.get("peer_mac_normalized") else row.get("peer_mac_raw")
    return [
        row.get("record_seq") or row.get("source_line_number"),
        _excel_time_text(row.get("sample_time")),
        row.get("timestamp_tag") or "",
        row.get("radio"),
        format_link_state(row.get("link_state")),
        row.get("peer_mac_raw") or peer,
        row.get("peer_ap_name") or "-",
        format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "-",
        row.get("peer_site") or "-",
        row.get("belong_section") or row.get("peer_section") or "-",
        row.get("peer_location") or row.get("mileage") or "-",
        row.get("peer_direction") or row.get("direction") or "-",
        format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "-",
        row.get("peer_radio") or row.get("peer_radio_label") or "-",
        row.get("peer_match_rule") or row.get("identity_rule") or "-",
        row.get("peer_identity_source") or row.get("identity_source") or row.get("peer_resolve_source") or "-",
        _excel_time_text(row.get("establish_time")),
        row.get("duration_text") or "-",
        _dash(row.get("link_count")),
        _dash(_metric(row, metrics, "local_rssi_db")),
        _dash(_metric(row, metrics, "peer_rssi_db")),
        _dash(_metric(row, metrics, "local_noise_dbm", "local_noise_raw")),
        _dash(_metric(row, metrics, "peer_noise_dbm", "peer_noise_raw")),
        _dash(_metric(row, metrics, "local_signal_dbm")),
        _dash(_metric(row, metrics, "peer_signal_dbm")),
        _dash(_metric(row, metrics, "local_rate_raw")),
        _dash(_metric(row, metrics, "peer_rate_raw")),
        _dash(_metric(row, metrics, "local_tx_busy")),
        _dash(_metric(row, metrics, "peer_tx_busy")),
        _dash(_metric(row, metrics, "local_rx_busy")),
        _dash(_metric(row, metrics, "peer_rx_busy")),
        _dash(_metric(row, metrics, "local_cpu_percent")),
        _dash(_metric(row, metrics, "peer_cpu_percent")),
        _dash(_metric(row, metrics, "local_mem_percent")),
        _dash(_metric(row, metrics, "peer_mem_percent")),
        _dash(_metric(row, metrics, "local_tx")),
        _dash(_metric(row, metrics, "peer_tx")),
        _dash(_metric(row, metrics, "local_rx")),
        _dash(_metric(row, metrics, "peer_rx")),
        _dash(_metric(row, metrics, "local_retry")),
        _dash(_metric(row, metrics, "peer_retry")),
        _dash(_metric(row, metrics, "local_err")),
        _dash(_metric(row, metrics, "peer_err")),
        row.get("archived_filename") or row.get("source_file") or "-",
        _dash(row.get("source_line_number")),
    ]


def active_build_order_export_row_values(row: dict[str, object]) -> list[object]:
    return [
        row.get("sequence"),
        row.get("radio"),
        row.get("peer_mac_raw") or (
            format_mac_h3c(row.get("active_peer_mac"))
            if row.get("active_peer_mac")
            else ""
        ),
        row.get("peer_ap_name") or "",
        format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "",
        row.get("peer_site") or "",
        row.get("belong_section") or row.get("peer_section") or "",
        row.get("peer_radio") or "",
        format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "",
        row.get("identity_rule") or row.get("peer_match_rule") or "",
        row.get("identity_source") or row.get("peer_identity_source") or "",
        row.get("build_start_time") or "",
        row.get("build_end_time") or "",
        row.get("main_link_duration_seconds") if row.get("main_link_duration_seconds") is not None else "",
        row.get("reported_duration_seconds") if row.get("reported_duration_seconds") is not None else "",
        row.get("sample_count") if row.get("sample_count") is not None else "",
        _rssi_stat_value(row.get("avg_mr_rssi")),
        _rssi_stat_value(row.get("min_mr_rssi")),
        _rssi_stat_value(row.get("max_mr_rssi")),
        _rssi_stat_value(row.get("p10_mr_rssi")),
        row.get("avg_tx_busy") if row.get("avg_tx_busy") is not None else "",
        row.get("avg_rx_busy") if row.get("avg_rx_busy") is not None else "",
        _yes_no(row.get("link_establishment_accepted")),
        row.get("link_establishment_reason") or "",
        _build_result_text(str(row.get("build_result") or "")),
        row.get("judge_reason") or "",
        row.get("pingpong_type") or "",
        row.get("source_file") or "",
    ]


def export_mesh_link_details_xlsx(
    path: Path,
    rows: Iterable[dict[str, object]],
    active_build_order_rows: Iterable[dict[str, object]] | None = None,
    *,
    total_rows: int | None = None,
    source_files: Iterable[dict[str, object]] | None = None,
    event_rows: Iterable[dict[str, object]] | None = None,
    analysis_params: dict[str, object] | None = None,
    export_context: dict[str, object] | None = None,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - dependency is declared in requirements.txt
        raise RuntimeError("缺少 xlsxwriter 依赖，无法执行高速链路明细导出") from exc

    active_rows = list(active_build_order_rows or [])
    row_total = max(int(total_rows or 0), 0)
    fast_mode = row_total >= LINK_DETAIL_FAST_MODE_THRESHOLD
    diagnostics: ExportIdentityDiagnostics | None
    diagnostics_fallback: dict[str, object] | None = None
    try:
        diagnostics = ExportIdentityDiagnostics("mesh_link_detail")
    except Exception as exc:
        diagnostics = None
        diagnostics_fallback = unavailable_export_identity_diagnostics("mesh_link_detail", exc)
    workbook = xlsxwriter.Workbook(
        str(path),
        {
            "constant_memory": True,
            "strings_to_urls": False,
            "nan_inf_to_errors": True,
        },
    )
    closed = False
    try:
        formats = _xlsx_business_formats(workbook)
        workbook.set_properties({
            "title": "MESH 链路明细",
            "subject": "链路明细与主链路明细",
            "comments": "数据来自结构化 MESH 分析结果；主链路明细复用正式 active-build-order 查询。",
        })
        link_sheet = workbook.add_worksheet("链路明细")
        active_sheet = workbook.add_worksheet("主链路明细")
        params_sheet = workbook.add_worksheet("分析参数")

        _write_link_detail_sheet_xlsx(
            link_sheet,
            LINK_DETAIL_EXPORT_COLUMNS,
            rows,
            total_rows=row_total,
            formats=formats,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            fast_mode=fast_mode,
            diagnostics=diagnostics,
            row_factory=link_detail_export_row_values,
        )
        _write_basic_sheet_xlsx(
            active_sheet,
            ACTIVE_BUILD_ORDER_EXPORT_COLUMNS,
            active_rows,
            active_build_order_export_row_values,
            formats=formats,
            empty_message="未生成主链路建链顺序；请确认当前日志存在 ACTIVE 主链路采样。",
            should_cancel=should_cancel,
        )
        _write_params_sheet_xlsx(
            params_sheet,
            analysis_params or {},
            export_context or {},
            formats,
            should_cancel,
        )
        _raise_if_cancelled(should_cancel)
        workbook.close()
        closed = True
    except Exception:
        if not closed:
            try:
                workbook.close()
            except Exception:
                pass
        raise
    if diagnostics is None:
        diagnostics_payload = diagnostics_fallback or unavailable_export_identity_diagnostics(
            "mesh_link_detail",
            "diagnostics 初始化失败",
        )
    else:
        try:
            diagnostics_payload = diagnostics.summarize().to_dict()
        except Exception as exc:
            diagnostics_payload = unavailable_export_identity_diagnostics("mesh_link_detail", exc)
    return {"export_identity_diagnostics": diagnostics_payload}


def export_mesh_raw_links_xlsx(
    path: Path,
    rows: Iterable[dict[str, object]],
    *,
    total_rows: int | None = None,
    export_context: dict[str, object] | None = None,
    should_cancel: CancelCallback | None = None,
) -> dict[str, object]:
    """Export one source's persisted parser link rows without presentation transforms.

    The first row supplies the DB-backed column order.  Values are written
    directly to xlsxwriter: ``None`` becomes an empty cell while integer ``0``
    remains numeric zero.  No analysis filtering, identity remapping or dash
    placeholder conversion is applied here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - dependency is declared in requirements.txt
        raise RuntimeError("缺少 xlsxwriter 依赖，无法执行原始链路导出") from exc

    row_iterator = iter(rows)
    first = next(row_iterator, None)
    if first is None:
        raise RuntimeError("暂无可导出的原始链路数据")
    columns = tuple((field, field) for field in first.keys())
    specs = _xlsx_column_specs(columns)
    widths = [column.width for column in specs]
    workbook = xlsxwriter.Workbook(
        str(path),
        {
            "constant_memory": True,
            "strings_to_urls": False,
            "nan_inf_to_errors": True,
        },
    )
    closed = False
    try:
        formats = _xlsx_business_formats(workbook)
        workbook.set_properties(
            {
                "title": "MESH 原始链路",
                "subject": "Parser 持久化原始链路记录",
                "comments": str((export_context or {}).get("description") or "不经过分析筛选或身份格式化。"),
            }
        )
        sheet = workbook.add_worksheet("原始链路")
        _write_xlsx_header(sheet, specs, formats)
        sheet.freeze_panes(1, 0)
        sheet.hide_gridlines(2)
        written = 0
        for row in chain((first,), row_iterator):
            _raise_if_cancelled(should_cancel)
            values = [row.get(field) for _header, field in columns]
            default_format = formats["data"] if written % 2 == 0 else formats["zebra"]
            column_formats: dict[int, object] = {}
            for index, column in enumerate(specs):
                if column.text:
                    column_formats[index] = formats["text"] if default_format is formats["data"] else formats["zebra_text"]
                elif column.wrap:
                    column_formats[index] = formats["wrap"] if default_format is formats["data"] else formats["wrap_zebra"]
            write_row(
                sheet,
                written + 1,
                values,
                default_format=default_format,
                column_formats=column_formats,
            )
            if written < LINK_DETAIL_WIDTH_SAMPLE_ROWS:
                _update_xlsx_widths(widths, specs, values)
            written += 1
        sheet.autofilter(0, 0, max(written, 1), len(specs) - 1)
        _apply_xlsx_widths(sheet, widths)
        _raise_if_cancelled(should_cancel)
        workbook.close()
        closed = True
    except Exception:
        if not closed:
            try:
                workbook.close()
            except Exception:
                pass
        raise
    return {
        "total_rows": written,
        "column_count": len(columns),
        "source_file_id": (export_context or {}).get("source_file_id"),
    }


def _write_link_detail_sheet_xlsx(
    worksheet,
    columns: tuple[tuple[str, str], ...],
    rows: Iterable[dict[str, object]],
    *,
    total_rows: int,
    formats: dict[str, object],
    progress_callback: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    fast_mode: bool,
    diagnostics: ExportIdentityDiagnostics | None,
    row_factory: Callable[[dict[str, object]], list[object]] = link_detail_row_values,
) -> dict[str, object]:
    specs = _xlsx_column_specs(columns)
    widths = [column.width for column in specs]
    stats = _new_export_stats()
    _write_xlsx_header(worksheet, specs, formats)
    worksheet.freeze_panes(1, 0)
    worksheet.hide_gridlines(2)
    group_index = -1
    previous_group_key: tuple[object, object, object, object] | None = None
    written = 0
    last_progress_at = time.monotonic()
    for row in rows:
        _raise_if_cancelled(should_cancel)
        if diagnostics is not None and diagnostics.available:
            try:
                diagnostics.inspect_mesh_link_detail_row(row, row_index=written + 1)
            except Exception as exc:
                diagnostics.mark_unavailable(exc)
        values = row_factory(row)
        _collect_link_stats(stats, row, values)
        group_key = (row.get("source_file_id"), row.get("sample_time"), row.get("timestamp_tag"), row.get("radio"))
        if group_key != previous_group_key:
            group_index += 1
            previous_group_key = group_key
        data_format = formats["data"] if fast_mode or group_index % 2 == 0 else formats["zebra"]
        _write_xlsx_data_row(
            worksheet,
            written + 1,
            values,
            specs,
            formats,
            default_format=data_format,
            link_state=row.get("link_state"),
        )
        if written < LINK_DETAIL_WIDTH_SAMPLE_ROWS:
            _update_xlsx_widths(widths, specs, values)
        written += 1
        now = time.monotonic()
        if progress_callback is not None and (written % 1000 == 0 or now - last_progress_at >= 0.3 or (total_rows and written >= total_rows)):
            last_progress_at = now
            progress_callback(written, total_rows, "mesh_analysis.export_progress_write_links")
    data_row_count = written
    if written == 0:
        values = ["未找到可导出的链路明细数据；请检查筛选条件、源文件和解析结果。"] + ["" for _ in specs[1:]]
        _write_xlsx_data_row(worksheet, 1, values, specs, formats, default_format=formats["data"])
        data_row_count = 1
    worksheet.autofilter(0, 0, data_row_count, len(specs) - 1)
    _apply_xlsx_widths(worksheet, widths)
    if progress_callback is not None:
        progress_callback(written, total_rows, "mesh_analysis.export_progress_write_links")
    return _finalize_stats(stats, written)


def _write_basic_sheet_xlsx(
    worksheet,
    columns: tuple[tuple[str, str], ...],
    rows: Iterable[dict[str, object]],
    row_factory,
    *,
    formats: dict[str, object],
    empty_message: str,
    should_cancel: CancelCallback | None = None,
) -> None:
    specs = _xlsx_column_specs(columns)
    widths = [column.width for column in specs]
    _write_xlsx_header(worksheet, specs, formats)
    worksheet.freeze_panes(1, 0)
    worksheet.hide_gridlines(2)
    written = 0
    for row in rows:
        _raise_if_cancelled(should_cancel)
        values = row_factory(row)
        extra_formats: dict[int, object] = {}
        if str(row.get("build_result") or "") == "short":
            for index, column in enumerate(specs):
                if column.field == "build_result":
                    extra_formats[index] = formats["warning"]
                    break
        _write_xlsx_data_row(
            worksheet,
            written + 1,
            values,
            specs,
            formats,
            default_format=formats["data"] if written % 2 == 0 else formats["zebra"],
            extra_formats=extra_formats,
        )
        if written < LINK_DETAIL_WIDTH_SAMPLE_ROWS:
            _update_xlsx_widths(widths, specs, values)
        written += 1
    data_row_count = written
    if written == 0:
        values = [empty_message] + ["" for _ in specs[1:]]
        _write_xlsx_data_row(worksheet, 1, values, specs, formats, default_format=formats["data"])
        data_row_count = 1
    worksheet.autofilter(0, 0, data_row_count, len(specs) - 1)
    _apply_xlsx_widths(worksheet, widths)


def _write_event_sheet_xlsx(worksheet, event_rows: list[dict[str, object]], active_rows: list[dict[str, object]], formats: dict[str, object], should_cancel: CancelCallback | None = None) -> None:
    rows = [_event_export_row(index, row) for index, row in enumerate(event_rows, 1)]
    if not rows:
        rows = [_active_order_event_row(index, row) for index, row in enumerate(active_rows, 1) if _active_order_event_type(row)]
    _write_basic_sheet_xlsx(
        worksheet,
        EVENT_COLUMNS,
        rows,
        lambda row: [row.get(field) or "-" for _header, field in EVENT_COLUMNS],
        formats=formats,
        empty_message="当前导出范围内暂无事件明细；如未启用事件分析，请以链路明细和主链路建链顺序为准。",
        should_cancel=should_cancel,
    )


def _write_params_sheet_xlsx(worksheet, analysis_params: dict[str, object], context: dict[str, object], formats: dict[str, object], should_cancel: CancelCallback | None = None) -> None:
    rows = [
        {"key": "当前局点/线路", "value": context.get("site_name") or "-", "remark": "导出上下文"},
        {"key": "MR名称", "value": context.get("mr_name") or "-", "remark": "导出对象"},
        {"key": "导出类型", "value": "链路明细", "remark": "MR原始MESH日志分析"},
        {"key": "基准时间(ms)", "value": analysis_params.get("link_time_window", 4000), "remark": "链路事件持续范围及切换后新主链稳定性判定"},
        {"key": "切换阈值(RSSI)", "value": analysis_params.get("link_switch_threshold", 10), "remark": "主链路候选切换信号差"},
        {"key": "维持链路阈值(RSSI)", "value": analysis_params.get("link_hold_rssi", 22), "remark": "维持当前链路信号基线"},
        {"key": "发现链路阈值(RSSI)", "value": analysis_params.get("link_establish_threshold", 4), "remark": "新链路附加信号"},
        {
            "key": "建链信号阈值(RSSI)",
            "value": int(analysis_params.get("link_hold_rssi") or 22) + int(analysis_params.get("link_establish_threshold") or 4),
            "remark": "首个主链路除外；维持链路阈值 + 发现链路阈值",
        },
        {"key": "切换稳定时间阈值(ms)", "value": analysis_params.get("link_time_window", 4000), "remark": "新主链持续时间 >= 基准时间为正常切换；< 基准时间为短时建链"},
        {"key": "短时判定容差(ms)", "value": analysis_params.get("short_link_tolerance_ms", analysis_params.get("pingpong_tolerance_ms", 500)), "remark": "兼容保存字段；不参与正常切换/短时建链阈值"},
        {"key": "乒乓切换判断间隔(ms)", "value": analysis_params.get("pingpong_return_window_ms", "自动"), "remark": "未配置时按切换时间自动计算"},
        {"key": "同AP双射频合并", "value": _yes_no(analysis_params.get("merge_same_physical_ap_dual_radio", True)), "remark": "同一物理AP radio1/radio2 切换不计入AP乒乓"},
        {"key": "日志边界段纳入短时统计", "value": _yes_no(analysis_params.get("include_log_boundary_segments", False)), "remark": "边界段默认不计入短时建链异常"},
        {"key": "采样间隔(ms)", "value": analysis_params.get("sample_interval_ms") or "自动识别", "remark": "分析参数快照"},
        {"key": "业务类型", "value": analysis_params.get("service_type", "PIS"), "remark": "局点/本次导出参数"},
        {"key": "无线类型", "value": analysis_params.get("wifi_type", "WiFi6"), "remark": "局点/本次导出参数"},
        {"key": "单AP详情图表窗口(秒)", "value": 120, "remark": "当前点左右各60秒"},
        {"key": "AP扩展信息匹配", "value": "启用", "remark": "使用当前解析结果中的AP归属字段"},
        {"key": "FIT-AP资源匹配", "value": "如当前解析已补齐则使用", "remark": "无法匹配时显示 - 或 未匹配"},
    ]
    _write_key_value_sheet_xlsx(worksheet, rows, formats, should_cancel)


def _write_description_sheet_xlsx(
    worksheet,
    stats: dict[str, object],
    active_rows: list[dict[str, object]],
    source_files: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    context: dict[str, object],
    formats: dict[str, object],
    should_cancel: CancelCallback | None,
) -> None:
    rows = [
        {"key": "软件名称", "value": "NetConsole", "remark": ""},
        {"key": "模块名称", "value": "MR原始MESH日志分析", "remark": ""},
        {"key": "导出类型", "value": "链路明细", "remark": "正式业务导出表"},
        {"key": "局点 / 线路 / 项目", "value": context.get("site_name") or "-", "remark": ""},
        {"key": "MR名称", "value": context.get("mr_name") or "-", "remark": ""},
        {"key": "源文件名称", "value": _source_file_names(source_files) or context.get("source_label") or "-", "remark": ""},
        {"key": "导出时间", "value": context.get("exported_at") or "-", "remark": ""},
        {"key": "分析开始时间", "value": stats.get("start_time") or "-", "remark": ""},
        {"key": "分析结束时间", "value": stats.get("end_time") or "-", "remark": ""},
        {"key": "采样总数", "value": stats.get("sample_count") or 0, "remark": "按源文件+采样时间+Radio去重"},
        {"key": "Peer数量", "value": stats.get("peer_count") or 0, "remark": ""},
        {"key": "Radio数量", "value": stats.get("radio_count") or 0, "remark": ""},
        {"key": "ACTIVE数量", "value": stats.get("active_count") or 0, "remark": ""},
        {"key": "STANDBY数量", "value": stats.get("standby_count") or 0, "remark": ""},
        {"key": "主备切换次数", "value": max(len(active_rows) - 1, 0), "remark": "基于主链路建链顺序估算"},
        {"key": "短时建链次数", "value": _short_build_count(active_rows), "remark": ""},
        {"key": "乒乓切换次数", "value": _pingpong_count(active_rows), "remark": ""},
        {"key": "事件明细数量", "value": len(event_rows), "remark": "如事件表未启用，则使用主链路建链顺序补充异常项"},
        {"key": "异常说明", "value": _export_exception_summary(active_rows, event_rows), "remark": ""},
    ]
    _write_key_value_sheet_xlsx(worksheet, rows, formats, should_cancel)


def _write_summary_sheet_xlsx(worksheet, stats: dict[str, object], active_rows: list[dict[str, object]], event_rows: list[dict[str, object]], formats: dict[str, object], should_cancel: CancelCallback | None) -> None:
    total = int(stats.get("total_rows") or 0)
    active_count = int(stats.get("active_count") or 0)
    standby_count = int(stats.get("standby_count") or 0)
    rows = [
        {"key": "总链路记录数", "value": total, "remark": "链路明细总行数"},
        {"key": "总采样点数", "value": stats.get("sample_count") or 0, "remark": "按源文件+采样时间+Radio去重"},
        {"key": "主链路采样点数", "value": active_count, "remark": "ACTIVE记录数"},
        {"key": "备份链路采样点数", "value": standby_count, "remark": "STANDBY/BACKUP记录数"},
        {"key": "ACTIVE占比", "value": _ratio_text(active_count, total), "remark": ""},
        {"key": "STANDBY占比", "value": _ratio_text(standby_count, total), "remark": ""},
        {"key": "Peer数量", "value": stats.get("peer_count") or 0, "remark": ""},
        {"key": "AP数量", "value": stats.get("ap_count") or 0, "remark": "按对端AP MAC/名称去重"},
        {"key": "Radio数量", "value": stats.get("radio_count") or 0, "remark": ""},
        {"key": "最小MR RSSI", "value": _dash(stats.get("min_mr_rssi")), "remark": ""},
        {"key": "平均MR RSSI", "value": _round_or_dash(stats.get("avg_mr_rssi")), "remark": ""},
        {"key": "最大MR RSSI", "value": _dash(stats.get("max_mr_rssi")), "remark": ""},
        {"key": "最小对端RSSI", "value": _dash(stats.get("min_peer_rssi")), "remark": ""},
        {"key": "平均对端RSSI", "value": _round_or_dash(stats.get("avg_peer_rssi")), "remark": ""},
        {"key": "最大对端RSSI", "value": _dash(stats.get("max_peer_rssi")), "remark": ""},
        {"key": "最大发送繁忙度", "value": _dash(stats.get("max_tx_busy")), "remark": ""},
        {"key": "最大接收繁忙度", "value": _dash(stats.get("max_rx_busy")), "remark": ""},
        {"key": "切换次数", "value": max(len(active_rows) - 1, 0), "remark": "基于主链路建链顺序估算"},
        {"key": "短时建链次数", "value": _short_build_count(active_rows), "remark": ""},
        {"key": "乒乓切换次数", "value": _pingpong_count(active_rows), "remark": ""},
        {"key": "事件明细数量", "value": len(event_rows), "remark": ""},
    ]
    _write_key_value_sheet_xlsx(worksheet, rows, formats, should_cancel)


def _write_key_value_sheet_xlsx(worksheet, rows: list[dict[str, object]], formats: dict[str, object], should_cancel: CancelCallback | None) -> None:
    columns = (("统计项", "key"), ("数值", "value"), ("说明", "remark"))
    _write_basic_sheet_xlsx(
        worksheet,
        columns,
        rows,
        lambda row: [row.get("key") or "-", _dash(row.get("value")), row.get("remark") or ""],
        formats=formats,
        empty_message="暂无数据",
        should_cancel=should_cancel,
    )


def _xlsx_business_formats(workbook) -> dict[str, object]:
    base = {"align": "center", "valign": "vcenter", "font_color": "#111827"}
    return {
        "header": workbook.add_format({**base, "bold": True, "bg_color": f"#{MESH_LINK_EXPORT_HEADER_FILL}", "border": 1, "border_color": "#D1D5DB"}),
        "data": workbook.add_format({**base}),
        "text": workbook.add_format({**base, "num_format": "@"}),
        "zebra": workbook.add_format({**base, "bg_color": f"#{MESH_LINK_EXPORT_GROUP_FILL_2}"}),
        "zebra_text": workbook.add_format({**base, "bg_color": f"#{MESH_LINK_EXPORT_GROUP_FILL_2}", "num_format": "@"}),
        "wrap": workbook.add_format({**base, "text_wrap": True}),
        "wrap_zebra": workbook.add_format({**base, "bg_color": f"#{MESH_LINK_EXPORT_GROUP_FILL_2}", "text_wrap": True}),
        "active": workbook.add_format({**base, "bold": True, "font_color": f"#{MESH_LINK_EXPORT_ACTIVE_FONT_COLOR}", "bg_color": f"#{MESH_LINK_EXPORT_STATUS_ACTIVE_FILL}"}),
        "standby": workbook.add_format({**base, "font_color": f"#{MESH_LINK_EXPORT_STANDBY_FONT_COLOR}", "bg_color": f"#{MESH_LINK_EXPORT_STATUS_STANDBY_FILL}"}),
        "warning": workbook.add_format({**base, "bold": True, "font_color": f"#{MESH_LINK_EXPORT_WARNING_FONT_COLOR}", "bg_color": f"#{MESH_LINK_EXPORT_STATUS_WARNING_FILL}"}),
    }


def _xlsx_column_specs(columns: tuple[tuple[str, str], ...]) -> list[XlsxColumn]:
    return [
        XlsxColumn(
            header=header,
            field=field,
            width=_fixed_column_width(field, header),
            max_width=_column_max_width(field),
            text=_is_text_field(field),
            wrap=field in {"remark", "judge_reason", "pingpong_judgment_reason", "description"},
        )
        for header, field in columns
    ]


def _write_xlsx_header(worksheet, specs: list[XlsxColumn], formats: dict[str, object]) -> None:
    worksheet.set_row(0, 24)
    write_row(worksheet, 0, [column.header for column in specs], default_format=formats["header"])


def _write_xlsx_data_row(
    worksheet,
    row_index: int,
    values: list[object],
    specs: list[XlsxColumn],
    formats: dict[str, object],
    *,
    default_format,
    link_state: object = None,
    extra_formats: dict[int, object] | None = None,
) -> None:
    column_formats: dict[int, object] = {}
    for index, column in enumerate(specs):
        if column.wrap:
            column_formats[index] = formats["wrap_zebra"] if default_format is formats.get("zebra") else formats["wrap"]
        elif column.text:
            column_formats[index] = formats["zebra_text"] if default_format is formats.get("zebra") else formats["text"]
    if link_state is not None:
        for index, column in enumerate(specs):
            if column.field == "link_state":
                column_formats[index] = _state_xlsx_format(link_state, formats)
                break
    if extra_formats:
        column_formats.update(extra_formats)
    write_row(worksheet, row_index, [_cell_value(value) for value in values], default_format=default_format, column_formats=column_formats)


def _state_xlsx_format(state: object, formats: dict[str, object]):
    normalized = normalize_link_state(state)
    if normalized == LINK_STATE_ACTIVE:
        return formats["active"]
    if normalized == LINK_STATE_STANDBY:
        return formats["standby"]
    return formats["warning"]


def _update_xlsx_widths(widths: list[float], specs: list[XlsxColumn], values: list[object]) -> None:
    for index, value in enumerate(values):
        if index >= len(widths):
            break
        column = specs[index]
        widths[index] = fixed_or_sampled_width(widths[index], value, minimum=column.width, maximum=column.max_width)


def _apply_xlsx_widths(worksheet, widths: list[float]) -> None:
    for index, width in enumerate(widths):
        worksheet.set_column(index, index, min(max(width, 8.0), MAX_EXCEL_WIDTH))


def _fixed_column_width(field: str, header: str) -> float:
    widths = {
        "record_seq": 10.0,
        "sequence": 10.0,
        "sample_time": 24.0,
        "radio": 10.0,
        "link_state": 12.0,
        "peer_mac": 20.0,
        "active_peer_mac": 20.0,
        "peer_ap_mac": 20.0,
        "peer_ap_name": 24.0,
        "peer_site": 18.0,
        "belong_section": 22.0,
        "belong_type": 12.0,
        "peer_radio": 14.0,
        "establish_time": 24.0,
        "duration_text": 14.0,
        "link_count": 12.0,
        "local_rssi_db": 12.0,
        "peer_rssi_db": 12.0,
        "local_cpu_percent": 12.0,
        "peer_cpu_percent": 12.0,
        "local_noise_dbm": 12.0,
        "peer_noise_dbm": 12.0,
        "local_tx_busy": 14.0,
        "local_rx_busy": 14.0,
        "max_tx_busy": 16.0,
        "max_rx_busy": 16.0,
        "archived_filename": 36.0,
        "source_file": 36.0,
        "source_line_number": 12.0,
        "remark": 50.0,
    }
    if field in widths:
        return widths[field]
    return max(10.0, min(excel_column_width(header, field=field, header=header), 36.0))


def _column_max_width(field: str) -> float:
    if field in {"remark", "judge_reason", "pingpong_judgment_reason", "description"}:
        return 60.0
    if field in {"archived_filename", "source_file"}:
        return 45.0
    if field in {"build_start_time", "build_end_time", "start_time", "end_time"}:
        return 26.0
    return 36.0


def _is_text_field(field: str) -> bool:
    return field in {
        "sample_time",
        "establish_time",
        "build_start_time",
        "build_end_time",
        "start_time",
        "end_time",
        "peer_mac",
        "peer_ap_mac",
        "active_peer_mac",
        "source_file",
        "archived_filename",
    }


def _raise_if_cancelled(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise MeshLinkDetailExportCancelled("导出已取消")


def _new_export_stats() -> dict[str, object]:
    return {
        "samples": set(),
        "peers": set(),
        "aps": set(),
        "radios": set(),
        "active_count": 0,
        "standby_count": 0,
        "mr_rssi_values": [],
        "peer_rssi_values": [],
        "tx_busy_values": [],
        "rx_busy_values": [],
        "start_time": "",
        "end_time": "",
    }


def _collect_link_stats(stats: dict[str, object], row: dict[str, object], values: list[object]) -> None:
    metrics = _json_dict(row.get("metrics_json"))
    sample_time = str(row.get("sample_time") or "")
    if sample_time:
        stats["samples"].add(  # type: ignore[index, union-attr]
            (row.get("source_file_id"), sample_time, row.get("timestamp_tag"), row.get("radio"))
        )
        stats["start_time"] = min(str(stats.get("start_time") or sample_time), sample_time) if stats.get("start_time") else sample_time
        stats["end_time"] = max(str(stats.get("end_time") or sample_time), sample_time)
    peer = row.get("peer_mac_normalized") or row.get("peer_mac") or row.get("peer_mac_raw")
    if peer:
        stats["peers"].add(str(peer))  # type: ignore[index, union-attr]
    ap = row.get("peer_ap_mac") or row.get("peer_ap_name")
    if ap:
        stats["aps"].add(str(ap))  # type: ignore[index, union-attr]
    if row.get("radio") not in (None, ""):
        stats["radios"].add(str(row.get("radio")))  # type: ignore[index, union-attr]
    state = normalize_link_state(row.get("link_state"))
    if state == LINK_STATE_ACTIVE:
        stats["active_count"] = int(stats.get("active_count") or 0) + 1
    elif state == LINK_STATE_STANDBY:
        stats["standby_count"] = int(stats.get("standby_count") or 0) + 1
    for key, target in (
        ("local_rssi_db", "mr_rssi_values"),
        ("peer_rssi_db", "peer_rssi_values"),
        ("local_tx_busy", "tx_busy_values"),
        ("local_rx_busy", "rx_busy_values"),
    ):
        value = _number(metrics.get(key))
        if value is not None:
            stats[target].append(value)  # type: ignore[index, union-attr]


def _finalize_stats(stats: dict[str, object], total_rows: int) -> dict[str, object]:
    mr_values = list(stats.get("mr_rssi_values") or [])
    peer_values = list(stats.get("peer_rssi_values") or [])
    tx_values = list(stats.get("tx_busy_values") or [])
    rx_values = list(stats.get("rx_busy_values") or [])
    return {
        "total_rows": total_rows,
        "sample_count": len(stats.get("samples") or []),
        "peer_count": len(stats.get("peers") or []),
        "ap_count": len(stats.get("aps") or []),
        "radio_count": len(stats.get("radios") or []),
        "active_count": stats.get("active_count") or 0,
        "standby_count": stats.get("standby_count") or 0,
        "min_mr_rssi": min(mr_values) if mr_values else None,
        "avg_mr_rssi": sum(mr_values) / len(mr_values) if mr_values else None,
        "max_mr_rssi": max(mr_values) if mr_values else None,
        "min_peer_rssi": min(peer_values) if peer_values else None,
        "avg_peer_rssi": sum(peer_values) / len(peer_values) if peer_values else None,
        "max_peer_rssi": max(peer_values) if peer_values else None,
        "max_tx_busy": max(tx_values) if tx_values else None,
        "max_rx_busy": max(rx_values) if rx_values else None,
        "start_time": _excel_time_text(stats.get("start_time")),
        "end_time": _excel_time_text(stats.get("end_time")),
    }


def _event_export_row(index: int, row: dict[str, object]) -> dict[str, object]:
    return {
        "sequence": index,
        "event_type": row.get("event_type") or row.get("switch_type") or row.get("type") or "-",
        "start_time": _excel_time_text(row.get("event_time") or row.get("previous_sample_time") or row.get("current_sample_time")),
        "end_time": _excel_time_text(row.get("current_sample_time") or row.get("event_time")),
        "duration": row.get("observed_window_ms") or "-",
        "radio": row.get("radio") or "-",
        "peer_mac": format_mac_h3c(row.get("to_peer_mac") or row.get("from_peer_mac") or row.get("peer_mac")) or "-",
        "peer_ap_name": row.get("peer_ap_name") or "-",
        "peer_radio": row.get("peer_radio") or "-",
        "old_state": row.get("old_state") or row.get("from_state") or "-",
        "new_state": row.get("new_state") or row.get("to_state") or "-",
        "mr_rssi": _dash(row.get("to_local_rssi") or row.get("from_local_rssi")),
        "peer_rssi": _dash(row.get("to_peer_rssi") or row.get("from_peer_rssi")),
        "tx_busy": _dash(row.get("tx_busy")),
        "rx_busy": _dash(row.get("rx_busy")),
        "description": row.get("description") or row.get("diagnosis") or row.get("event_type") or "-",
    }


def _active_order_event_row(index: int, row: dict[str, object]) -> dict[str, object]:
    return {
        "sequence": index,
        "event_type": _active_order_event_type(row),
        "start_time": _excel_time_text(row.get("build_start_time")),
        "end_time": _excel_time_text(row.get("build_end_time")),
        "duration": row.get("main_link_duration_seconds") or "-",
        "radio": row.get("radio") or "-",
        "peer_mac": row.get("active_peer_mac") or "-",
        "peer_ap_name": row.get("peer_ap_name") or "-",
        "peer_radio": row.get("peer_radio") or "-",
        "old_state": "-",
        "new_state": row.get("build_result") or "-",
        "mr_rssi": _dash(row.get("avg_mr_rssi")),
        "peer_rssi": "-",
        "tx_busy": _dash(row.get("avg_tx_busy")),
        "rx_busy": _dash(row.get("avg_rx_busy")),
        "description": row.get("judge_reason") or row.get("pingpong_judgment_reason") or _active_order_event_type(row),
    }


def _active_order_event_type(row: dict[str, object]) -> str:
    if row.get("is_pingpong_abnormal"):
        return "乒乓切换"
    if str(row.get("build_result") or "") == "short":
        return "短时建链"
    if str(row.get("build_result") or "") == "normal":
        return "正常切换"
    if row.get("is_same_physical_ap_radio_switch"):
        return "同AP射频切换"
    return ""


def _build_result_text(value: str) -> str:
    if value == "normal":
        return "正常切换"
    if value == "short":
        return "短时建链"
    if value == "same_ap_radio_switch":
        return "同AP射频切换"
    if value == "stable":
        return "稳定主链（非切换）"
    return value


def _source_file_names(source_files: list[dict[str, object]]) -> str:
    names = [str(row.get("archived_filename") or row.get("original_filename") or "").strip() for row in source_files]
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) <= 3:
        return "、".join(names)
    return "、".join(names[:3]) + f" 等 {len(names)} 个源文件"


def _short_build_count(rows: list[dict[str, object]]) -> int:
    return sum(1 for row in rows if str(row.get("build_result") or "") == "short")


def _pingpong_count(rows: list[dict[str, object]]) -> int:
    return sum(1 for row in rows if row.get("is_pingpong_abnormal") or str(row.get("pingpong_type") or "") not in {"", "无"})


def _export_exception_summary(active_rows: list[dict[str, object]], event_rows: list[dict[str, object]]) -> str:
    parts = []
    short_count = _short_build_count(active_rows)
    pingpong_count = _pingpong_count(active_rows)
    if short_count:
        parts.append(f"短时建链 {short_count} 次")
    if pingpong_count:
        parts.append(f"乒乓/回切相关 {pingpong_count} 次")
    if event_rows:
        parts.append(f"事件记录 {len(event_rows)} 条")
    return "；".join(parts) if parts else "未发现明显异常事件；请结合链路明细筛选复核。"


def _ratio_text(count: int, total: int) -> str:
    return f"{count / total:.2%}" if total else "-"


def _round_or_dash(value: object) -> object:
    number = _number(value)
    return "-" if number is None else round(number, 3)


def _yes_no(value: object) -> str:
    if isinstance(value, str):
        return "是" if value.strip().lower() in {"1", "true", "yes", "on", "是", "开启"} else "否"
    return "是" if bool(value) else "否"


def _belong_type_text(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "station": "车站",
        "section": "区间",
        "yard": "场段",
        "area": "区域",
        "empty": "空链路",
        "unknown": "未知",
    }
    if not text:
        return "-"
    return mapping.get(text, str(value))


def _rssi_stat_value(value: object) -> object:
    return "N/A" if value is None or value == "" else value


def _link_detail_remark(row: dict[str, object], _metrics: dict[str, object]) -> str:
    if not row.get("peer_site") and not row.get("belong_section"):
        return "未匹配AP点位"
    if normalize_link_state(row.get("link_state")) == LINK_STATE_ACTIVE:
        return "当前采样点主链路"
    return ""


def _max_numeric(*values: object) -> float | None:
    numbers = [_number(value) for value in values]
    finite = [value for value in numbers if value is not None]
    return max(finite) if finite else None


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric(row: dict[str, object], metrics: dict[str, object], key: str, fallback_key: str | None = None) -> object:
    if row.get(key) is not None:
        return row.get(key)
    if metrics.get(key) is not None:
        return metrics.get(key)
    return metrics.get(fallback_key) if fallback_key else None


def _dash(value: object) -> object:
    if value is None:
        return "-"
    if isinstance(value, float) and value != value:
        return "-"
    text = str(value)
    if text.strip().lower() in {"", "none", "nan", "null"}:
        return "-"
    return value


def _cell_value(value: object) -> object:
    value = _dash(value)
    return "-" if value == "" else value


def _excel_time_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(text)
        return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except ValueError:
        return text


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
