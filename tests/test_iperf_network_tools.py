from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTabWidget

from netconsole.core.paths import PathResolver
from netconsole.core.i18n import I18n
from netconsole.services.network_tools.iperf_parser import aggregate_iperf_for_segment, parse_iperf_line
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfResultStore, build_iperf_client_args, normalize_bandwidth_text
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.ui.pages.iperf_bandwidth_page import IperfBandwidthPage


def _qt_app():
    return QApplication.instance() or QApplication([])


class FakeWheelEvent:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True


def test_iperf_tool_discovery_from_project_tools(tmp_path: Path) -> None:
    exe = tmp_path / "tools" / "iperf" / "iperf3.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")
    assert find_iperf_tool(PathResolver(tmp_path)) == exe.resolve()


def test_iperf_version_parses_3_20_with_extra_output(tmp_path: Path) -> None:
    exe = tmp_path / "iperf3.exe"
    exe.write_text("fake", encoding="utf-8")

    def runner(*args, **kwargs):
        class Result:
            stdout = "iperf 3.20 (cJSON 1.7.15)\nCYGWIN_NT-10.0-26200\n"
            stderr = "Optional features available: POSIX threads"
            returncode = 0

        return Result()

    status = detect_iperf_version(exe, runner=runner)
    assert status.found is True
    assert status.version == "3.20"


def test_tcp_auto_max_bandwidth_omits_bandwidth_arg(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth=None))
    assert "-b" not in args


def test_tcp_target_bandwidth_includes_bandwidth_arg(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth="100M"))
    assert args[args.index("-b") + 1] == "100M"


def test_target_bandwidth_value_and_unit_formats_arg(tmp_path: Path) -> None:
    assert normalize_bandwidth_text("100", "M") == "100M"
    assert normalize_bandwidth_text("1", "G") == "1G"
    assert normalize_bandwidth_text("12.5", "M") == "12.5M"
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth=normalize_bandwidth_text("1", "G")))
    assert args[args.index("-b") + 1] == "1G"


def test_invalid_target_bandwidth_is_rejected() -> None:
    for value in ("-1", "abc", "1x", ""):
        if value == "":
            assert normalize_bandwidth_text(value, "M") is None
        else:
            import pytest

            with pytest.raises(ValueError):
                normalize_bandwidth_text(value, "M")


def test_udp_defaults_to_10m_bandwidth(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="UDP", target_bandwidth=None))
    assert "-u" in args
    assert args[args.index("-b") + 1] == "10M"


def test_iperf_direction_args(tmp_path: Path) -> None:
    upload = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="upload"))
    download = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="download"))
    bidirectional = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="bidirectional"))
    assert "-R" not in upload and "--bidir" not in upload
    assert "-R" in download
    assert "--bidir" in bidirectional


def test_follow_collection_manual_duration_uses_long_duration(tmp_path: Path) -> None:
    config = IperfClientConfig("10.0.0.1", duration_seconds=86400, follow_collection=True)
    args = build_iperf_client_args(tmp_path / "iperf3.exe", config)
    assert args[args.index("-t") + 1] == "86400"


def test_iperf_output_parser_extracts_interval_fields() -> None:
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes")
    assert row is not None
    assert row["interval_start_sec"] == 0
    assert row["interval_end_sec"] == 1
    assert row["bitrate_mbps"] == 88.1
    assert row["retransmits"] == 0


def test_iperf_interval_center_time_aligns_to_started_at() -> None:
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes", datetime(2025, 1, 1, 10, 0, 0))
    assert row is not None
    assert row["interval_center_time"] == "2025-01-01 10:00:00.500"


def test_iperf_active_segment_aggregation() -> None:
    start = datetime(2025, 1, 1, 10, 0, 0)
    rows = []
    for index in range(10):
        row = parse_iperf_line(f"[  5]   {index:.2f}-{index + 1:.2f}   sec  1.0 MBytes  {10 + index}.0 Mbits/sec  {index}   256 KBytes", start)
        assert row is not None
        rows.append(row)
    result = aggregate_iperf_for_segment(rows, start, start + timedelta(seconds=10))
    assert result["sample_count"] == 10
    assert result["avg_mbps"] == 14.5
    assert result["max_mbps"] == 19.0
    assert result["retransmits"] == 45


