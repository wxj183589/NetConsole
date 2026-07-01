from __future__ import annotations

from datetime import datetime

from openpyxl import load_workbook

from netconsole.core.i18n import I18n
from netconsole.services.mesh_analysis_excel_report import EMPTY_PARSE_ISSUES_TEXT, MeshAnalysisExcelReportExporter, REPORT_FIELD_LABELS, SHEET_DEFINITIONS, translate_report_value
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
from netconsole.services.mesh_quality_analysis import (
    MeshQualityRules,
    analyze_anomaly_events,
    analyze_link_rebuilds,
    analyze_switch_events,
    build_active_segments as build_quality_active_segments,
    build_busy_analysis,
    build_sample_quality,
    normalize_samples,
    percentile,
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
        "source_line_number": 1,
        "raw_line": f"{sample_time} {state} {peer}",
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
    assert [cell.value for cell in workbook["切换事件分析"][1]][:4] == [
        REPORT_FIELD_LABELS["sequence"],
        REPORT_FIELD_LABELS["radio"],
        REPORT_FIELD_LABELS["switch_time"],
        REPORT_FIELD_LABELS["from_peer"],
    ]
    assert workbook["解析问题"]["F2"].value == EMPTY_PARSE_ISSUES_TEXT


def test_i18n_report_keys_exist_and_mesh_page_has_generate_button(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from netconsole.core.paths import PathResolver
    from netconsole.ui.pages.mesh_log_analysis_page import MESH_ANALYSIS_REPORT_ENABLED, MeshLogAnalysisPage

    app = QApplication.instance() or QApplication([])
    assert app is not None
    assert I18n("zh_CN").t("mesh_report.generate_report") == "生成分析报告"
    assert I18n("en_US").t("mesh_report.generate_report") == "Generate Report"
    page = MeshLogAnalysisPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert MESH_ANALYSIS_REPORT_ENABLED
    assert page.generate_report_button is not None
    assert page.generate_report_button.text() == "生成 MR 原始 MESH 分析报告"


def test_report_worker_cancel_before_run_cleans_temp(tmp_path):
    output = tmp_path / "cancelled.xlsx"
    temp = output.with_name(output.stem + ".tmp.xlsx")
    temp.write_text("partial", encoding="utf-8")
    worker = MeshAnalysisReportWorker(tmp_path / "missing.sqlite", "MR", output, MeshReportOptions())
    worker.cancel()
    worker.run()
    assert not output.exists()
    assert not temp.exists()


def test_report_export_translates_internal_enum_values():
    assert translate_report_value("quality_level", "EXCELLENT") == "优秀"
    assert translate_report_value("switch_type", "LATE_SWITCH") == "切换滞后"
    assert translate_report_value("event_type", "NO_BACKUP") == "无可用备份"
    assert translate_report_value("rebuild_type", "DURATION_RESET") == "持续时间回退"
    assert translate_report_value("link_state", "ACTIVE") == "主链路"
    assert translate_report_value("data_source_type", "MR_RAW_MESH_LOG") == "MR原始MESH日志"
    assert translate_report_value("fping_loss_rate", None) == "N/A"
    assert translate_report_value("related_event_type", "SHORT_SEGMENT_SWITCH") == "短时切换"


def test_quality_sample_point_and_fping_na():
    rules = MeshQualityRules()
    rows = normalize_samples(
        [
            _row("2025-12-03 10:00:00", PEER_A, "ACTIVE", mr_rssi=42),
            _row("2025-12-03 10:00:00", PEER_B, "STANDBY", mr_rssi=35),
        ]
    )
    sample = build_sample_quality(rows, rules)[0]
    assert sample["quality_level"] == "EXCELLENT"
    assert sample["available_backup_count"] == 1
    assert rows[0]["fping_loss_rate"] is None


def test_quality_anomaly_event_merging_for_no_backup_weak_no_active_multi_active_and_busy():
    rules = MeshQualityRules(no_backup_min_seconds=1, weak_active_min_seconds=1, busy_warning_threshold=60, busy_bad_threshold=75)
    rows = normalize_samples(
        [
            _row("2025-12-03 10:00:00", PEER_A, "ACTIVE", mr_rssi=28),
            _row("2025-12-03 10:00:01", PEER_A, "ACTIVE", mr_rssi=27),
            _row("2025-12-03 10:00:02", PEER_A, "STANDBY"),
            _row("2025-12-03 10:00:03", PEER_A, "ACTIVE"),
            _row("2025-12-03 10:00:03", PEER_B, "ACTIVE"),
            {**_row("2025-12-03 10:00:04", PEER_A, "ACTIVE"), "local_tx_busy": 80, "local_rx_busy": 10},
        ]
    )
    samples = build_sample_quality(rows, rules)
    events = analyze_anomaly_events(samples, rows, rules)
    event_types = {event["event_type"] for event in events}
    assert {"NO_BACKUP", "WEAK_ACTIVE", "NO_ACTIVE", "MULTI_ACTIVE", "HIGH_BUSY"} <= event_types
    assert len([event for event in events if event["event_type"] == "NO_BACKUP"]) == 1


def test_quality_switch_late_weak_target_and_flap_detection():
    rules = MeshQualityRules(switch_late_window_seconds=5, switch_target_window_seconds=5, flap_window_seconds=30, short_active_segment_seconds=0)
    rows = normalize_samples(
        [
            _row("2025-12-03 10:00:00", PEER_A, "ACTIVE", mr_rssi=24),
            _row("2025-12-03 10:00:00", PEER_B, "STANDBY", mr_rssi=40),
            _row("2025-12-03 10:00:01", PEER_A, "ACTIVE", mr_rssi=23),
            _row("2025-12-03 10:00:01", PEER_B, "STANDBY", mr_rssi=41),
            _row("2025-12-03 10:00:02", PEER_B, "ACTIVE", mr_rssi=24),
            _row("2025-12-03 10:00:03", PEER_A, "ACTIVE", mr_rssi=41),
        ]
    )
    samples = build_sample_quality(rows, rules)
    segments = build_quality_active_segments(samples, rows, rules)
    switches = analyze_switch_events(segments, samples, rules)
    assert any(switch["switch_type"] == "FLAP_SWITCH" for switch in switches)
    late_rows = normalize_samples(
        [
            _row("2025-12-03 10:01:00", PEER_A, "ACTIVE", mr_rssi=24),
            _row("2025-12-03 10:01:00", PEER_B, "STANDBY", mr_rssi=40),
            _row("2025-12-03 10:01:01", PEER_A, "ACTIVE", mr_rssi=23),
            _row("2025-12-03 10:01:01", PEER_B, "STANDBY", mr_rssi=41),
            _row("2025-12-03 10:01:02", PEER_B, "ACTIVE", mr_rssi=24),
        ]
    )
    late_samples = build_sample_quality(late_rows, rules)
    late_segments = build_quality_active_segments(late_samples, late_rows, rules)
    late_switches = analyze_switch_events(late_segments, late_samples, rules)
    assert late_switches[0]["switch_type"] in {"LATE_SWITCH", "WEAK_TARGET_SWITCH"}


def test_quality_rebuild_busy_and_percentiles():
    assert percentile([10, 20, 30, 40], 0.1) == 13
    assert percentile([10, 20, 30, 40], 0.9) == 37
    rows = normalize_samples(
        [
            {**_row("2025-12-03 10:00:00", PEER_A, "ACTIVE"), "link_count": 1, "duration_seconds": 20, "establish_time": "2025-12-03 09:59:00", "local_tx_busy": 10, "local_rx_busy": 10},
            {**_row("2025-12-03 10:00:01", PEER_A, "ACTIVE"), "link_count": 2, "duration_seconds": 21, "establish_time": "2025-12-03 09:59:00", "local_tx_busy": 80, "local_rx_busy": 20},
            {**_row("2025-12-03 10:00:02", PEER_A, "ACTIVE"), "link_count": 2, "duration_seconds": 1, "establish_time": "2025-12-03 10:00:02", "local_tx_busy": 30, "local_rx_busy": 82},
        ]
    )
    rebuilds = analyze_link_rebuilds(rows)
    assert {event["rebuild_type"] for event in rebuilds} >= {"LINKCNT_INCREASE", "DURATION_RESET"}
    busy = build_busy_analysis(rows, MeshQualityRules(busy_warning_threshold=60, busy_bad_threshold=75))[0]
    assert busy["busy_level"] == "BAD"
