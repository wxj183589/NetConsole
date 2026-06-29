from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from netconsole.models.mesh_log_models import format_mac_h3c
from netconsole.ui.table.table_autosize_engine import apply_worksheet_autofit

MESH_LINK_EXPORT_ACTIVE_FONT_COLOR = "15803D"
MESH_LINK_EXPORT_GROUP_FILL_1 = "FFFFFF"
MESH_LINK_EXPORT_GROUP_FILL_2 = "F3F4F6"


LINK_DETAIL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "record_seq"),
    ("时间", "sample_time"),
    ("Radio", "radio"),
    ("LinkState", "link_state"),
    ("PeerMac", "peer_mac"),
    ("当前PEER AP名称", "peer_ap_name"),
    ("AP MAC", "peer_ap_mac"),
    ("归属站点", "peer_site"),
    ("Peer Radio MAC", "peer_radio_mac"),
    ("EER Radio", "peer_radio"),
    ("EstablishTime", "establish_time"),
    ("DurationTime", "duration_text"),
    ("LinkCnt", "link_count"),
    ("L_Rssi", "local_rssi_db"),
    ("P_Rssi", "peer_rssi_db"),
    ("L_Cpu", "local_cpu_percent"),
    ("P_Cpu", "peer_cpu_percent"),
    ("L_Mem", "local_mem_percent"),
    ("P_Mem", "peer_mem_percent"),
    ("L_TxBusy", "local_tx_busy"),
    ("L_RxBusy", "local_rx_busy"),
    ("P_TxBusy", "peer_tx_busy"),
    ("P_RxBusy", "peer_rx_busy"),
    ("源文件", "archived_filename"),
    ("源行号", "source_line_number"),
)


ACTIVE_BUILD_ORDER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("序号", "sequence"),
    ("Radio", "radio"),
    ("Active PeerMac", "active_peer_mac"),
    ("当前PEER AP名称", "peer_ap_name"),
    ("归属站点", "peer_site"),
    ("Peer Radio", "peer_radio"),
    ("建链开始时间", "build_start_time"),
    ("建链结束时间", "build_end_time"),
    ("主链路维持时长(s)", "main_link_duration_seconds"),
    ("设备上报链路时长(s)", "reported_duration_seconds"),
    ("采样数", "sample_count"),
    ("MR RSSI平均", "avg_mr_rssi"),
    ("MR RSSI最小", "min_mr_rssi"),
    ("MR RSSI最大", "max_mr_rssi"),
    ("TxBusy平均", "avg_tx_busy"),
    ("RxBusy平均", "avg_rx_busy"),
    ("建链结果", "build_result"),
    ("来源文件", "source_file"),
)


def link_detail_row_values(row: dict[str, object]) -> list[object]:
    metrics = _json_dict(row.get("metrics_json"))
    peer = format_mac_h3c(row.get("peer_mac_normalized")) if row.get("peer_mac_normalized") else row.get("peer_mac_raw")
    return [
        row.get("record_seq") or row.get("source_line_number"),
        row.get("sample_time"),
        row.get("radio"),
        row.get("link_state"),
        row.get("peer_mac_raw") or peer,
        row.get("peer_ap_name") or "-",
        format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "-",
        row.get("peer_site") or "-",
        format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "-",
        row.get("peer_radio") or row.get("peer_radio_label") or "-",
        row.get("establish_time"),
        row.get("duration_text"),
        row.get("link_count"),
        metrics.get("local_rssi_db"),
        metrics.get("peer_rssi_db"),
        metrics.get("local_cpu_percent"),
        metrics.get("peer_cpu_percent"),
        metrics.get("local_mem_percent"),
        metrics.get("peer_mem_percent"),
        metrics.get("local_tx_busy"),
        metrics.get("local_rx_busy"),
        metrics.get("peer_tx_busy"),
        metrics.get("peer_rx_busy"),
        row.get("archived_filename"),
        row.get("source_line_number"),
    ]


