from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from netconsole.services.mesh_analysis_report import MeshAnalysisReportModel


EMPTY_PARSE_ISSUES_TEXT = "未发现解析问题"


SHEET_DEFINITIONS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("概览", ("项目", "值"), "overview"),
    ("主链路切换顺序", ("序号", "Radio", "切换时间", "原PeerMac", "新PeerMac", "原段开始", "原段结束", "原段时长(s)", "新段结束", "新段时长(s)", "原MR RSSI", "新MR RSSI"), "switch_sequence"),
    ("Active主链路段", ("段号", "Radio", "Active PeerMac", "开始时间", "结束时间", "时长(s)", "采样数", "MR RSSI均值", "MR RSSI最小", "MR RSSI最大", "Peer RSSI均值", "TxBusy均值", "RxBusy均值", "来源文件"), "active_segments"),
    ("来回切换", ("序号", "Radio", "类型", "开始时间", "回切时间", "Peer A", "Peer B", "窗口(s)"), "flap_events"),
    ("建链顺序", ("序号", "Radio", "PeerMac", "首次出现", "首次建链", "最后出现", "采样数", "Active采样", "Standby采样", "最大链路时长(s)"), "link_establishment_order"),
    ("Peer生命周期", ("Radio", "PeerMac", "首次出现", "最后出现", "首次Active", "最后Active", "Active段数", "Active采样", "Standby采样", "切入次数", "切出次数"), "peer_lifecycle"),
    ("无Active与多Active", ("类型", "Radio", "开始时间", "结束时间", "Active数量", "Active PeerMac", "采样数"), "active_anomalies"),
    ("RSSI统计", ("Radio", "PeerMac", "采样数", "MR RSSI均值", "MR RSSI最小", "MR RSSI最大", "Peer RSSI均值", "Peer RSSI最小", "Peer RSSI最大"), "rssi_statistics"),
    ("空口负载统计", ("Radio", "PeerMac", "采样数", "MR TxBusy均值", "MR TxBusy最大", "MR RxBusy均值", "MR RxBusy最大", "Peer TxBusy均值", "Peer RxBusy均值"), "channel_busy_statistics"),
    ("原始事件明细", ("事件时间", "Radio", "事件类型", "原PeerMac", "新PeerMac", "观察窗口(ms)", "来源文件", "行号", "详情"), "raw_events"),
    ("解析问题", ("来源文件", "行号", "级别", "类型", "字段", "说明", "原始内容"), "parse_issues"),
)


class MeshAnalysisExcelReportExporter:
    def export(self, model: MeshAnalysisReportModel, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        workbook.remove(workbook.active)
        for sheet_name, headers, attr_name in SHEET_DEFINITIONS:
            sheet = workbook.create_sheet(sheet_name)
            self._write_sheet(sheet, headers, self._rows_for(model, attr_name), attr_name)
            self._format_sheet(sheet)
        workbook.save(path)
        return path

    def _write_sheet(self, sheet, headers: Iterable[str], rows: list[dict[str, object]] | list[tuple[object, ...]], attr_name: str) -> None:
        header_values = list(headers)
        sheet.append(header_values)
        if attr_name == "parse_issues" and not rows:
            sheet.append((EMPTY_PARSE_ISSUES_TEXT, "", "", "", "", "", ""))
            return
        for row in rows:
            sheet.append(tuple(row) if not isinstance(row, dict) else self._dict_to_row(attr_name, row))

    def _format_sheet(self, sheet) -> None:
        header_fill = PatternFill("solid", fgColor="1F4E78")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column)
            sheet.column_dimensions[get_column_letter(column[0].column)].width = min(max(max_length + 2, 12), 42)

    def _rows_for(self, model: MeshAnalysisReportModel, attr_name: str) -> list[dict[str, object]] | list[tuple[object, ...]]:
        if attr_name == "overview":
            return [(key, value) for key, value in model.overview.items()]
        return list(getattr(model, attr_name))

    def _dict_to_row(self, attr_name: str, row: dict[str, object]) -> tuple[object, ...]:
        mappings = {
            "switch_sequence": ("sequence", "radio", "switch_time", "from_peer", "to_peer", "previous_start_time", "previous_end_time", "previous_duration_seconds", "new_segment_end_time", "new_duration_seconds", "from_mr_rssi", "to_mr_rssi"),
            "active_segments": ("segment_id", "radio", "active_peer", "start_time", "end_time", "duration_seconds", "sample_count", "avg_mr_rssi", "min_mr_rssi", "max_mr_rssi", "avg_peer_rssi", "avg_tx_busy", "avg_rx_busy", "source_files"),
            "flap_events": ("sequence", "radio", "flap_type", "start_time", "return_time", "peer_a", "peer_b", "window_seconds"),
            "link_establishment_order": ("sequence", "radio", "peer", "first_seen_time", "first_establish_time", "last_seen_time", "sample_count", "active_sample_count", "standby_sample_count", "max_duration_seconds"),
            "peer_lifecycle": ("radio", "peer", "first_seen_time", "last_seen_time", "first_active_time", "last_active_time", "active_segment_count", "active_sample_count", "standby_sample_count", "switch_in_count", "switch_out_count"),
            "active_anomalies": ("anomaly_type", "radio", "start_time", "end_time", "active_count", "active_peers", "sample_count"),
            "rssi_statistics": ("radio", "peer", "sample_count", "mr_rssi_avg", "mr_rssi_min", "mr_rssi_max", "peer_rssi_avg", "peer_rssi_min", "peer_rssi_max"),
            "channel_busy_statistics": ("radio", "peer", "sample_count", "local_tx_busy_avg", "local_tx_busy_max", "local_rx_busy_avg", "local_rx_busy_max", "peer_tx_busy_avg", "peer_rx_busy_avg"),
            "raw_events": ("event_time", "radio", "event_type", "from_peer_mac", "to_peer_mac", "observed_window_ms", "source_file", "source_line_number", "details_json"),
            "parse_issues": ("source_file", "line_number", "severity", "issue_type", "field_name", "message", "raw_line"),
        }
        return tuple(row.get(key, "") for key in mappings[attr_name])