def test_iperf_result_store_creates_required_tables(tmp_path: Path) -> None:
    store = IperfResultStore(tmp_path / "iperf_results.sqlite")
    store.start_run("run1", mode="client", command=["iperf3"], log_file=tmp_path / "raw.log", started_at=datetime(2025, 1, 1), device_id=7, config=IperfClientConfig("10.0.0.1"))
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes", datetime(2025, 1, 1))
    assert row is not None
    store.append_interval("run1", row)
    store.finish_run("run1", "DONE")
    with sqlite3.connect(tmp_path / "iperf_results.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM iperf_runs").fetchone()[0] == 1
        assert conn.execute("SELECT device_id FROM iperf_runs").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1


def test_network_tools_iperf_page_uses_bandwidth_value_and_unit(tmp_path: Path) -> None:
    _qt_app()
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert page.client_bandwidth_unit_combo.currentText() == "M"
    assert "auto maximum" in page.client_bandwidth_hint_label.text()
    page.client_bandwidth_edit.setText("50")
    page.client_bandwidth_unit_combo.setCurrentText("M")
    config = IperfClientConfig(
        "10.0.0.1",
        target_bandwidth=normalize_bandwidth_text(page.client_bandwidth_edit.text(), page.client_bandwidth_unit_combo.currentText()),
    )
    args = build_iperf_client_args(tmp_path / "iperf3.exe", config)
    assert args[args.index("-b") + 1] == "50M"


def test_iperf_page_shows_server_and_client_panels_together(tmp_path: Path) -> None:
    _qt_app()
    (tmp_path / "tools" / "iperf").mkdir(parents=True)
    (tmp_path / "tools" / "iperf" / "iperf3.exe").write_text("fake", encoding="utf-8")
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))

    assert page.splitter.count() == 2
    assert page.splitter.widget(0).title() == "Server"
    assert page.splitter.widget(1).title() == "Client"
    assert page.server_output.parentWidget() is not page.client_output.parentWidget()
    assert page.findChildren(QTabWidget) == []


def test_iperf_page_spinbox_wheel_does_not_change_value(tmp_path: Path) -> None:
    _qt_app()
    (tmp_path / "tools" / "iperf").mkdir(parents=True)
    (tmp_path / "tools" / "iperf" / "iperf3.exe").write_text("fake", encoding="utf-8")
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    event = FakeWheelEvent()
    page.server_port_spin.setValue(5201)
    page.server_port_spin.wheelEvent(event)
    assert page.server_port_spin.value() == 5201
    assert event.ignored is True


def test_iperf_page_combobox_wheel_does_not_change_value(tmp_path: Path) -> None:
    _qt_app()
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    event = FakeWheelEvent()
    page.client_protocol_combo.setCurrentText("TCP")
    page.client_protocol_combo.wheelEvent(event)
    assert page.client_protocol_combo.currentText() == "TCP"
    assert event.ignored is True


def test_iperf_server_initial_status_is_stopped(tmp_path: Path) -> None:
    _qt_app()
    (tmp_path / "tools" / "iperf").mkdir(parents=True)
    (tmp_path / "tools" / "iperf" / "iperf3.exe").write_text("fake", encoding="utf-8")
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert page.server_state == "STOPPED"
    assert "Stopped" in page.server_status_label.text()
    assert "#ef4444" in page.server_status_dot.styleSheet()
    assert page.server_start_button.isEnabled() is True
    assert page.server_stop_button.isEnabled() is False


def test_iperf_server_running_and_failed_status_buttons(tmp_path: Path) -> None:
    _qt_app()
    (tmp_path / "tools" / "iperf").mkdir(parents=True)
    (tmp_path / "tools" / "iperf" / "iperf3.exe").write_text("fake", encoding="utf-8")
    page = IperfBandwidthPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    page._set_server_state("RUNNING")
    assert "Running" in page.server_status_label.text()
    assert "#22c55e" in page.server_status_dot.styleSheet()
    assert page.server_start_button.isEnabled() is False
    assert page.server_stop_button.isEnabled() is True
    page._set_server_state("FAILED")
    assert "Failed" in page.server_status_label.text()
    assert "#ef4444" in page.server_status_dot.styleSheet()
    assert page.server_start_button.isEnabled() is True
    assert page.server_stop_button.isEnabled() is False