def active_build_order_row_values(row: dict[str, object]) -> list[object]:
    result = str(row.get("build_result") or "")
    return [
        row.get("sequence"),
        row.get("radio"),
        format_mac_h3c(row.get("active_peer_mac")) if row.get("active_peer_mac") else "",
        row.get("peer_ap_name") or "",
        row.get("peer_site") or "",
        row.get("peer_radio") or "",
        row.get("build_start_time") or "",
        row.get("build_end_time") or "",
        row.get("main_link_duration_seconds") or "",
        row.get("reported_duration_seconds") or "",
        row.get("sample_count") or "",
        row.get("avg_mr_rssi") or "",
        row.get("min_mr_rssi") or "",
        row.get("max_mr_rssi") or "",
        row.get("avg_tx_busy") or "",
        row.get("avg_rx_busy") or "",
        "正常" if result == "normal" else "短时建链" if result == "short" else result,
        row.get("source_file") or "",
    ]


def export_mesh_link_details_xlsx(path: Path, rows: Iterable[dict[str, object]], active_build_order_rows: Iterable[dict[str, object]] | None = None) -> None:
    materialized = list(rows)
    active_build_order_materialized = list(active_build_order_rows or [])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    _write_link_detail_sheet(workbook.active, "链路明细", LINK_DETAIL_COLUMNS, materialized)
    _write_basic_sheet(workbook.create_sheet("主链路建链顺序"), ACTIVE_BUILD_ORDER_COLUMNS, active_build_order_materialized, active_build_order_row_values)
    workbook.save(path)


def _write_link_detail_sheet(worksheet, title: str, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object]]) -> None:
    worksheet.title = title
    worksheet.append([header for header, _field in columns])
    alignment = Alignment(horizontal="center", vertical="center")
    header_font = Font(bold=True)
    active_font = Font(bold=True, color=MESH_LINK_EXPORT_ACTIVE_FONT_COLOR)
    standby_font = Font(bold=False)
    group_fill_1 = PatternFill(fill_type="solid", fgColor=MESH_LINK_EXPORT_GROUP_FILL_1)
    group_fill_2 = PatternFill(fill_type="solid", fgColor=MESH_LINK_EXPORT_GROUP_FILL_2)
    for cell in worksheet[1]:
        cell.font = header_font
        cell.alignment = alignment
    group_indexes = _sample_group_indexes(rows)
    for row_index, row in enumerate(rows, start=2):
        worksheet.append(link_detail_row_values(row))
        group_index = group_indexes[row_index - 2]
        fill = group_fill_1 if group_index % 2 == 0 else group_fill_2
        font = active_font if str(row.get("link_state") or "").upper() == "ACTIVE" else standby_font
        for cell in worksheet[row_index]:
            cell.alignment = alignment
            cell.fill = fill
            cell.font = font
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    apply_worksheet_autofit(worksheet, maximum=80)


def _write_basic_sheet(worksheet, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object]], row_factory) -> None:
    worksheet.append([header for header, _field in columns])
    alignment = Alignment(horizontal="center", vertical="center")
    header_font = Font(bold=True)
    for cell in worksheet[1]:
        cell.font = header_font
        cell.alignment = alignment
    for row in rows:
        worksheet.append(row_factory(row))
    for row_cells in worksheet.iter_rows(min_row=2):
        for cell in row_cells:
            cell.alignment = alignment
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    apply_worksheet_autofit(worksheet, maximum=80)


def _sample_group_indexes(rows: list[dict[str, object]]) -> list[int]:
    result: list[int] = []
    group_indexes: dict[tuple[object, object], int] = {}
    for row in rows:
        raw_group = row.get("sample_group_index")
        if raw_group not in (None, ""):
            try:
                result.append(int(raw_group))
                continue
            except (TypeError, ValueError):
                pass
        key = (row.get("sample_time"), row.get("radio"))
        if key not in group_indexes:
            group_indexes[key] = len(group_indexes)
        result.append(group_indexes[key])
    return result


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
