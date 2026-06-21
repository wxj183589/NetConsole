from __future__ import annotations

from datetime import datetime

from openpyxl import load_workbook

from netconsole.core.i18n import I18n
from netconsole.services.mesh_analysis_excel_report import EMPTY_PARSE_ISSUES_TEXT, MeshAnalysisExcelReportExporter, SHEET_DEFINITIONS
from netconsole.services.mesh_analysis_report import (
    MeshAnalysisReportModel,
    MeshReportOptions,
    build_active_anomalies,
    build_active_segments,
    build_channel_busy_statistics,
    build_link_establishment_order,
    build_peer_lifecycle,
    build_rssi_statistics,
    build_switch_sequence,
    detect_flap_switches,
)
from netconsole.ui.mesh_log_workers import MeshAnalysisReportWorker


PEER_A = "30f5277a5a2f"
PEER_B = "30f5277a5a30"
PEER_C = "30f5277a5a31"


def _row(sample_time: str, peer: str, state: str = "ACTIVE", radio: int = 1, mr_rssi: int = 41, peer_rssi: int = 39) -> dict[str, object]:
    return {
        "sample_time": sample_time,
        "radio": radio,
        "link_state": state,
        "peer_mac_normalized": peer,
        "establish_time": "2025-12-03 09:59:00.000",
        "duration_seconds": 60,
        "mr_rssi": mr_rssi,
        "peer_rssi": peer_rssi,
        "local_tx_busy": 12,
        "local_rx_busy": 8,
        "peer_tx_busy": 6,
        "peer_rx_busy": 4,
        "local_rate_raw": 866,
        "archived_filename": "mesh.log",
    }


def test_active_segments_preserve_aba_runs_and_switch_sequence():
    rows = [
        _row("2025-12-03 10:00:00.000", PEER_A, mr_rssi=40),
        _row("2025-12-03 10:00:01.000", PEER_A, mr_rssi=42),
        _row("2025-12-03 10:00:02.000", PEER_B, mr_rssi=55),
        _row("2025-12-03 10:00:03.000", PEER_A, mr_rssi=41),
    ]
    segments = build_active_segments(rows)
    assert [segment["active_peer_mac"] for segment in segments] == [PEER_A, PEER_B, PEER_A]
    assert segments[0]["sample_count"] == 2
    switches = build_switch_sequence(segments)
    assert [(switch["from_peer_mac"], switch["to_peer_mac"]) for switch in switches] == [(PEER_A, PEER_B), (PEER_B, PEER_A)]
    assert switches[0]["from_mr_rssi"] == 41
    assert switches[0]["to_mr_rssi"] == 55


def test_flap_detects_aba_inside_window_and_ignores_non_flap():
    flap_segments = build_active_segments(
        [
            _row("2025-12-03 10:00:00.000", PEER_A),
            _row("2025-12-03 10:00:02.000", PEER_B),
            _row("2025-12-03 10:00:04.000", PEER_A),
        ]
    )
    assert detect_flap_switches(flap_segments, flap_window_seconds=5)[0]["flap_type"] == "A-B-A"
    non_flap_segments = build_active_segments(
        [
            _row("2025-12-03 10:00:00.000", PEER_A),
            _row("2025-12-03 10:00:02.000", PEER_B),
            _row("2025-12-03 10:00:04.000", PEER_C),
        ]
    )
    assert detect_flap_switches(non_flap_segments, flap_window_seconds=5) == []


def test_link_establishment_order_lifecycle_and_anomalies():
    rows = [
        _row("2025-12-03 10:00:00.000", PEER_A, "STANDBY"),
        _row("2025-12-03 10:00:01.000", PEER_A, "ACTIVE"),
        _row("2025-12-03 10:00:02.000", PEER_B, "ACTIVE"),
        _row("2025-12-03 10:00:03.000", PEER_A, "ACTIVE"),
        _row("2025-12-03 10:00:04.000", PEER_B, "STANDBY"),
    ]
    segments = build_active_segments(rows)
    switches = build_switch_sequence(segments)
    order = build_link_establishment_order(rows)
    assert [item["peer_mac"] for item in order] == [PEER_A, PEER_B]
    lifecycle = build_peer_lifecycle(rows, segments, switches)
    peer_a = next(item for item in lifecycle if item["peer_mac"] == PEER_A)
    assert peer_a["standby_sample_count"] == 1
    assert peer_a["active_segment_count"] == 2

    anomalies = build_active_anomalies(
        [
            _row("2025-12-03 10:01:00.000", PEER_A, "STANDBY"),
            _row("2025-12-03 10:01:01.000", PEER_A, "ACTIVE"),
            _row("2025-12-03 10:01:01.000", PEER_B, "ACTIVE"),
        ]
    )
    assert [item["anomaly_type"] for item in anomalies] == ["NO_ACTIVE", "MULTI_ACTIVE"]


def test_rssi_and_channel_busy_statistics_keep_raw_positive_values():
    rows = [_row("2025-12-03 10:00:00.000", PEER_A, mr_rssi=43, peer_rssi=37), _row("2025-12-03 10:00:01.000", PEER_A, mr_rssi=45, peer_rssi=39)]
    rssi = build_rssi_statistics(rows)[0]
    busy = build_channel_busy_statistics(rows)[0]
    assert rssi["mr_rssi_avg"] == 44
    assert rssi["mr_rssi_min"] == 43
    assert rssi["peer_rssi_max"] == 39
    assert busy["local_tx_busy_avg"] == 12


def test_excel_report_contains_required_sheets_headers_and_empty_parse_issue_text(tmp_path):
    model = MeshAnalysisReportModel(
        mr_name="14CW-01",
        report_name="14CW-01",
        generated_at=datetime.now(),
        options=MeshReportOptions(),
        overview={"mr_name": "14CW-01"},
        active_segments=build_active_segments([_row("2025-12-03 10:00:00.000", PEER_A)]),
    )
    path = MeshAnalysisExcelReportExporter().export(model, tmp_path / "report.xlsx")
    workbook = load_workbook(path)
    assert workbook.sheetnames == [definition[0] for definition in SHEET_DEFINITIONS]
    assert [cell.value for cell in workbook["主链路切换顺序"][1]][:4] == ["序号", "Radio", "切换时间", "原PeerMac"]
    assert workbook["解析问题"]["A2"].value == EMPTY_PARSE_ISSUES_TEXT


def test_i18n_report_keys_exist_and_mesh_page_has_generate_button(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from netconsole.core.paths import PathResolver
    from netconsole.ui.pages.mesh_log_analysis_page import MeshLogAnalysisPage

    app = QApplication.instance() or QApplication([])
    assert app is not None
    assert I18n("zh_CN").t("mesh_report.generate_report") == "生成分析报告"
    assert I18n("en_US").t("mesh_report.generate_report") == "Generate Report"
    page = MeshLogAnalysisPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert page.generate_report_button.text() == "Generate Report"


def test_report_worker_cancel_before_run_cleans_temp(tmp_path):
    output = tmp_path / "cancelled.xlsx"
    temp = output.with_name(output.stem + ".tmp.xlsx")
    temp.write_text("partial", encoding="utf-8")
    worker = MeshAnalysisReportWorker(tmp_path / "missing.sqlite", "MR", output, MeshReportOptions())
    worker.cancel()
    worker.run()
    assert not output.exists()
    assert not temp.exists()
