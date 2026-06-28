from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from netconsole.models.mesh_log_models import format_mac_h3c
from netconsole.ui.table.table_autosize_engine import apply_worksheet_autofit


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


def export_mesh_link_details_xlsx(path: Path, rows: Iterable[dict[str, object]]) -> None:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "链路明细"
    worksheet.append([title for title, _field in LINK_DETAIL_COLUMNS])
    alignment = Alignment(horizontal="center", vertical="center")
    header_font = Font(bold=True)
    for cell in worksheet[1]:
        cell.font = header_font
        cell.alignment = alignment
    for row in materialized:
        worksheet.append(link_detail_row_values(row))
    for row_cells in worksheet.iter_rows(min_row=2):
        for cell in row_cells:
            cell.alignment = alignment
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    apply_worksheet_autofit(worksheet, maximum=80)
    workbook.save(path)


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
