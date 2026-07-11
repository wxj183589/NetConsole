from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractItemView, QAbstractSpinBox, QApplication, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QMessageBox, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import (
    CONFIG_COLLECT_COMMANDS,
    FpingConfig,
    INIT_COMMANDS,
    IperfTrafficConfig,
    TERMINAL_MONITOR_INIT_COMMANDS,
    STATE_ABORTED,
    STATE_COLLECTING,
    STATE_CONNECTING,
    STATE_RECONNECTING,
    STATE_STOPPING,
    STATE_STOPPED,
    TASK_CONFIG_COLLECT,
    TASK_CHANNEL_BUSY,
    TASK_AP_RADIO_STATISTICS,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    TASK_WIRELESS_STATUS,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrSnapshot,
    repeat_command_group,
)
from netconsole.core.ping.fping_v5_runner import build_fping_v5_args
from netconsole.services.fping_legacy_parser import (
    aggregate_ping_for_active_segment,
    parse_fping_lines,
    parse_fping_summary,
)
from netconsole.services.fping_v5 import detect_fping_version, find_fping_tool
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.services.network_tools.iperf_runner import FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_tasks import run_background_task
from netconsole.services.online_mr_collector import NetmikoShellConnection, RepeatSshSession
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.network_tools.iperf_parser import parse_iperf_lines, read_iperf_text
from netconsole.services.online_mr_parser import parse_ap_radio_statistics_text, parse_channel_busy_text, parse_mesh_link_text, parse_switch_history_text
from netconsole.services.online_mr_analysis_report_exporter import OnlineMrAnalysisReportExporter
from netconsole.services.online_mr_chart_builder import OnlineMrChartBuilder
from netconsole.services.online_mr_terminal_log_parser import parse_active_link_endpoint, parse_active_link_switch_logs, switch_reason_text
from netconsole.services.online_mr.core.event_model import EVENT_BUSY_SAMPLE, EVENT_FPING_V5_SAMPLE, EVENT_LINK_SWITCH, EVENT_MESH_SAMPLE, OnlineMrEvent
from netconsole.services.online_mr.core.realtime_model import RealtimeAggregator, build_realtime_state
from netconsole.services.online_mr.core.realtime_cache import OnlineMrRawEvent, OnlineMrRealtimeCache
from netconsole.services.online_mr.core.realtime_parser import OnlineMrRealtimeParser
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.services.online_mr.collection_models import collection_config_from_payload, collection_config_to_payload
from netconsole.ui.pages.online_mr_collection_page import (
    ONLINE_MR_LEFT_PANEL_MIN_WIDTH,
    ONLINE_MR_DEVICE_DISPLAY_LIMIT,
    ONLINE_MR_PAGE_MIN_WIDTH,
    ONLINE_MR_RIGHT_PANEL_MIN_WIDTH,
    ONLINE_MR_WORK_PANEL_MIN_WIDTH,
    OnlineMrCollectionPage,
    SUMMARY_COL_ACTIVE_PEER,
    SUMMARY_COL_BUSY_TIME,
    SUMMARY_COL_BUSY_TOTAL,
    SUMMARY_COL_BUSY_TX,
    SUMMARY_COL_BUSY_RX,
    SUMMARY_COL_COLLECTED,
    SUMMARY_COL_DEVICE_ID,
    SUMMARY_COL_FAILED,
    SUMMARY_COL_IPERF_MBPS,
    SUMMARY_COL_IPERF_RETRANS,
    SUMMARY_COL_LAST_COLLECTION,
    SUMMARY_COL_MR_RSSI,
    SUMMARY_COL_PEER_MAC,
    SUMMARY_COL_PEER_SECTION,
    SUMMARY_COL_PEER_SITE,
    SUMMARY_COL_PING_LOSS,
    SUMMARY_COL_PING_LATENCY,
    SUMMARY_COL_RECONNECTS,
    SUMMARY_COL_SESSION,
    SUMMARY_COL_STATUS,
    is_fat_ap_device,
    natural_device_sort_key,
    safe_device_folder_name,
)
from netconsole.ui.widgets.table_check_delegate import CheckBoxOnlyDelegate
from netconsole.ui.table_utils import apply_analysis_table_style, auto_fit_table_columns, make_table_item
from netconsole.ui.widgets.online_mr_analysis_chart_widget import ANOMALY_MARKER_STYLE, SWITCH_MARKER_STYLE
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr_collector import (
    NORMAL_DISPLAY_PREPARE_COMMANDS,
    PROBE_STREAM_PREPARE_COMMANDS,
    STREAM_PREPARE_COMMANDS,
    OnlineMrCollectionManager,
    OnlineMrCollector,
    stream_prepare_commands,
)
from netconsole.services.online_mr_session_store import COLLECTOR_OUTPUT_RAW_FILE, DEVICE_TERMINAL_MONITOR_RAW_FILE, OnlineMrSessionStore
from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION, OnlineMrDiagnosisParser, TimeSyncSample, estimate_device_time_from_local
from netconsole.ui.pages.online_mr_collection_page import OnlineMrUiThrottle
from netconsole.services.online_mr.workers.fping_v5_worker import FpingV5ProbeWorker
from netconsole.ui.online_mr_collector_worker import OnlineMrCollectorWorker


LINE_A = "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def _qt_app():
    return QApplication.instance() or QApplication([])


def _process_qt_until(predicate, *, timeout: float = 5.0) -> None:
    app = _qt_app()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for Qt background task")


class FakeConnection:
    def __init__(self, outputs: dict[str, str] | None = None, fail_on: set[str] | None = None) -> None:
        self.outputs = outputs or {}
        self.fail_on = fail_on or set()
        self.commands: list[str] = []
        self.closed = False

    def send_command(self, command: str, timeout: int) -> str:
        self.commands.append(command)
        if command in self.fail_on:
            self.closed = True
            raise RuntimeError("connection closed")
        return self.outputs.get(command, f"{command}\nOK")

    def close(self) -> None:
        self.closed = True


class FakeWheelEvent:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True

    def type(self):
        return QEvent.Wheel


class Factory:
    def __init__(self, connections: list[FakeConnection]) -> None:
        self.connections = connections
        self.created: list[FakeConnection] = []

    def __call__(self, config: OnlineMrConnectionConfig) -> FakeConnection:
        connection = self.connections.pop(0)
        self.created.append(connection)
        return connection


def _config(tmp_path: Path) -> tuple[PathResolver, OnlineMrConnectionConfig]:
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("MR-01")
    config = OnlineMrConnectionConfig(
        site="demo",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="FAT-AP-01",
        host="192.0.2.10",
        username="admin",
        password="secret",
        reconnect_interval=0,
    )
    return paths, config


def _collector(tmp_path: Path, connection: FakeConnection | None = None) -> tuple[OnlineMrCollector, FakeConnection]:
    paths, config = _config(tmp_path)
    connection = connection or FakeConnection({"display wlan mesh-link": LINE_A})
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=lambda _: connection, sleeper=lambda _: None)
    return collector, connection


def _online_page_with_devices(tmp_path: Path) -> tuple[OnlineMrCollectionPage, DeviceRepository, DeviceGroupRepository]:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device_repo = DeviceRepository(database)
    group_repo = DeviceGroupRepository(database, "demo")
    page = OnlineMrCollectionPage(device_repo, I18n("en_US"), "demo", paths)
    refresh_all = page.refresh_all

    def refresh_all_and_wait(*args, **kwargs):
        refresh_all(*args, **kwargs)
        _process_qt_until(lambda: not page._device_refresh_job_id)

    page.refresh_all = refresh_all_and_wait
    return page, device_repo, group_repo


def test_online_mr_device_table_caps_and_batches_large_filtered_list(tmp_path: Path) -> None:
    page, _device_repo, _group_repo = _online_page_with_devices(tmp_path)
    page.device_groups = {1: "车载-MR"}
    page.devices = [
        Device(id=index + 1, name=f"MR-{index:04d}", group_id=1, device_type="FAT-AP", primary_address=f"192.0.2.{index % 250 + 1}")
        for index in range(ONLINE_MR_DEVICE_DISPLAY_LIMIT + 5)
    ]
    page.selected_device_ids = {1}

    page._fill_devices()
    _process_qt_until(lambda: page.device_table.item(ONLINE_MR_DEVICE_DISPLAY_LIMIT - 1, 1) is not None)

    assert page.device_table.rowCount() == ONLINE_MR_DEVICE_DISPLAY_LIMIT
    assert "仅显示前" in page.device_table.toolTip()
    assert page.device_table.item(0, 0).checkState() == Qt.Checked
    page.device_search_input.blockSignals(True)
    page.device_search_input.setText("MR-0000")
    page.device_search_input.blockSignals(False)
    page._fill_devices()
    assert page.device_table.rowCount() == 1
    assert page.device_table.item(0, 0).checkState() == Qt.Checked


def test_online_mr_fping_parameter_layout_has_stable_widths(tmp_path: Path) -> None:
    page, _device_repo, _group_repo = _online_page_with_devices(tmp_path)

    assert page.right_control_scroll.minimumWidth() >= ONLINE_MR_RIGHT_PANEL_MIN_WIDTH
    assert page.control_panel.minimumWidth() >= ONLINE_MR_RIGHT_PANEL_MIN_WIDTH
    assert page.ping_box.minimumWidth() >= 360
    assert page.ping_box.minimumHeight() >= 430
    assert page.ping_box.maximumHeight() > 10000
    for spin in (page.fping_packet_size, page.fping_interval_ms, page.fping_loss_threshold_ms, page.fping_latency_warn_ms):
        assert spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert spin.minimumWidth() >= 110
    assert page.fping_loss_warn_edit.minimumWidth() >= 110
    assert page.fping_preset_combo.minimumWidth() >= 220
    assert not page.start_button.icon().isNull()
    assert not page.refresh_devices_button.icon().isNull()


def _create_onboard_device(repository: DeviceRepository, group_id: int, name: str, device_type: str = "FAT-AP") -> Device:
    return repository.create(
        Device(
            name=name,
            group_id=group_id,
            device_type=device_type,
            ip_address=f"192.0.2.{len(name) + 10}",
            ssh_enabled=1,
            ssh_port=22,
            ssh_username="admin",
            ssh_password="secret",
        )
    )


def test_concurrency_limit_rejects_third_collector() -> None:
    manager = OnlineMrCollectionManager(max_concurrent=2)
    manager.register("s1", object())
    manager.register("s2", object())
    assert manager.running_count() == 2
    with pytest.raises(RuntimeError, match="online_mr.max_two_running"):
        manager.register("s3", object())


def test_manager_allows_session_then_device_registration_for_second_collector() -> None:
    manager = OnlineMrCollectionManager(max_concurrent=2)
    first = object()
    second = object()
    manager.register("s1", first)
    manager.register_device(1, first)
    manager.register("s2", second)
    manager.register_device(2, second)
    assert manager.running_count() == 2
    with pytest.raises(RuntimeError, match="online_mr.max_two_running"):
        manager.register_device(3, object())


def test_init_command_order_is_exact(tmp_path: Path) -> None:
    collector, connection = _collector(tmp_path)
    collector.start()
    assert connection.commands[: len(INIT_COMMANDS)] == list(INIT_COMMANDS)


def test_init_status_written_without_init_raw_log(tmp_path: Path) -> None:
    collector, _connection = _collector(tmp_path)
    collector.start()

    session_dir = collector.session.session_dir
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert not (session_dir / "raw" / "init_raw.log").exists()
    assert meta["init"]["status"] == "success"
    assert meta["init"]["commands"] == list(INIT_COMMANDS)
    assert meta["init"]["started_at"]
    assert meta["init"]["ended_at"]
    raw = (session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE).read_text(encoding="utf-8")
    assert "===== INIT START" not in raw
    assert "screen-length disable -> OK" not in raw


def test_init_failure_records_meta_without_raw_echo(tmp_path: Path) -> None:
    collector, _connection = _collector(tmp_path, FakeConnection(fail_on={"terminal monitor"}))
    collector.start()

    session_dir = collector.session.session_dir
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert not (session_dir / "raw" / "init_raw.log").exists()
    assert meta["init"]["status"] == "failed"
    assert "terminal monitor" in meta["init"]["error_message"]


def test_stop_during_init_does_not_reenter_collecting_or_write_init_success(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)

    class StopDuringInitConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.collector: OnlineMrCollector | None = None

        def send_command(self, command: str, timeout: int) -> str:
            result = super().send_command(command, timeout)
            if command == INIT_COMMANDS[0] and self.collector is not None:
                self.collector.request_stop()
            return result

    connection = StopDuringInitConnection()
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=lambda _: connection)
    connection.collector = collector

    meta = collector.start()

    log_text = (collector.session.session_dir / "logs" / "collector.log").read_text(encoding="utf-8")
    assert meta.status == STATE_STOPPING
    assert collector.status == STATE_STOPPING
    assert "state=COLLECTING" not in log_text
    assert "init_status=success" not in log_text


def test_scheduler_intervals_with_fake_clock(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    config.intervals = OnlineMrIntervals(mesh_link=2, channel_busy=2, ap_radio_statistics=5, switch_history=300)
    connection = FakeConnection({"display wlan mesh-link": LINE_A})
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=lambda _: connection, sleeper=lambda _: None)
    collector.start()
    assert set(collector.run_due_tasks(0.0)) == {"mesh_link", "channel_busy", "ap_radio_statistics", "switch_history", "interface_rate"}
    assert collector.run_due_tasks(1.0) == []
    assert set(collector.run_due_tasks(2.0)) == {"mesh_link", "channel_busy", "interface_rate"}
    assert set(collector.run_due_tasks(4.0)) == {"mesh_link", "channel_busy", "interface_rate"}
    assert collector.run_due_tasks(5.0) == ["ap_radio_statistics"]
    assert "switch_history" in collector.run_due_tasks(300.0)


def test_auto_reconnect_reruns_init_and_continues(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    first = FakeConnection(fail_on={"display wlan mesh-link"})
    second = FakeConnection({"display wlan mesh-link": LINE_A})
    factory = Factory([first, second])
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=factory, sleeper=lambda _: None)
    collector.start()
    sample_id = collector.run_once(TASK_MESH_LINK)
    assert collector.status == STATE_COLLECTING
    assert collector.stats.reconnect_count == 1
    assert sample_id == -1
    assert second.commands[: len(INIT_COMMANDS)] == list(INIT_COMMANDS)
    assert any("reconnect_count=1" in line for line in (collector.session.session_dir / "raw" / "reconnect.log").read_text(encoding="utf-8").splitlines())


def test_raw_persistence_after_mesh_link(tmp_path: Path) -> None:
    collector, _ = _collector(tmp_path)
    collector.start()
    collector.run_once(TASK_MESH_LINK)
    raw_path = collector.session.session_dir / "raw" / "mesh_link_raw.log"
    raw = raw_path.read_text(encoding="utf-8")
    assert "display wlan mesh-link" in raw
    assert LINE_A in raw
    meta = json.loads((collector.session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta["stats"]["mesh_link_success"] == 1


def test_realtime_session_collects_config_inside_same_session(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    config.collect_config_on_start = True
    config_connection = FakeConnection({command: f"{command}\nOK" for command in CONFIG_COLLECT_COMMANDS})
    realtime_connection = FakeConnection()
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=Factory([config_connection, realtime_connection]))

    meta = collector.start()

    config_path = collector.session.session_dir / "outputs" / "current_configuration.txt"
    root_config_dir = collector.session.session_dir.parent.parent / "config"
    saved_meta = json.loads((collector.session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta.session_id == collector.session.meta.session_id
    assert config_path.exists()
    assert root_config_dir.exists() is False
    assert config_connection.commands == list(CONFIG_COLLECT_COMMANDS)
    assert saved_meta["session_type"] == "realtime"
    assert saved_meta["config_collect_enabled"] is True
    assert saved_meta["config_collect_status"] == "success"
    assert saved_meta["config_file_path"] == str(config_path)
    assert saved_meta["raw_log_path"] == str(collector.session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE)
    assert "display current-configuration" in config_path.read_text(encoding="utf-8")


def test_config_only_session_writes_config_and_meta(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    connection = FakeConnection({command: f"{command}\nOK" for command in CONFIG_COLLECT_COMMANDS})
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=lambda _: connection)

    meta = collector.collect_config_only()

    config_path = collector.session.session_dir / "outputs" / "current_configuration.txt"
    saved_meta = json.loads((collector.session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta.session_type == "config_only"
    assert saved_meta["session_type"] == "config_only"
    assert saved_meta["config_collect_status"] == "success"
    assert saved_meta["config_file_path"] == str(config_path)
    assert saved_meta["raw_log_path"] == str(collector.session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE)
    assert saved_meta["ended_at"]
    assert connection.commands == list(CONFIG_COLLECT_COMMANDS)


def test_config_collect_failure_keeps_session_meta(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    config.collect_config_on_start = True
    collector = OnlineMrCollector(
        config,
        OnlineMrSessionStore(paths),
        connection_factory=Factory([FakeConnection(fail_on={"display current-configuration"}), FakeConnection()]),
    )

    collector.start()

    saved_meta = json.loads((collector.session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert saved_meta["config_collect_status"] == "failed"
    assert saved_meta["config_error"]
    assert collector.status == STATE_COLLECTING


def _prepare_parsed_channel_busy_session(tmp_path: Path, count: int = 3):
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        for index in range(count):
            conn.execute(
                """
                INSERT INTO channel_busy_records (
                    session_id, device_time, device_clock, time_source, radio, ctl_channel, bandwidth,
                    record_interval, row_index, ctl_busy, tx_busy, rx_busy,
                    raw_file, raw_line_start, raw_line_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.meta.session_id,
                    f"2026-07-03 19:00:0{index}.000",
                    None,
                    "device_record",
                    1,
                    None,
                    None,
                    None,
                    1,
                    7 + index,
                    4 + index,
                    3 + index,
                    "raw/channel_busy_raw.log",
                    index,
                    index + 1,
                ),
            )
        conn.execute(
            """
            INSERT INTO active_segments (
                session_id, radio, active_peer_mac, start_time, end_time, sample_count,
                avg_mr_rssi, min_mr_rssi, max_mr_rssi, event_type, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.meta.session_id,
                1,
                "1111-2222-3333",
                "2026-07-03 19:00:00.000",
                "2026-07-03 19:01:00.000",
                count,
                35,
                30,
                40,
                "NORMAL",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO online_parse_metadata (
                session_id, parsed_at, parser_version, raw_fingerprint, row_counts, status, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.meta.session_id,
                "2026-07-03 19:02:00.000",
                PARSER_VERSION,
                parser.raw_fingerprint(),
                json.dumps({"channel_samples": count, "active_segments": 1}),
                "OK",
                "",
            ),
        )
    return session, config


def _insert_main_link_sample(
    conn: sqlite3.Connection,
    session_id: str,
    collected_at: str,
    *,
    radio: int = 1,
    link_state: str = "ACTIVE",
    peer_mac: str = "bc5a-3457-cbef",
    peer_name: str | None = None,
    resolved_peer_name: str | None = None,
    rssi: int = -36,
    station: str = "",
    section: str = "",
    online_time: str = "00h 00m 01s",
) -> None:
    _ensure_test_new_parsed_tables(conn)
    conn.execute(
        """
        INSERT INTO main_link_samples (
            session_id, collector_time, device_time, device_clock, time_source, radio, link_state,
            peer_name, peer_mac, peer_mac_normalized, resolved_peer_name, mr_rssi,
            bssid, mesh_interface, belong_station, belong_section, belong_type,
            belonging_source, online_time, raw_file, raw_line_start, raw_line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            collected_at,
            collected_at,
            None,
            "collector",
            radio,
            link_state,
            peer_name if peer_name is not None else peer_mac,
            peer_mac,
            peer_mac.replace("-", ""),
            resolved_peer_name if resolved_peer_name is not None else peer_name if peer_name is not None else peer_mac,
            rssi,
            "",
            "",
            station,
            section,
            "unknown",
            "",
            online_time,
            "raw/mesh_link_raw.log",
            0,
            1,
        ),
    )


def _insert_channel_busy_record(
    conn: sqlite3.Connection,
    session_id: str,
    collected_at: str,
    *,
    radio: int = 1,
    ctl_busy: int = 7,
    tx_busy: int = 4,
    rx_busy: int = 3,
) -> None:
    _ensure_test_new_parsed_tables(conn)
    conn.execute(
        """
        INSERT INTO channel_busy_records (
            session_id, device_time, time_source, radio,
            row_index, ctl_busy, tx_busy, rx_busy, raw_file, raw_line_start, raw_line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, collected_at, "device_record_time", radio, 1, ctl_busy, tx_busy, rx_busy, "raw/channel_busy_raw.log", 0, 1),
    )


def _insert_fping_sample(
    conn: sqlite3.Connection,
    session_id: str,
    collected_at: str,
    *,
    target_ip: str = "127.0.0.1",
    success: int = 1,
    latency_ms: float | None = 2.5,
) -> None:
    _ensure_test_new_parsed_tables(conn)
    conn.execute(
        """
        INSERT INTO fping_samples (
            session_id, collector_time, local_time, device_aligned_time, clock_offset_ms,
            offset_source, time_source, target_ip, target_name, seq,
            success, latency_ms, loss_percent, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, collected_at, collected_at, collected_at, 0.0, "nearest_sample", "local_tool", target_ip, "", 1, success, latency_ms, 0 if success else 100, "OK" if success else "TIMEOUT"),
    )
    conn.execute(
        """
        INSERT INTO fping_1s_summary (
            session_id, bucket_time, local_bucket_time, device_bucket_time, clock_offset_ms,
            target_ip, target_name, sent, received, lost, loss_percent,
            avg_latency_ms, min_latency_ms, max_latency_ms, jitter_ms, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            collected_at[:19],
            collected_at[:19],
            collected_at[:19],
            0.0,
            target_ip,
            "",
            1,
            success,
            1 - success,
            0 if success else 100,
            latency_ms if success else None,
            latency_ms if success else None,
            latency_ms if success else None,
            0 if success else None,
            "OK" if success else "LOSS",
        ),
    )


def _insert_interface_rate_sample(
    conn: sqlite3.Connection,
    session_id: str,
    collected_at: str,
    *,
    direction: str = "inbound",
    interface_name: str = "GE1/0/1",
    total_pps: int = 100,
) -> None:
    _ensure_test_new_parsed_tables(conn)
    conn.execute(
        """
        INSERT INTO interface_rate_samples (
            session_id, device_time, device_clock, time_source, interface_name, interface_normalized,
            direction, total_pps, broadcast_pps, multicast_pps, usage_percent,
            raw_file, raw_line_start, raw_line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, collected_at, None, "device_clock", interface_name, interface_name, direction, total_pps, 0, 0, None, "raw/interface_rate_raw.log", 0, 1),
    )


def _insert_switch_realtime_event(
    conn: sqlite3.Connection,
    session_id: str,
    collected_at: str,
    *,
    device_name: str = "MR-01",
    old_peer_name: str = "AP-A",
    old_peer_mac: str = "1111-2222-3333",
    old_rssi: int = 30,
    old_station: str = "站点A",
    old_section: str = "",
    new_peer_name: str = "AP-B",
    new_peer_mac: str = "1111-2222-4444",
    new_rssi: int = 40,
    new_station: str = "站点B",
    new_section: str = "",
    peer_quantity: int = 2,
    link_quantity: int = 1,
    reason_code: int | None = 2,
    reason_text: str = "主动切换（未开启移动链路优化）",
) -> None:
    _ensure_test_new_parsed_tables(conn)
    conn.execute(
        """
        INSERT INTO switch_realtime_events (
            session_id, device_time, time_source, device_name,
            old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section,
            new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section,
            peer_quantity, link_quantity, switch_reason_code, switch_reason_text,
            raw_file, raw_line_start, raw_line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            collected_at,
            "device_event_time",
            device_name,
            old_peer_name,
            old_peer_mac,
            old_rssi,
            old_station,
            old_section,
            new_peer_name,
            new_peer_mac,
            new_rssi,
            new_station,
            new_section,
            peer_quantity,
            link_quantity,
            reason_code,
            reason_text,
            "raw/terminal_monitor_raw.log",
            0,
            1,
        ),
    )


def _ensure_test_new_parsed_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS main_link_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, collector_time TEXT, device_time TEXT, device_clock TEXT, time_source TEXT,
            radio INTEGER, link_state TEXT, peer_name TEXT, peer_mac TEXT,
            peer_mac_normalized TEXT, resolved_peer_name TEXT, mr_rssi INTEGER,
            bssid TEXT, mesh_interface TEXT, belong_station TEXT, belong_section TEXT,
            belong_type TEXT, belonging_source TEXT, online_time TEXT,
            raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
        );
        CREATE TABLE IF NOT EXISTS channel_busy_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, device_time TEXT, device_clock TEXT, time_source TEXT,
            radio INTEGER, ctl_channel INTEGER, bandwidth INTEGER, record_interval INTEGER,
            row_index INTEGER, ctl_busy INTEGER, tx_busy INTEGER, rx_busy INTEGER,
            raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
        );
        CREATE TABLE IF NOT EXISTS fping_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, collector_time TEXT, local_time TEXT, device_aligned_time TEXT,
            clock_offset_ms REAL, offset_source TEXT, time_source TEXT, target_ip TEXT,
            target_name TEXT, seq INTEGER, success INTEGER, latency_ms REAL,
            loss_percent REAL, status TEXT
        );
        CREATE TABLE IF NOT EXISTS fping_1s_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, bucket_time TEXT, local_bucket_time TEXT, device_bucket_time TEXT,
            clock_offset_ms REAL, target_ip TEXT, target_name TEXT,
            sent INTEGER, received INTEGER, lost INTEGER, loss_percent REAL,
            avg_latency_ms REAL, min_latency_ms REAL, max_latency_ms REAL,
            jitter_ms REAL, status TEXT
        );
        CREATE TABLE IF NOT EXISTS time_sync_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, collector_time TEXT NOT NULL, device_time TEXT NOT NULL,
            offset_ms REAL NOT NULL, source TEXT, raw_file TEXT,
            raw_line_start INTEGER, raw_line_end INTEGER
        );
        CREATE TABLE IF NOT EXISTS interface_rate_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, device_time TEXT, device_clock TEXT, time_source TEXT,
            interface_name TEXT, interface_normalized TEXT, direction TEXT, total_pps REAL,
            broadcast_pps REAL, multicast_pps REAL, usage_percent REAL, raw_file TEXT,
            raw_line_start INTEGER, raw_line_end INTEGER
        );
        CREATE TABLE IF NOT EXISTS switch_realtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, device_time TEXT, time_source TEXT,
            device_name TEXT, old_peer_name TEXT, old_peer_mac TEXT, old_rssi INTEGER,
            old_belong_station TEXT, old_belong_section TEXT, new_peer_name TEXT,
            new_peer_mac TEXT, new_rssi INTEGER, new_belong_station TEXT,
            new_belong_section TEXT, peer_quantity INTEGER, link_quantity INTEGER,
            switch_reason_code INTEGER, switch_reason_text TEXT, raw_file TEXT,
            raw_line_start INTEGER, raw_line_end INTEGER
        );
        """
    )


class _ShutdownWorker:
    def __init__(self) -> None:
        self.cancelled = False
        self.stopped = False

    def cancel(self) -> None:
        self.cancelled = True

    def stop(self) -> None:
        self.stopped = True


def test_raw_log_files_split_collector_output_from_terminal_monitor(tmp_path: Path) -> None:
    collector, _ = _collector(tmp_path)
    collector.start()
    collector.run_once(TASK_MESH_LINK)

    collector_raw = collector.session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE
    mesh_raw = collector.session.session_dir / "raw" / "mesh_link_raw.log"
    terminal_raw = collector.session.session_dir / "raw" / DEVICE_TERMINAL_MONITOR_RAW_FILE
    collector_text = collector_raw.read_text(encoding="utf-8")
    mesh_text = mesh_raw.read_text(encoding="utf-8")
    terminal_text = terminal_raw.read_text(encoding="utf-8")
    assert "display wlan mesh-link" not in collector_text
    assert LINE_A not in collector_text
    assert "display wlan mesh-link" in mesh_text
    assert LINE_A in mesh_text
    assert "[collector=repeat]" not in terminal_text
    assert "display current-configuration" not in terminal_text
    assert "display wlan mesh-link" not in terminal_text


def test_append_raw_does_not_mirror_to_collector_output_by_default(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)

    session.append_raw(TASK_CONFIG_COLLECT, "\n".join(CONFIG_COLLECT_COMMANDS), "display current-configuration\nversion 7.1.064\nlocal-user admin")

    collector_text = (session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE).read_text(encoding="utf-8")
    config_text = (session.session_dir / "raw" / "config_collect_raw.log").read_text(encoding="utf-8")
    assert "display current-configuration" in config_text
    assert "version 7.1.064" in config_text
    assert "local-user admin" in config_text
    assert "display current-configuration" not in collector_text
    assert "version 7.1.064" not in collector_text
    assert "local-user admin" not in collector_text


def test_raw_append_methods_write_separate_files(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)

    session.append_collector_output_raw("[collector=repeat] display wlan mesh-link\n")
    session.append_device_terminal_monitor_raw("%Jul  3 18:23:32:224 2026 MR SHELL/5/SHELL_LOGIN: admin logged in\n")

    collector_text = (session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE).read_text(encoding="utf-8")
    terminal_text = (session.session_dir / "raw" / DEVICE_TERMINAL_MONITOR_RAW_FILE).read_text(encoding="utf-8")
    assert "[collector=repeat]" in collector_text
    assert "SHELL_LOGIN" not in collector_text
    assert "SHELL_LOGIN" in terminal_text
    assert "[collector=repeat]" not in terminal_text


def test_realtime_cache_tracks_latest_snapshot_without_file_polling(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    cache = OnlineMrRealtimeCache()
    collector = OnlineMrCollector(
        config,
        OnlineMrSessionStore(paths),
        connection_factory=lambda _: FakeConnection({"display wlan mesh-link": LINE_A}),
        realtime_cache=cache,
    )
    collector.start()
    collector.run_once(TASK_MESH_LINK)

    snapshot = cache.get_latest_snapshot(1)
    assert snapshot is not None
    assert snapshot.active_peer == "30f5-277a-5a2f"
    assert cache.get_session_realtime_table(snapshot.session_id) is snapshot

    cache.close_session(snapshot.session_id)

    assert cache.get_latest_snapshot(1) is None
    assert cache.get_latest_snapshot(1, site_id="demo") is None


def test_realtime_cache_clear_device_latest_removes_old_snapshot() -> None:
    cache = OnlineMrRealtimeCache()
    snapshot = OnlineMrSnapshot(session_id="old-session", status=STATE_STOPPED, device_id=7)
    cache.register_session(site_id="demo", session_id=snapshot.session_id, device_id=7, snapshot=snapshot)

    cache.clear_device_latest(site_id="demo", device_id=7)

    assert cache.get_latest_snapshot(7, site_id="demo") is None
    assert cache.get_latest_snapshot(7) is None


def test_realtime_parser_parses_raw_cache_event_without_file_polling() -> None:
    parser = OnlineMrRealtimeParser()
    event = OnlineMrRawEvent(
        timestamp=datetime.now(),
        session_id="session-1",
        device_id=1,
        source="ssh-repeat",
        task_type=TASK_MESH_LINK,
        raw=LINE_A,
    )

    parsed = parser.parse_raw_event(event)

    assert parsed is not None
    assert parsed.module == "mesh"
    assert parsed.payload["peer_mac"] == "30f5-277a-5a2f"
    assert parsed.payload["link_state"] == "ACTIVE"


def test_collector_raw_tail_uses_prefix_time_and_parser_line() -> None:
    raw_line = f"2026-07-07 03:05:11.465 [collector=repeat] RX {LINE_A}"

    timestamp, parser_line = OnlineMrCollectorWorker._split_collector_raw_line(raw_line)
    parsed = OnlineMrRealtimeParser().parse_raw_event(
        OnlineMrEvent(
            timestamp=timestamp,
            session_id="session-1",
            device_id=1,
            source="ssh_raw_tail",
            module="mesh",
            event_type=EVENT_MESH_SAMPLE,
            payload={"task_type": TASK_MESH_LINK, "line": parser_line, "raw_line": raw_line},
            raw=raw_line,
        )
    )

    assert timestamp == datetime(2026, 7, 7, 3, 5, 11, 465000)
    assert parser_line == LINE_A
    assert parsed is not None
    assert parsed.payload["peer_mac"] == "30f5-277a-5a2f"
    assert parsed.raw == raw_line


def test_repeat_stream_invokes_callback_before_archival(tmp_path: Path) -> None:
    stop_event = Event()
    raw_path = tmp_path / "raw" / "mesh_link_raw.log"
    seen: list[str] = []

    class FakeInteractiveConnection:
        def __init__(self) -> None:
            self.read_count = 0
            self.writes: list[str] = []

        def write_channel(self, text: str) -> None:
            self.writes.append(text)

        def read_channel(self) -> str:
            self.read_count += 1
            if self.read_count == 1:
                return f"{LINE_A}\n"
            stop_event.set()
            return ""

        def disconnect(self) -> None:
            pass

    connection = object.__new__(NetmikoShellConnection)
    connection.connection = FakeInteractiveConnection()
    connection._tunnel_session = None

    def callback(_stamp: datetime, line: str) -> None:
        seen.append(line)
        stop_event.set()

    connection.run_repeat_stream(
        ("display wlan mesh-link",),
        raw_path,
        stop_event,
        timeout=1,
        line_callback=callback,
    )

    assert seen == [LINE_A]
    text = raw_path.read_text(encoding="utf-8")
    assert LINE_A in text
    assert "display wlan mesh-link" in text
    assert "\x03" in "".join(connection.connection.writes)


def test_terminal_monitor_stream_uses_dedicated_init_commands() -> None:
    stop_event = Event()
    seen: list[str] = []

    class FakeInteractiveConnection:
        def __init__(self) -> None:
            self.read_count = 0
            self.writes: list[str] = []

        def write_channel(self, text: str) -> None:
            self.writes.append(text)

        def read_channel(self) -> str:
            self.read_count += 1
            if self.read_count == 1:
                return "%Jul  3 18:23:32:224 2026 MR SHELL/5/SHELL_LOGIN: admin logged in\n"
            stop_event.set()
            return ""

        def disconnect(self) -> None:
            pass

    connection = object.__new__(NetmikoShellConnection)
    connection.connection = FakeInteractiveConnection()
    connection._tunnel_session = None

    connection.run_terminal_monitor_stream(
        TERMINAL_MONITOR_INIT_COMMANDS,
        stop_event,
        timeout=1,
        line_callback=seen.append,
    )

    assert connection.connection.writes == [f"{command}\n" for command in TERMINAL_MONITOR_INIT_COMMANDS]
    assert "SHELL_LOGIN" in "".join(seen)
    assert "display wlan mesh-link" not in "".join(connection.connection.writes)


def test_repeat_stream_uses_minimal_prepare_and_does_not_write_init_status(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)

    class FakeRepeatConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.repeat_commands: tuple[str, ...] = ()

        def run_repeat_stream(self, commands, raw_path, stop_event, timeout: int, line_callback=None) -> None:
            self.repeat_commands = tuple(commands)
            stamp = datetime.now()
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(f"{stamp.isoformat(sep=' ', timespec='milliseconds')} [collector=repeat] START commands:\n" + "\n".join(commands) + f"\n{LINE_A}\n", encoding="utf-8")
            if line_callback is not None:
                line_callback(stamp, LINE_A)
            stop_event.set()

    main_connection = FakeConnection()
    repeat_connection = FakeRepeatConnection()
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=Factory([main_connection, repeat_connection]))

    collector.start()
    collector._start_repeat_thread(TASK_MESH_LINK)
    for thread in list(collector._stream_threads):
        thread.join(timeout=1)

    log_text = (collector.session.session_dir / "logs" / "collector.log").read_text(encoding="utf-8")
    raw_text = (collector.session.session_dir / "raw" / "mesh_link_raw.log").read_text(encoding="utf-8")
    assert log_text.count("init_status=success") == 1
    assert repeat_connection.commands == list(NORMAL_DISPLAY_PREPARE_COMMANDS)
    assert stream_prepare_commands(TASK_MESH_LINK) == STREAM_PREPARE_COMMANDS
    assert "terminal logging level 7" not in repeat_connection.commands
    assert "system-view" not in repeat_connection.commands
    assert "probe" not in repeat_connection.commands
    assert repeat_connection.repeat_commands == repeat_command_group(TASK_MESH_LINK, interval=config.intervals.mesh_link)
    assert LINE_A in raw_text


@pytest.mark.parametrize(
    ("task_type", "expected_command", "raw_name"),
    [
        (TASK_CHANNEL_BUSY, "display ar5drv 1 channelbusy", "channel_busy_raw.log"),
        (TASK_AP_RADIO_STATISTICS, "display ar5drv 1 statistics", "ap_radio_statistics_raw.log"),
        (TASK_WIRELESS_STATUS, "display ar5drv 1 client all rssi", "wireless_status_raw.log"),
    ],
)
def test_ar5drv_repeat_stream_enters_probe_without_rewriting_init_status(
    tmp_path: Path,
    task_type: str,
    expected_command: str,
    raw_name: str,
) -> None:
    paths, config = _config(tmp_path)

    class FakeRepeatConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.repeat_commands: tuple[str, ...] = ()

        def run_repeat_stream(self, commands, raw_path, stop_event, timeout: int, line_callback=None) -> None:
            self.repeat_commands = tuple(commands)
            stamp = datetime.now()
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                f"{stamp.isoformat(sep=' ', timespec='milliseconds')} [collector=repeat] START commands:\n"
                + "\n".join(commands)
                + f"\n{expected_command}\nOK\n",
                encoding="utf-8",
            )
            if line_callback is not None:
                line_callback(stamp, expected_command)
            stop_event.set()

    main_connection = FakeConnection()
    repeat_connection = FakeRepeatConnection()
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=Factory([main_connection, repeat_connection]))

    collector.start()
    collector._start_repeat_thread(task_type)
    for thread in list(collector._stream_threads):
        thread.join(timeout=1)

    log_text = (collector.session.session_dir / "logs" / "collector.log").read_text(encoding="utf-8")
    raw_text = (collector.session.session_dir / "raw" / raw_name).read_text(encoding="utf-8")
    assert log_text.count("init_status=success") == 1
    assert f"collector={task_type} prepare_status=success" in log_text
    assert repeat_connection.commands == list(PROBE_STREAM_PREPARE_COMMANDS)
    assert "terminal monitor" not in repeat_connection.commands
    assert "terminal logging level 7" not in repeat_connection.commands
    assert expected_command in repeat_connection.repeat_commands
    if task_type == TASK_WIRELESS_STATUS:
        assert repeat_connection.repeat_commands == (
            "display clock",
            "display ar5drv 1 client all rssi",
            "display ar5drv 1 client all status",
            "repeat 3 delay 3",
        )
        assert "display ar5drv 1 client all status" in raw_text
    assert expected_command in raw_text


def test_ar5drv_repeat_stream_stops_when_probe_prepare_fails(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)

    class FakeRepeatConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__(outputs={"probe": "probe\n          ^\n% Unrecognized command found at '^' position."})
            self.repeat_started = False

        def run_repeat_stream(self, commands, raw_path, stop_event, timeout: int, line_callback=None) -> None:
            self.repeat_started = True
            raise AssertionError("repeat stream must not start after probe prepare failure")

    main_connection = FakeConnection()
    repeat_connection = FakeRepeatConnection()
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=Factory([main_connection, repeat_connection]))

    collector.start()
    collector._start_repeat_thread(TASK_CHANNEL_BUSY)
    for thread in list(collector._stream_threads):
        thread.join(timeout=1)

    log_text = (collector.session.session_dir / "logs" / "collector.log").read_text(encoding="utf-8")
    assert repeat_connection.commands == list(PROBE_STREAM_PREPARE_COMMANDS)
    assert repeat_connection.repeat_started is False
    assert "collector=channel_busy prepare_status=failed reason=probe_failed" in log_text
    assert log_text.count("init_status=success") == 1
    raw_text = (collector.session.session_dir / "raw" / "channel_busy_raw.log").read_text(encoding="utf-8")
    assert "display ar5drv" not in raw_text
    assert "repeat 2 delay" not in raw_text


def test_streaming_switch_history_uses_normal_display_connection_after_main_init(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    main_connection = FakeConnection()
    switch_connection = FakeConnection(
        {
            "display clock": "2026-07-06 20:27:42",
            "display wlan mesh-link switch-history": "display wlan mesh-link switch-history\nTotal 0",
        }
    )
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=Factory([main_connection, switch_connection]))

    collector.start()
    collector._streaming_mode = True
    assert collector._replace_main_connection_for_stream_task(TASK_SWITCH_HISTORY) is True
    collector.run_once(TASK_SWITCH_HISTORY)

    latest_text = (collector.session.session_dir / "raw" / "switch_history_latest.log").read_text(encoding="utf-8")
    assert main_connection.closed is True
    assert switch_connection.commands[: len(NORMAL_DISPLAY_PREPARE_COMMANDS)] == list(NORMAL_DISPLAY_PREPARE_COMMANDS)
    assert "terminal monitor" not in switch_connection.commands
    assert "terminal logging level 7" not in switch_connection.commands
    assert "system-view" not in switch_connection.commands
    assert "probe" not in switch_connection.commands
    assert "display wlan mesh-link switch-history" in latest_text
    assert "SHELL/" not in latest_text


def test_stop_state_prevents_new_repeat_connection_and_start_log(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    main_connection = FakeConnection()
    unused_repeat_connection = FakeConnection()
    factory = Factory([main_connection, unused_repeat_connection])
    collector = OnlineMrCollector(config, OnlineMrSessionStore(paths), connection_factory=factory)

    collector.start()
    collector.request_stop()
    collector._start_repeat_thread(TASK_MESH_LINK)

    collector_text = (collector.session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE).read_text(encoding="utf-8")
    assert factory.created == [main_connection]
    assert "[collector=repeat] START" not in collector_text


def test_sqlite_writes_live_samples_and_active_peer(tmp_path: Path) -> None:
    collector, _ = _collector(tmp_path)
    collector.start()
    collector.run_once(TASK_MESH_LINK)
    with sqlite3.connect(collector.session.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM live_samples").fetchone()[0] == 1
        row = conn.execute("SELECT link_state, peer_mac_raw FROM live_mesh_links").fetchone()
    assert row == ("ACTIVE", "30f5-277a-5a2f")


def test_stop_updates_meta_and_closes_connection(tmp_path: Path) -> None:
    collector, connection = _collector(tmp_path)
    collector.start()
    collector.stop()
    meta = json.loads((collector.session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert connection.closed is True
    assert meta["ended_at"]
    assert meta["status"] == STATE_STOPPED


def test_recovery_marks_stale_collecting_meta_aborted(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    store = OnlineMrSessionStore(paths)
    session = store.create_session(config)
    session.update_status(STATE_COLLECTING)
    changed = store.mark_stale_sessions_aborted("demo")
    assert changed
    meta = json.loads((session.session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == STATE_ABORTED


def test_recovery_marks_stale_sessions_through_background_task(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    session.update_status(STATE_COLLECTING)

    result = run_background_task(
        BackgroundJob(
            task_type="online_mr_mark_stale_sessions",
            params={"site_name": "demo", "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
        )
    )

    assert result == {"changed_count": 1}
    assert json.loads((session.session_dir / "session_meta.json").read_text(encoding="utf-8"))["status"] == STATE_ABORTED


def test_ui_throttle_coalesces_many_snapshots() -> None:
    throttle = OnlineMrUiThrottle(500)
    for index in range(100):
        from netconsole.models.online_mr_models import OnlineMrSnapshot

        throttle.enqueue(OnlineMrSnapshot(str(index), STATE_COLLECTING))
    snapshot = throttle.flush()
    assert snapshot.session_id == "99"
    assert throttle.flush() is None
    assert throttle.flush_count == 1


def test_flush_snapshot_does_not_start_realtime_file_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    called = False

    def fail_parse(_snapshot: OnlineMrSnapshot) -> None:
        nonlocal called
        called = True
        raise AssertionError("realtime page must not start file parse worker")

    monkeypatch.setattr(page, "_maybe_parse_realtime", fail_parse)
    page.throttle.enqueue(OnlineMrSnapshot("session-1", STATE_STOPPED, device_id=1, device_name="MR-01", host="192.0.2.1"))

    page._flush_snapshot()

    assert called is False


def test_collector_snapshot_before_session_is_pending_with_device_identity(tmp_path: Path) -> None:
    collector, _connection = _collector(tmp_path)
    collector.status = STATE_CONNECTING

    snapshot = collector.snapshot()

    assert snapshot.status == STATE_CONNECTING
    assert snapshot.session_id == "pending:1"
    assert snapshot.device_id == 1
    assert snapshot.device_name == "FAT-AP-01"
    assert snapshot.host == "192.0.2.10"


def test_collector_snapshot_overrides_stale_latest_status(tmp_path: Path) -> None:
    collector, _connection = _collector(tmp_path)
    collector.start()
    collector.latest_snapshot = OnlineMrSnapshot(
        collector.session.meta.session_id,
        STATE_COLLECTING,
        device_id=collector.config.device_id,
        device_name=collector.config.device_name,
        host=collector.config.host,
        active_peer="30f5-277a-5a2f",
        local_rssi=36,
    )
    collector.status = STATE_STOPPED

    snapshot = collector.snapshot()

    assert snapshot.status == STATE_STOPPED
    assert collector.latest_snapshot.status == STATE_COLLECTING
    assert snapshot.active_peer == "30f5-277a-5a2f"


def test_collector_job_handle_cancel_only_requests_job_center_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _qt_app()
    paths, config = _config(tmp_path)
    worker = OnlineMrCollectorWorker(config, paths)
    calls: list[str] = []
    monkeypatch.setattr(worker._manager, "cancel_job", calls.append)

    worker.cancel()

    assert calls == [worker.job_id]
    assert worker.collector.cancelled is True
    assert worker.collector.status == STATE_STOPPING


def test_online_mr_job_page_terminal_events_restore_button_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "MR-Job")
    paths, config = _config(tmp_path)
    config.device_id = int(device.id)
    config.device_name = device.name
    config.mr_id = str(device.id)
    config.mr_name = device.name
    page.selected_device_ids = {int(device.id)}
    page.enable_fping_check.setChecked(False)
    page.enable_iperf_check.setChecked(False)
    monkeypatch.setattr(page, "_selected_devices", lambda: [device])
    monkeypatch.setattr(page, "_build_config_for_device", lambda _device: config)
    monkeypatch.setattr(page, "_confirm_start_collection", lambda _devices: True)
    started: list[OnlineMrCollectorWorker] = []
    monkeypatch.setattr(OnlineMrCollectorWorker, "start", lambda worker: started.append(worker))
    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.QMessageBox.warning", lambda *_args: None)

    page.start_collection()

    assert len(started) == 1
    assert not page.start_button.isEnabled()
    assert page.stop_selected_button.isEnabled()

    page.stop_selected()

    assert page.status_value == "STOPPING"
    assert not page.start_button.isEnabled()
    assert not page.stop_selected_button.isEnabled()

    page._worker_failed("连接失败", int(device.id))

    assert int(device.id) not in page.workers_by_device_id
    assert page.start_button.isEnabled()
    assert not page.stop_selected_button.isEnabled()

    page.start_collection()
    cancelled_worker = started[-1]
    cancelled_session = OnlineMrSessionStore(page.paths).create_session(config)
    cancelled_worker.collector.session = cancelled_session
    page._worker_started(cancelled_session.meta, cancelled_worker)
    cancelled_worker._handle_cancelled({"job_id": cancelled_worker.job_id})

    assert int(device.id) not in page.workers_by_device_id
    assert page.start_button.isEnabled()
    assert not page.stop_selected_button.isEnabled()

    page.start_collection()
    finished_worker = started[-1]
    finished_session = OnlineMrSessionStore(page.paths).create_session(config)
    finished_worker.collector.session = finished_session
    page._worker_started(finished_session.meta, finished_worker)
    finished_worker._handle_finished(
        {
            "job_id": finished_worker.job_id,
            "result": {"session_id": finished_session.meta.session_id, "status": "STOPPED"},
        }
    )

    assert int(device.id) not in page.workers_by_device_id
    assert page.start_button.isEnabled()
    assert not page.stop_selected_button.isEnabled()


def test_online_mr_start_confirmation_cancel_does_not_start_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "MR-Cancel")
    page.refresh_all()
    page.enable_fping_check.setChecked(False)
    page.enable_iperf_check.setChecked(False)
    page.selected_device_ids = {int(device.id)}
    started: list[OnlineMrCollectorWorker] = []
    preflight_calls: list[bool] = []
    initial_status = page.status_value
    monkeypatch.setattr(OnlineMrCollectorWorker, "start", lambda worker: started.append(worker))
    monkeypatch.setattr(page, "_show_start_confirm_dialog", lambda _message: False)
    monkeypatch.setattr(page, "_preflight_iperf_before_start", lambda: preflight_calls.append(True) or True)

    page.start_collection()

    assert started == []
    assert preflight_calls == []
    assert page.session_dirs == {}
    assert int(device.id) not in page.workers_by_device_id
    assert page.status_value == initial_status


def test_online_mr_start_confirmation_yes_collapses_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "MR-Start")
    page.refresh_all()
    page.enable_fping_check.setChecked(False)
    page.enable_iperf_check.setChecked(False)
    page.selected_device_ids = {int(device.id)}
    started: list[OnlineMrCollectorWorker] = []
    preflight_calls: list[bool] = []
    monkeypatch.setattr(OnlineMrCollectorWorker, "start", lambda worker: started.append(worker))
    monkeypatch.setattr(page, "_show_start_confirm_dialog", lambda _message: True)
    monkeypatch.setattr(page, "_preflight_iperf_before_start", lambda: preflight_calls.append(True) or True)

    page.start_collection()

    assert preflight_calls == [True]
    assert len(started) == 1
    assert page.parameter_panel_collapsed is True
    assert page.right_control_scroll.isHidden() is True
    assert page.vertical_splitter.sizes()[0] <= 260


def test_online_mr_start_confirmation_summary_includes_ping_details(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "Train01-MR-CT")
    page.refresh_all()

    row = next(row for row, row_device in enumerate(page.filtered_devices) if row_device.id == device.id)
    page.device_table.item(row, 0).setCheckState(Qt.Checked)
    page.enable_fping_check.setChecked(True)
    page.enable_iperf_check.setChecked(False)
    page.fping_packet_size.setValue(64)
    page.fping_interval_ms.setValue(10)
    page.fping_loss_threshold_ms.setValue(100)
    page.fping_loss_warn_edit.setText("0.7")
    page.fping_latency_warn_ms.setValue(100)
    page.fping_target_label_2.setText("10.122.7.250")
    page._fping_target_edited(2)

    message = page._build_start_confirm_message([device])

    assert "High-frequency Ping:" in message
    assert "- Ping 1: Enabled" in message
    assert "Device Name: Train01-MR-CT" in message
    assert f"Target IP: {device.primary_address}" in message
    assert "Packet Size: 64 bytes" in message
    assert "Send Interval: 10 ms" in message
    assert "Timeout Judgment: 100 ms" in message
    assert "Packet Loss Warning: 0.7%" in message
    assert "- Ping 2: Not enabled" in message
    assert "10.122.7.250" not in message
    assert "iperf: Not enabled" in message


def test_online_mr_start_confirmation_summary_keeps_ping_two_independent(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device_1 = _create_onboard_device(repository, onboard.id, "Train01-MR-CT")
    device_2 = _create_onboard_device(repository, onboard.id, "Train01-MR-DT")
    page.refresh_all()

    for row, row_device in enumerate(page.filtered_devices):
        if row_device.id in {device_1.id, device_2.id}:
            page.device_table.item(row, 0).setCheckState(Qt.Checked)
    page.enable_fping_check.setChecked(True)
    ping_1_index = page.fping_device_combo_1.findData(device_1.id)
    ping_2_index = page.fping_device_combo_2.findData(device_2.id)
    assert ping_1_index >= 0
    assert ping_2_index >= 0
    page.fping_device_combo_1.setCurrentIndex(ping_1_index)
    page.fping_device_combo_2.setCurrentIndex(ping_2_index)
    page.fping_target_label_1.setText("10.122.1.249")
    page.fping_target_label_2.setText("10.122.1.250")

    message = page._build_start_confirm_message([device_1, device_2])

    assert "- Ping 1: Enabled" in message
    assert "Device Name: Train01-MR-CT" in message
    assert "Target IP: 10.122.1.249" in message
    assert "- Ping 2: Enabled" in message
    assert "Device Name: Train01-MR-DT" in message
    assert "Target IP: 10.122.1.250" in message


def test_online_mr_start_confirmation_summary_includes_udp_iperf_details(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "Train01-MR-CT")
    page.refresh_all()

    page.enable_fping_check.setChecked(False)
    page.enable_iperf_check.setChecked(True)
    preset_index = page.iperf_preset_combo.findData("pis_udp_downlink_carrier")
    assert preset_index >= 0
    page.iperf_preset_combo.setCurrentIndex(preset_index)
    page.iperf_server_edit.setText("10.122.1.100")
    page.iperf_port_spin.setValue(5202)
    page.iperf_udp_bitrate_edit.setText("300")
    page.iperf_udp_threshold_edit.setText("280")
    page.iperf_packet_length_spin.setValue(1400)
    page.iperf_parallel_spin.setValue(2)
    page.auto_reconnect_check.setChecked(True)

    message = page._build_start_confirm_message([device])

    assert "iperf Traffic Test:" in message
    assert "State: Enabled" in message
    assert "Protocol: UDP" in message
    assert "Test Preset: PIS UDP 下行指定码率承载" in message
    assert "Server Address: 10.122.1.100" in message
    assert "Port: 5202" in message
    assert "Target Bandwidth: 300M" in message
    assert "UDP Acceptance Threshold: 280M" in message
    assert "UDP Packet Length: 1400 bytes" in message
    assert "Parallel Streams: 2" in message
    assert "Interval: 1 s" in message
    assert "Role: Ground server / onboard client" in message
    assert "Ground -> Onboard" in message
    assert "Startup Preflight: Enabled" in message
    assert "Auto Reconnect on Interruption: Enabled" in message


def test_online_mr_start_confirmation_summary_includes_tcp_iperf_details(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, "Train01-MR-CT")
    page.refresh_all()

    page.enable_fping_check.setChecked(False)
    page.enable_iperf_check.setChecked(True)
    page.iperf_server_edit.setText("10.122.1.100")
    page.iperf_protocol_combo.setCurrentText("TCP")
    page.iperf_tcp_threshold_edit.setText("600")
    page.iperf_tcp_pacing_check.setChecked(False)

    message = page._build_start_confirm_message([device])

    assert "Protocol: TCP" in message
    assert "Target Bandwidth: Auto Maximum Bandwidth" in message
    assert "TCP Acceptance Threshold: 600M" in message
    assert "TCP Pacing: Disabled" in message


def test_online_mr_start_confirmation_dialog_is_scrollable(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)

    dialog = page._create_start_confirm_dialog("\n".join(f"line {index}" for index in range(80)))

    scroll_area = dialog.findChild(QScrollArea)
    buttons = dialog.findChild(QDialogButtonBox)
    labels = dialog.findChildren(QLabel)
    assert scroll_area is not None
    assert scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert buttons is not None
    assert any("line 79" in label.text() for label in labels)
    assert dialog.minimumWidth() >= 640
    assert dialog.minimumHeight() >= 420
    dialog.deleteLater()


def test_parse_failure_saves_raw_marks_failed_and_loop_continues(tmp_path: Path) -> None:
    connection = FakeConnection({"display wlan mesh-link": "not a mesh table", "display ar5drv 1 channelbusy": "TxBusy: 11 RxBusy: 22"})
    collector, _ = _collector(tmp_path, connection)
    collector.start()
    collector.run_once(TASK_MESH_LINK)
    collector.run_once(TASK_CHANNEL_BUSY)
    raw = (collector.session.session_dir / "raw" / "mesh_link_raw.log").read_text(encoding="utf-8")
    assert "not a mesh table" in raw
    with sqlite3.connect(collector.session.db_path) as conn:
        statuses = [row[0] for row in conn.execute("SELECT parse_status FROM live_samples ORDER BY id")]
        busy_count = conn.execute("SELECT COUNT(*) FROM live_channel_busy").fetchone()[0]
    assert statuses == ["FAILED", "OK"]
    assert busy_count == 1


def test_run_forever_does_not_create_second_session_after_explicit_start(tmp_path: Path) -> None:
    collector, _ = _collector(tmp_path)
    meta = collector.start()
    collector.cancelled = True
    collector.run_forever()
    sessions = list((collector.session.session_dir.parent).iterdir())
    assert [path.name for path in sessions] == [meta.session_id]


def test_fping_tool_discovery_from_project_tools(tmp_path: Path) -> None:
    exe = tmp_path / "tools" / "fping_v5" / "fping.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")
    (exe.parent / "cygwin1.dll").write_text("fake", encoding="utf-8")
    assert find_fping_tool(PathResolver(tmp_path)) == exe.resolve()


def test_fping_v5_version_detects_json_support(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "fping.exe"
    exe.write_text("fake", encoding="utf-8")
    (tmp_path / "cygwin1.dll").write_text("fake", encoding="utf-8")

    def runner(*args, **kwargs):
        class Result:
            stdout = "/fping_v5/fping: Version 5.5" if "-v" in args[0] else "-J, --json output in JSON format"
            stderr = ""
            returncode = 1

        return Result()

    monkeypatch.setattr("netconsole.core.ping.fping_v5_runner.subprocess.run", runner)
    status = detect_fping_version(exe)
    assert status.found is True
    assert status.version == "5.5"
    assert status.json_supported is True


def test_fping_command_args_are_list_with_expected_parameters(tmp_path: Path) -> None:
    args = build_fping_v5_args(tmp_path / "fping.exe", "127.0.0.1", 10, 100)
    assert args == [
        str(tmp_path / "fping.exe"),
        "-J",
        "-l",
        "-p",
        "10",
        "-t",
        "100",
        "127.0.0.1",
    ]


def test_fping_success_and_failure_lines_parse_with_midnight_rollover() -> None:
    rows = parse_fping_lines(
        [
            "23:59:59.990 : Reply[6] from 10.62.90.252: bytes=64 time=4.9 ms TTL=255",
            "00:00:00.010 : Request timed out",
        ],
        datetime(2025, 12, 20, 12, 0, 0),
        default_target="10.62.90.252",
    )
    assert rows[0]["seq"] == 6
    assert rows[0]["success"] is True
    assert rows[0]["latency_ms"] == 4.9
    assert rows[0]["ttl"] == 255
    assert rows[0]["bytes"] == 64
    assert rows[1]["success"] is False
    assert rows[1]["latency_ms"] is None
    assert str(rows[1]["collected_at"]).startswith("2025-12-21")


def test_fping_summary_parse() -> None:
    summary = parse_fping_summary(
        "Packets: Sent = 97358, Received = 96573, Lost = 785 (0.806% loss)\n"
        "Minimum = 1.5 ms, Maximum = 534.4 ms, Average = 5.6 ms",
        "10.62.90.252",
    )
    assert summary["sent"] == 97358
    assert summary["received"] == 96573
    assert summary["lost"] == 785
    assert summary["loss_percent"] == 0.806
    assert summary["max_latency_ms"] == 534.4


def test_mesh_parser_normalizes_active_variants() -> None:
    line = LINE_A.replace("Active", "Active(ax)")

    records, status, error = parse_mesh_link_text(line, datetime(2025, 12, 3, 10, 12, 33))

    assert status == "OK"
    assert error == ""
    assert records[0].link_state == "ACTIVE"
    assert records[0].metrics["local_rssi_db"] == 36


def test_online_mesh_parser_accepts_peer_name_table_format() -> None:
    records, status, error = parse_mesh_link_text(
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        " bc5a-3457-7540         bc5a-3457-755f 51   74ad-cb9d-3321 WLAN-MeshLink694  Active(ax)       00h 36m 52s\n",
        datetime(2026, 6, 27, 3, 23, 54),
    )

    assert status == "OK"
    assert error == ""
    assert len(records) == 1
    assert records[0].link_state == "ACTIVE"
    assert records[0].peer_mac_raw == "bc5a-3457-755f"
    assert records[0].metrics["local_rssi_db"] == 51
    assert records[0].metrics["online_time"] == "00h 36m 52s"


def test_online_mesh_parser_accepts_empty_peer_name_table_format() -> None:
    records, status, error = parse_mesh_link_text(
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        "                        4ce9-e4f1-b880 53   5cf7-9605-960f WLAN-MeshLink25   Active(a)        00h 43m 10s\n",
        datetime(2026, 7, 7, 1, 29, 36),
    )

    assert status == "OK"
    assert error == ""
    assert len(records) == 1
    assert records[0].metrics["peer_name"] == ""
    assert records[0].peer_mac_raw == "4ce9-e4f1-b880"
    assert records[0].peer_mac_normalized == "4ce9e4f1b880"
    assert records[0].metrics["local_rssi_db"] == 53
    assert records[0].metrics["bssid"] == "5cf7-9605-960f"
    assert records[0].metrics["interface"] == "WLAN-MeshLink25"
    assert records[0].metrics["radio_mode"] == "a"
    assert records[0].metrics["online_time"] == "00h 43m 10s"
    assert records[0].link_state == "ACTIVE"


def test_online_mesh_parser_accepts_empty_peer_name_standby_online_time() -> None:
    records, status, error = parse_mesh_link_text(
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        "                        4ce9-e4ef-aae0 30   5cf7-9605-960f WLAN-MeshLink24   Standby(a)       00h 43m 07s\n",
        datetime(2026, 7, 7, 1, 29, 36),
    )

    assert status == "OK"
    assert error == ""
    assert len(records) == 1
    assert records[0].metrics["peer_name"] == ""
    assert records[0].peer_mac_raw == "4ce9-e4ef-aae0"
    assert records[0].link_state_raw == "Standby(a)"
    assert records[0].link_state == "STANDBY"
    assert records[0].metrics["online_time"] == "00h 43m 07s"


@pytest.mark.parametrize("peer_name", ["AP-X_3111", "AP-S_3406", "30f5-277a-0ea0", "083b-e9ec-da40"])
def test_online_mesh_parser_accepts_common_ap_names(peer_name: str) -> None:
    records, status, error = parse_mesh_link_text(
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        f" {peer_name:<22} 083b-e9ec-da40 39   74ad-cb9d-3321 WLAN-MeshLink694  Active(ax)       00h 36m 52s\n",
        datetime(2026, 6, 27, 3, 23, 54),
    )

    assert status == "OK"
    assert error == ""
    assert len(records) == 1
    assert records[0].metrics["peer_name"] == peer_name
    assert records[0].peer_mac_raw == "083b-e9ec-da40"


def test_channel_busy_parser_keeps_table_rows_with_structured_fields() -> None:
    rows = parse_channel_busy_text(
        "Date/Month/Year: 26/06/2026\n"
        "Ctl Channel: 165\n"
        "BandWidth: 1\n"
        "Record Interval(s):  9\n"
        "      Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
        "01     22:08:24          4          1          3          -\n"
        "02     22:08:15          7          5          6          -\n"
    )

    assert len(rows) == 2
    assert rows[0]["row_index"] == 1
    assert rows[0]["sample_time"] == "2026-06-26 22:08:24"
    assert rows[0]["channel_busy_sample_time"] == "2026-06-26 22:08:24"
    assert rows[0]["channel_busy_total"] == 4
    assert rows[0]["ctl_channel"] == 165
    assert rows[0]["bandwidth"] == 1
    assert rows[0]["record_interval"] == 9
    assert rows[0]["ctl_busy"] == 4
    assert rows[0]["tx_busy"] == 1
    assert rows[0]["rx_busy"] == 3


def test_channel_busy_parser_strips_collector_prefix_and_does_not_map_bandwidth_to_busy() -> None:
    rows = parse_channel_busy_text(
        "2026-07-07 03:05:11.465 [collector=repeat] RX  Ctl Channel: 165\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX  BandWidth: 1\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX  Record Interval(s):  9\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX  CurrentTime: 03:05:13\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX        Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX  01     03:05:07         81          2         77\n"
    )

    assert rows[0]["ctl_channel"] == 165
    assert rows[0]["bandwidth"] == 1
    assert rows[0]["ctl_busy"] == 81
    assert rows[0]["tx_busy"] == 2
    assert rows[0]["rx_busy"] == 77


def test_switch_history_parser_accepts_h3c_rows() -> None:
    rows = parse_switch_history_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        " bc5a-3457-cde0         bc5a-3457-cdef(A) N/A               54/0        06-27 20:32:35 01h 07m 41s\n"
        "                        0000-0000-0000(A) Link establish    0 /0        06-27 20:32:27 00h 00m 07s\n"
        " bc5a-3457-cc60         bc5a-3457-cc7f(A) Active link fault 27/27       06-27 20:32:27 00h 00m 00s\n",
        datetime(2026, 6, 27, 21, 40, 12),
    )

    assert len(rows) == 3
    assert rows[0]["switch_time"] == "2026-06-27 20:32:27"
    assert rows[0]["to_peer_name"] == ""
    assert rows[0]["reason"] == "Link establish"
    assert rows[1]["from_peer_mac"] == "0000-0000-0000"
    assert rows[1]["to_peer_name"] == "bc5a-3457-cc60"
    assert rows[1]["reason"] == "Active link fault"
    assert rows[2]["switch_time"] == "2026-06-27 20:32:35"
    assert rows[2]["from_peer_name"] == "bc5a-3457-cc60"
    assert rows[2]["to_peer_name"] == "bc5a-3457-cde0"
    assert rows[2]["to_peer_mac"] == "bc5a-3457-cdef"
    assert rows[2]["to_peer_mac_normalized"] == "bc5a3457cdef"
    assert rows[2]["reason"] == "N/A"
    assert rows[2]["in_rssi"] == 54


def test_switch_history_parser_fills_from_peer_in_time_order() -> None:
    rows = parse_switch_history_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        " bc5a-3457-cc60         bc5a-3457-cc6f(A) N/A               41/0        07-03 19:19:27 00h 00m 15s\n"
        " bc5a-3457-cbe0         bc5a-3457-cbef(A) Better RSSI       36/33       07-03 19:12:27 00h 07m 00s\n"
        " bc5a-3457-6ba0         bc5a-3457-6baf(A) Better RSSI       35/28       07-03 19:12:12 00h 00m 14s\n"
        " bc5a-3457-cbe0         bc5a-3457-cbef(A) Better RSSI       35/27       07-03 19:11:55 00h 00m 17s\n"
        " bc5a-3457-cc60         bc5a-3457-cc6f(A) Better RSSI       41/26       07-03 19:11:48 00h 00m 07s\n",
        datetime(2026, 7, 3, 20, 0, 0),
    )

    assert rows[1]["switch_time"] == "2026-07-03 19:11:55"
    assert rows[1]["from_peer_name"] == "bc5a-3457-cc60"
    assert rows[1]["from_peer_mac"] == "bc5a-3457-cc6f"
    assert rows[1]["to_peer_name"] == "bc5a-3457-cbe0"
    assert rows[1]["to_peer_mac"] == "bc5a-3457-cbef"
    assert rows[2]["from_peer_name"] == "bc5a-3457-cbe0"
    assert rows[2]["to_peer_name"] == "bc5a-3457-6ba0"
    assert rows[-1]["from_peer_name"] == "bc5a-3457-cbe0"
    assert rows[-1]["to_peer_name"] == "bc5a-3457-cc60"


def test_active_link_switch_parser_parses_terminal_monitor_log() -> None:
    rows = parse_active_link_switch_logs(
        "%Jul  3 19:19:27:496 2026 NBL12-LC05-MR-CT WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from bc5a-3457-cbe0_bc5a-3457-cbef(33) to bc5a-3457-cc60_bc5a-3457-cc6f(41): "
        "peer quantity = 14, link quantity = 3, switch reason = 2.\n",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.log_time == datetime(2026, 7, 3, 19, 19, 27, 496000)
    assert row.device_name == "NBL12-LC05-MR-CT"
    assert row.from_peer_name == "bc5a-3457-cbe0"
    assert row.from_peer_mac == "bc5a-3457-cbef"
    assert row.from_peer_rssi == 33
    assert row.to_peer_name == "bc5a-3457-cc60"
    assert row.to_peer_mac == "bc5a-3457-cc6f"
    assert row.to_peer_rssi == 41
    assert row.peer_quantity == 14
    assert row.link_quantity == 3
    assert row.switch_reason_code == 2
    assert row.switch_reason_text == "主动切换（未开启移动链路优化）"


def test_active_link_switch_parser_accepts_mac_only_endpoint() -> None:
    rows = parse_active_link_switch_logs(
        "%Jul  7 01:52:36:077 2026 HZ4DCS-MR6628E-T-040661-B WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from _4ce9-e4f1-b880(26) to _4ce9-e4ef-aae0(36): "
        "peer quantity = 5, link quantity = 2, switch reason = 2.\n",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.log_time == datetime(2026, 7, 7, 1, 52, 36, 77000)
    assert row.from_peer_name == ""
    assert row.from_peer_mac == "4ce9-e4f1-b880"
    assert row.from_peer_rssi == 26
    assert row.to_peer_name == ""
    assert row.to_peer_mac == "4ce9-e4ef-aae0"
    assert row.to_peer_rssi == 36
    assert row.peer_quantity == 5
    assert row.link_quantity == 2
    assert row.switch_reason_code == 2


def test_active_link_switch_parser_marks_empty_link() -> None:
    endpoint = parse_active_link_endpoint("NA_0000-0000-0000(0)")

    assert endpoint.is_empty_link is True
    assert endpoint.display_peer_name == "空链路"
    assert endpoint.radio_mac_display == "-"
    assert endpoint.rssi_display == "-"

    rows = parse_active_link_switch_logs(
        "%Jul  3 19:19:27:496 2026 NBL12-LC05-MR-CT WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from NA_0000-0000-0000(0) to bc5a-3457-cc60_bc5a-3457-cc6f(41): "
        "peer quantity = 14, link quantity = 3, switch reason = 1.\n",
    )

    assert rows[0].from_is_empty_link is True
    assert rows[0].from_station == "-"
    assert rows[0].from_serial_number == "-"
    assert rows[0].from_resolve_rule == "empty_link"
    assert rows[0].from_radio_mac_display == "-"
    assert rows[0].switch_reason_text == "首个 Mesh 链路建立"


def test_active_link_switch_unknown_reason_text() -> None:
    assert switch_reason_text(99) == "未知原因(99)"


def test_ap_radio_statistics_parser_extracts_required_counters() -> None:
    parsed = parse_ap_radio_statistics_text(
        "[Radio Statistics]\n"
        " TxFrameAllCnt       : 3949759\n"
        " TxFrameAllBytes     : 809134274\n"
        " RxFrameAllCnt       : 4902715\n"
        " RxFrameAllBytes     : 648170255\n"
        " TxRetryFrmCnt       : 198448               0                    0                    157395\n"
        " TxErrFrmCnt         : 162931               0                    12                   64835\n"
        " TxDiscardFrmCnt     : 162099               0                    0                    64532\n"
    )

    counters = parsed["counters"]
    assert counters["TxFrameAllCnt"] == 3949759
    assert counters["RxFrameAllCnt"] == 4902715
    assert counters["TxRetryFrmCnt"] == 355843
    assert parsed["retry_count"] == 355843
    assert parsed["error_count"] == 227778
    assert parsed["discard_count"] == 226631


def test_ap_radio_statistics_parser_extracts_latest_busy_values_from_prefixed_log() -> None:
    parsed = parse_ap_radio_statistics_text(
        "2026-07-07 03:05:11.465 [collector=repeat] RX [Radio Statistics]\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX ChannelBusy: 65\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX TxBusy: 12\n"
        "2026-07-07 03:05:11.465 [collector=repeat] RX RxBusy: 34\n"
    )

    assert parsed["channel_busy_total"] == 65
    assert parsed["ctl_busy"] == 65
    assert parsed["tx_busy"] == 12
    assert parsed["rx_busy"] == 34
    assert parsed["channel_busy_sample_time"] == "2026-07-07 03:05:11"


def test_realtime_state_unifies_mesh_busy_and_ping_fields() -> None:
    now = datetime(2026, 6, 27, 10, 0, 0)
    events = [
        OnlineMrEvent(now, "s1", 7, "ssh", "mesh", EVENT_MESH_SAMPLE, {"peer_mac": "30f5-277a-5a2f", "mr_rssi": 36, "link_state": "ACTIVE"}),
        OnlineMrEvent(now, "s1", 7, "ssh", "busy", EVENT_BUSY_SAMPLE, {"ctl_busy": 4, "tx_busy": 1, "rx_busy": 3}),
        OnlineMrEvent(now, "s1", 7, "fping_v5", "fping", EVENT_FPING_V5_SAMPLE, {"loss_rate_percent": 0.5, "avg_rtt_ms": 2.5}),
    ]

    state = build_realtime_state(
        device_id=7,
        device_name="MR",
        status="COLLECTING",
        events=events,
        sample_count=3,
        resolve_peer=lambda _mac: {"peer_ap_name": "AP-01", "peer_site": "宁波站"},
    )

    assert state.peer_name == "AP-01"
    assert state.peer_site == "宁波站"
    assert state.peer_station == "宁波站"
    assert state.mr_rssi == 36
    assert state.channel_busy_total == 4
    assert state.ctl_busy == 4
    assert state.loss == 0.5
    assert state.rtt == 2.5


def test_realtime_state_preserves_latest_valid_busy_when_later_stats_are_blank() -> None:
    now = datetime(2026, 6, 27, 10, 0, 0)
    state = build_realtime_state(
        device_id=7,
        device_name="MR",
        status="COLLECTING",
        events=[
            OnlineMrEvent(now, "s1", 7, "ssh", "busy", EVENT_BUSY_SAMPLE, {"ctl_busy": 55, "tx_busy": 12, "rx_busy": 34, "sample_time": "2026-06-27 10:00:00"}),
            OnlineMrEvent(now + timedelta(seconds=1), "s1", 7, "ssh", "stats", "STATS_SAMPLE", {"counters": {}}),
        ],
    )

    assert state.channel_busy_total == 55
    assert state.tx_busy == 12
    assert state.rx_busy == 34
    assert state.channel_busy_sample_time == "2026-06-27 10:00:00"


def test_realtime_state_continues_after_unresolved_peer_mac() -> None:
    now = datetime(2026, 7, 3, 18, 0, 0)
    calls: list[str] = []

    def resolve_peer(value: str) -> dict[str, object]:
        calls.append(value)
        if value == "bc5a-3457-7540":
            return {"peer_ap_name": "bc5a-3457-7540", "peer_site": "某站", "match_rule": "fit_ap_ap_mac_exact"}
        return {"peer_ap_name": "", "peer_site": "", "match_rule": "unresolved"}

    state = build_realtime_state(
        device_id=7,
        device_name="MR",
        status="COLLECTING",
        events=[
            OnlineMrEvent(
                now,
                "s1",
                7,
                "ssh",
                "mesh",
                EVENT_MESH_SAMPLE,
                {
                    "peer_name": "bc5a-3457-7540",
                    "peer_mac": "bc5a-3457-755f",
                    "peer_mac_normalized": "bc5a3457755f",
                    "bssid": "74ad-cb9d-345f",
                    "link_state": "ACTIVE",
                },
            )
        ],
        resolve_peer=resolve_peer,
    )

    assert calls[0] == "bc5a-3457-7540"
    assert state.peer_site == "某站"
    assert state.peer_station == "某站"


def test_realtime_state_does_not_let_standby_override_active_peer() -> None:
    now = datetime(2026, 6, 27, 10, 0, 0)
    events = [
        OnlineMrEvent(now, "s1", 7, "ssh", "mesh", EVENT_MESH_SAMPLE, {"peer_name": "active-peer", "peer_mac": "30f5-277a-5a2f", "mr_rssi": 36, "link_state": "ACTIVE"}),
        OnlineMrEvent(now + timedelta(seconds=1), "s1", 7, "ssh", "mesh", EVENT_MESH_SAMPLE, {"peer_name": "standby-peer", "peer_mac": "30f5-277a-5a3f", "mr_rssi": 10, "link_state": "STANDBY"}),
    ]

    state = build_realtime_state(device_id=7, device_name="MR", status="COLLECTING", events=events)

    assert state.peer_name == "active-peer"
    assert state.peer_mac == "30f5-277a-5a2f"
    assert state.mr_rssi == 36


def test_event_parser_extracts_simple_mesh_peer_fields() -> None:
    parser = EventParserEngine()
    event = OnlineMrEvent(
        datetime(2026, 6, 27, 10, 0, 0),
        "s1",
        7,
        "ssh",
        "mesh",
        EVENT_MESH_SAMPLE,
        {},
        raw="bc5a-3457-c8a0         bc5a-3457-c8bf 35   74ad-cb9d-317f WLAN-MeshLink774  Active(ax)       00h 05m 28s",
    )

    parser.on_event(event)

    latest = parser.latest("mesh")
    assert latest is not None
    assert latest["peer_name"] == "bc5a-3457-c8a0"
    assert latest["peer_mac"] == "bc5a-3457-c8bf"
    assert latest["mr_rssi"] == 35
    assert latest["bssid"] == "74ad-cb9d-317f"
    assert latest["interface"] == "WLAN-MeshLink774"
    assert latest["link_state"] == "ACTIVE"


def test_realtime_parser_extracts_latest_channel_busy_sample_from_stream_table() -> None:
    parser = OnlineMrRealtimeParser()
    parsed = parser.parse_raw_event(
        OnlineMrEvent(
            datetime(2026, 7, 7, 3, 5, 11, 465000),
            "s1",
            7,
            "ssh_stream",
            "busy",
            EVENT_BUSY_SAMPLE,
            {},
            raw=(
                "Date/Month/Year: 07/07/2026\n"
                "CurrentTime: 03:05:13\n"
                "      Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
                "01     03:05:07          81          2          77          -\n"
                "02     03:04:58          82          3          78          -\n"
            ),
        )
    )

    assert parsed is not None
    assert parsed.payload["channel_busy_total"] == 81
    assert parsed.payload["tx_busy"] == 2
    assert parsed.payload["rx_busy"] == 77
    assert parsed.payload["channel_busy_sample_time"] == "2026-07-07 03:05:07"


def test_realtime_aggregator_updates_stats_and_iperf_fields() -> None:
    now = datetime(2026, 6, 27, 10, 0, 0)
    aggregator = RealtimeAggregator(device_id=7, device_name="MR", status="COLLECTING")

    aggregator.update(OnlineMrEvent(now, "s1", 7, "ssh", "stats", "STATS_SAMPLE", {"retry_count": 12}))
    state = aggregator.update(OnlineMrEvent(now, "s1", 7, "iperf3", "iperf", "IPERF3_SAMPLE", {"throughput_mbps": 88.0, "retransmits": 2}))

    assert state.retry_count == 12
    assert state.retry == 12
    assert state.iperf_mbps == 88.0
    assert state.retrans == 2


def test_sliding_window_keeps_latest_module_after_window_trim() -> None:
    buffer = SlidingWindowBuffer(window_seconds=60)
    old_mesh = OnlineMrEvent(
        datetime(2026, 6, 27, 10, 0, 0),
        "s1",
        1,
        "ssh_stream",
        "mesh",
        EVENT_MESH_SAMPLE,
        {"peer_name": "AP-X_3111", "link_state": "ACTIVE"},
        raw="AP-X_3111 083b-e9ec-da40 39 74ad-cb9d-3321 WLAN-MeshLink694 Active(ax)",
    )
    busy = OnlineMrEvent(
        datetime(2026, 6, 27, 10, 2, 0),
        "s1",
        1,
        "ssh_stream",
        "busy",
        EVENT_BUSY_SAMPLE,
        {"tx_busy": 1, "rx_busy": 3},
    )

    buffer.add(old_mesh)
    buffer.add(busy)
    events = buffer.get_window()

    assert old_mesh in events
    assert busy in events
    state = build_realtime_state(device_id=1, device_name="MR", status=STATE_COLLECTING, events=events)
    assert state.peer_name == "AP-X_3111"
    assert state.tx_busy == 1


def test_iperf_json_parser_extracts_udp_1m_result() -> None:
    rows = parse_iperf_lines(
        [
            json.dumps(
                {
                    "intervals": [
                        {
                            "sum": {
                                "start": 0,
                                "end": 1,
                                "seconds": 1,
                                "bytes": 125000,
                                "bits_per_second": 1000000,
                                "jitter_ms": 0.12,
                                "lost_packets": 0,
                                "packets": 86,
                                "lost_percent": 0,
                            }
                        }
                    ],
                    "end": {
                        "sum": {
                            "start": 0,
                            "end": 10,
                            "seconds": 10,
                            "bytes": 1250000,
                            "bits_per_second": 1000000,
                            "jitter_ms": 0.2,
                            "lost_packets": 0,
                            "packets": 860,
                            "lost_percent": 0,
                        }
                    },
                }
            )
        ]
    )

    assert rows
    assert rows[0]["bitrate_mbps"] == 1.0
    assert rows[-1]["loss_percent"] == 0.0


def test_iperf_text_reader_accepts_powershell_utf16_json(tmp_path: Path) -> None:
    path = tmp_path / "iperf_client_raw.json"
    path.write_text('{"end":{"sum":{"bits_per_second":1000000}}}', encoding="utf-16")

    rows = parse_iperf_lines(read_iperf_text(path).splitlines())

    assert rows[-1]["bitrate_mbps"] == 1.0


def test_active_segment_ping_aggregation() -> None:
    start = datetime(2025, 12, 20, 10, 0, 0)
    samples = []
    for index in range(1000):
        samples.append(
            {
                "collected_at": (start + timedelta(milliseconds=index * 10)).isoformat(sep=" ", timespec="milliseconds"),
                "success": index >= 10,
                "latency_ms": None if index < 10 else 5.0,
            }
        )
    result = aggregate_ping_for_active_segment(samples, start, start + timedelta(seconds=10))
    assert result["ping_sent"] == 1000
    assert result["ping_lost"] == 10
    assert result["ping_loss_percent"] == 1.0
    assert result["max_consecutive_loss"] == 10


def test_repeat_command_groups_match_required_sequences() -> None:
    assert repeat_command_group(TASK_MESH_LINK, interval=1) == (
        "display clock",
        "display wlan mesh-link",
        "repeat 2 delay 1",
    )
    assert repeat_command_group(TASK_CHANNEL_BUSY, interval=9, radio_id=1) == (
        "display clock",
        "display ar5drv 1 channelbusy",
        "repeat 2 delay 9",
    )
    assert "display ar5drv 3 channelbusy" in repeat_command_group(TASK_CHANNEL_BUSY, interval=9, radio_id=3)
    assert repeat_command_group(TASK_AP_RADIO_STATISTICS, interval=10, radio_id=1)[1] == "display ar5drv 1 statistics"
    assert repeat_command_group(TASK_WIRELESS_STATUS, interval=3, radio_id=1) == (
        "display clock",
        "display ar5drv 1 client all rssi",
        "display ar5drv 1 client all status",
        "repeat 3 delay 3",
    )
    assert repeat_command_group(TASK_WIRELESS_STATUS, interval=3, radio_id=3) == (
        "display clock",
        "display ar5drv 3 client all rssi",
        "display ar5drv 3 client all status",
        "repeat 3 delay 3",
    )
    assert repeat_command_group(TASK_SWITCH_HISTORY, interval=300)[-1] == "repeat 2 delay 300"
    assert repeat_command_group(TASK_INTERFACE_RATE, interval=2) == (
        "display clock",
        "dis counters rate inbound interface",
        "dis counters rate outbound interface",
        "repeat 3 delay 2",
    )


def test_repeat_session_stop_sends_ctrl_c_and_closes() -> None:
    connection = FakeConnection()
    session = RepeatSshSession(connection, TASK_MESH_LINK, 1)
    session.stop()
    assert "\x03" in connection.commands
    assert connection.closed is True


def test_online_diagnosis_database_contains_required_tables(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    with sqlite3.connect(session.db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "ping_samples",
        "ping_summary",
        "live_samples",
        "live_mesh_links",
        "live_channel_busy",
        "live_radio_statistics_raw_index",
        "live_switch_history_latest",
        "live_interface_rates",
        "live_terminal_events",
        "live_events",
        "collector_logs",
    }.issubset(tables)


def test_session_raw_directory_precreates_required_files(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    raw_names = {path.name for path in (session.session_dir / "raw").iterdir()}
    assert {
        "mesh_link_raw.log",
        "channel_busy_raw.log",
        "ap_radio_statistics_raw.log",
        "switch_history_latest.log",
        "interface_rate_raw.log",
        "fping_v5_raw.log",
        "fping_v5_samples.jsonl",
    }.issubset(raw_names)
    assert "init_raw.log" not in raw_names
    assert "iperf_client_raw.log" not in raw_names


def test_disabled_fping_worker_writes_non_empty_summary(tmp_path: Path) -> None:
    _qt_app()
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    worker = FpingV5ProbeWorker(session, FpingConfig(enabled=False), tmp_path / "fping.exe")

    worker.run()

    summary = session.session_dir / "raw" / "fping_v5_final_summary.json"
    assert summary.read_text(encoding="utf-8").strip()


def test_online_mr_open_dir_defaults_to_site_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.os.name", "nt")
    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.os.startfile", lambda path: opened.append(str(path)), raising=False)

    page.open_selected_session_dir()

    expected = page.paths.online_mr_root("demo")
    assert expected.exists()
    assert opened == [str(expected)]


def test_default_online_mr_intervals_and_radio() -> None:
    config = OnlineMrIntervals()
    assert config.mesh_link == 1
    assert config.channel_busy == 9
    assert config.ap_radio_statistics == 10
    assert config.switch_history == 300
    assert config.interface_rate == 2
    assert config.wireless_status == 3


def test_online_mr_page_uses_card_layout_and_bounded_inputs(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)
    assert page.connection_box.title()
    assert page.period_box.title()
    assert page.radio_box.title()
    assert page.ping_box.title()
    assert not hasattr(page, "profile_combo")
    assert not hasattr(page, "device_combo")
    assert not hasattr(page, "host_edit")
    assert page.view_device_combo.minimumWidth() >= 260
    assert page.view_device_combo.maximumWidth() > 10000
    assert page.device_table.columnCount() == 9
    assert page.enable_iperf_check.isChecked() is False
    assert page.iperf_tcp_threshold_edit.text() == "600"
    assert not page.iperf_tcp_threshold_edit.isHidden()
    assert page.iperf_udp_bitrate_edit.isHidden()
    assert page.iperf_bandwidth_hint_label.text()
    assert page.connection_box.minimumHeight() >= 64
    assert page.connection_box.layout().count() >= 4
    assert page.action_bar.minimumHeight() >= 44
    assert page.action_layout.count() == 7
    assert page.action_layout.indexOf(page.force_stop_button) >= 0
    assert page.action_layout.indexOf(page.params_toggle_button) >= 0
    assert page.page_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert page.page_scroll.widget().minimumWidth() >= ONLINE_MR_PAGE_MIN_WIDTH
    assert not hasattr(page, "collect_config_button")
    assert not hasattr(page, "collect_config_once")
    assert page.available_device_count_label.parentWidget() is None
    assert page.site_label.isHidden()
    assert page.available_metric_label.text()
    top_layout = page.connection_box.layout()
    status_item = top_layout.itemAt(top_layout.count() - 1).widget()
    assert page.status_label.parentWidget() is status_item
    assert page.action_layout.indexOf(page.refresh_devices_button) >= 0
    assert page.start_button.minimumWidth() >= 104
    assert page.start_button.minimumHeight() >= 34
    assert page.status_label.minimumWidth() >= 72
    assert page.status_label.maximumWidth() > 10000
    assert page.fping_status_label_1.parentWidget() is None
    assert page.fping_status_label_2.parentWidget() is None
    page._refresh_collection_animation()
    assert page.collect_status_label_1.text().find("Ping 1") >= 0
    assert page.collect_status_label_1.text().find("Ping 2") >= 0
    assert page.collect_param_box.minimumHeight() >= 220
    assert page.collect_param_box.maximumHeight() > 10000
    assert page.advanced_box.minimumWidth() >= 260
    assert page.advanced_box.maximumWidth() > 10000
    assert page.advanced_box.minimumHeight() >= 190
    assert page.advanced_box.maximumHeight() > 10000
    assert not hasattr(page, "enable_wireless_status_check")
    assert page.wireless_status_label.text() == "无线状态"
    assert isinstance(page.wireless_status_interval_edit, QLineEdit)
    assert not isinstance(page.wireless_status_interval_edit, QAbstractSpinBox)
    assert page.wireless_status_interval_edit.text() == "3"
    assert page.period_box.layout().columnStretch(1) == 1
    assert page.collect_status_box.title() == "实时采集状态"
    assert page.collect_status_box.minimumHeight() >= 110
    assert page.collect_status_box.maximumHeight() > 10000
    assert page.collect_card_1.parentWidget() is page.collect_status_box
    assert page.collect_card_2.parentWidget() is page.collect_status_box
    assert not page.collect_progress_1.isVisible()
    assert page.device_table.minimumHeight() >= 120
    assert page.device_table.maximumHeight() > 10000
    assert page.device_table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert page.device_table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert isinstance(page.device_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)
    assert page.main_splitter.count() == 2
    assert page.main_splitter.childrenCollapsible() is False
    assert page.main_splitter.widget(0) is page.device_panel
    assert page.main_splitter.widget(1) is page.right_control_scroll
    assert page.main_work_panel.minimumWidth() >= ONLINE_MR_WORK_PANEL_MIN_WIDTH
    assert page.device_panel.minimumWidth() >= ONLINE_MR_LEFT_PANEL_MIN_WIDTH
    assert page.device_panel.minimumHeight() >= 180
    assert page.right_control_scroll.minimumWidth() >= ONLINE_MR_RIGHT_PANEL_MIN_WIDTH
    assert page.right_control_scroll.maximumWidth() > 10000
    assert page.right_control_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert page.ping_box.minimumHeight() >= 430
    assert page.ping_box.maximumHeight() > 10000
    assert page.fping_preset_combo.currentData() == "pis_high_ping_acceptance"
    assert page.fping_loss_warn_edit.text() == "0.7"
    assert page.fping_loss_warn_edit.minimumWidth() >= 110
    assert page.fping_device_combo_1.minimumWidth() >= 220
    assert page.fping_device_combo_1.maximumWidth() > 10000
    assert page.fping_target_label_1.minimumWidth() >= 160
    assert page.fping_target_label_1.maximumWidth() > 10000
    page.page_scroll.resize(1180, 760)
    page._update_realtime_responsive_layout()
    assert page.main_splitter.orientation() == Qt.Vertical
    page.page_scroll.resize(1500, 900)
    page._update_realtime_responsive_layout()
    assert page.main_splitter.orientation() == Qt.Horizontal
    numeric_spins = (
        page.mesh_interval,
        page.channel_interval,
        page.statistics_interval,
        page.switch_interval,
        page.interface_rate_interval,
        page.reconnect_interval,
        page.max_reconnect,
        page.duration_minutes,
        page.fping_packet_size,
        page.fping_interval_ms,
        page.fping_loss_threshold_ms,
        page.fping_latency_warn_ms,
        page.iperf_port_spin,
        page.iperf_parallel_spin,
        page.iperf_interval_spin,
        page.iperf_packet_length_spin,
    )
    for spin in numeric_spins:
        assert spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert spin.minimumWidth() >= 100
        assert spin.maximumWidth() > 10000
    assert page.fping_packet_size.maximum() == 65535
    assert page.fping_interval_ms.minimum() == 1
    assert page.fping_loss_threshold_ms.maximum() == 60000
    assert page.fping_latency_warn_ms.value() == 100
    assert page.max_reconnect.maximum() == 999
    assert page.duration_minutes.maximum() == 1440
    assert page.iperf_port_spin.value() == 5201
    assert page.iperf_duration_spin.value() == FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS
    assert page.iperf_duration_spin.isHidden()
    assert "跟随采集启停" in page.iperf_duration_mode_label.text()
    assert page.summary_table.minimumHeight() >= 120
    assert page.summary_table.maximumHeight() > 1000
    assert page.tabs.minimumHeight() >= 180
    assert page.tabs.count() == 3
    assert page.tabs.tabText(0) == "采集输出"
    assert page.tabs.tabText(1) == "采集日志"
    assert page.tabs.tabText(2) == "打流测试"
    expected_summary_widths = {
        0: 180,
        1: 130,
        SUMMARY_COL_STATUS: 90,
        SUMMARY_COL_ACTIVE_PEER: 190,
        SUMMARY_COL_PEER_MAC: 150,
        SUMMARY_COL_MR_RSSI: 80,
        SUMMARY_COL_BUSY_TIME: 150,
        SUMMARY_COL_BUSY_TOTAL: 95,
        SUMMARY_COL_BUSY_TX: 90,
        SUMMARY_COL_BUSY_RX: 90,
        SUMMARY_COL_PEER_SITE: 120,
        SUMMARY_COL_PEER_SECTION: 160,
        SUMMARY_COL_PING_LOSS: 80,
        SUMMARY_COL_PING_LATENCY: 90,
        SUMMARY_COL_COLLECTED: 90,
        SUMMARY_COL_FAILED: 90,
        SUMMARY_COL_RECONNECTS: 90,
        SUMMARY_COL_LAST_COLLECTION: 160,
        SUMMARY_COL_IPERF_MBPS: 100,
        SUMMARY_COL_IPERF_RETRANS: 80,
        SUMMARY_COL_SESSION: 170,
        SUMMARY_COL_DEVICE_ID: 80,
    }
    for column, width in expected_summary_widths.items():
        assert page.summary_table.columnWidth(column) >= width
    page.vertical_splitter.setSizes([480, 220, 180])
    page._save_vertical_splitter_sizes()
    assert page.settings.get_value("online_mr/realtime_vertical_splitter_sizes") == page.vertical_splitter.sizes()
    assert not page.advanced_detail.isVisible()

    from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

    analysis_page = OnlineMrCollectionAnalysisPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)
    tab_names = [analysis_page.tabs.tabText(index) for index in range(analysis_page.tabs.count())]
    assert tab_names[:2] == ["历史会话", "主链路信息"]
    assert "链路明细" in tab_names
    assert "主链路切换日志" in tab_names
    assert "分析图表" in tab_names
    assert "fping 1s聚合" in tab_names
    assert "诊断结果" in tab_names

    wheel = FakeWheelEvent()
    assert page._no_wheel_filter.eventFilter(page.mesh_interval, wheel) is True
    assert wheel.ignored is True
    combo_wheel = FakeWheelEvent()
    assert page._no_wheel_filter.eventFilter(page.radio_port, combo_wheel) is True
    assert combo_wheel.ignored is True


def test_online_mr_high_ping_presets_fill_common_parameters_only(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.fping_target_label_1.setText("10.10.10.1")
    page.fping_target_label_2.setText("10.10.10.2")

    preset_index = page.fping_preset_combo.findData("cbtc_dcs_attkping_256b")
    assert preset_index >= 0
    page.fping_preset_combo.setCurrentIndex(preset_index)

    assert page.fping_packet_size.value() == 256
    assert page.fping_interval_ms.value() == 30
    assert page.fping_loss_threshold_ms.value() == 100
    assert page.fping_loss_warn_edit.text() == "5"
    assert page.fping_latency_warn_ms.value() == 100
    assert page.fping_target_label_1.text() == "10.10.10.1"
    assert page.fping_target_label_2.text() == "10.10.10.2"

    page.fping_packet_size.setValue(1400)

    assert page.fping_preset_combo.currentData() == ""
    assert page.fping_packet_size.value() == 1400


def test_online_mr_iperf_protocol_switches_separate_threshold_controls(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)

    assert page.iperf_protocol_combo.currentText() == "TCP"
    assert not page.iperf_tcp_threshold_edit.isHidden()
    assert page.iperf_udp_bitrate_edit.isHidden()
    assert page.iperf_udp_threshold_edit.isHidden()

    page.iperf_protocol_combo.setCurrentText("UDP")

    assert page.iperf_tcp_threshold_edit.isHidden()
    assert not page.iperf_udp_bitrate_edit.isHidden()
    assert not page.iperf_udp_threshold_edit.isHidden()
    assert not page.iperf_packet_length_spin.isHidden()


def test_online_mr_iperf_cbtc_dcs_presets_fill_fields_without_clearing_server(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.iperf_server_edit.setText("10.122.100.10")

    udp_index = page.iperf_preset_combo.findData("cbtc_dcs_udp_1_3m_64b")
    assert udp_index >= 0
    page.iperf_preset_combo.setCurrentIndex(udp_index)

    assert page.iperf_server_edit.text() == "10.122.100.10"
    assert page.iperf_protocol_combo.currentText() == "UDP"
    assert page.iperf_direction_combo.currentData() == "download"
    assert page.iperf_udp_bitrate_edit.text() == "1.3"
    assert page.iperf_udp_threshold_edit.text() == "1.3"
    assert page.iperf_packet_length_spin.value() == 64
    assert page.iperf_parallel_spin.value() == 1
    assert page.iperf_interval_spin.value() == 1
    assert page.iperf_port_spin.value() == 5201
    assert page.iperf_duration_spin.value() == FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS

    tcp_index = page.iperf_preset_combo.findData("cbtc_dcs_tcp_observation")
    assert tcp_index >= 0
    page.iperf_preset_combo.setCurrentIndex(tcp_index)

    assert page.iperf_server_edit.text() == "10.122.100.10"
    assert page.iperf_protocol_combo.currentText() == "TCP"
    assert page.iperf_port_spin.value() == 5201
    assert page.iperf_tcp_threshold_edit.text() == "1"
    assert not page.iperf_tcp_pacing_check.isChecked()
    assert page.iperf_tcp_pacing_edit.text() == ""


def test_online_mr_fping_devices_follow_checked_mrs(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    first = _create_onboard_device(repository, onboard.id, "A")
    second = _create_onboard_device(repository, onboard.id, "BBB")
    page.refresh_all()

    for target in (first.id, second.id):
        row = next(row for row, device in enumerate(page.filtered_devices) if device.id == target)
        page.device_table.item(row, 0).setCheckState(Qt.Checked)

    assert page.fping_device_combo_1.currentData() == first.id
    assert page.fping_device_combo_2.currentData() == second.id
    assert not page.fping_target_label_1.isReadOnly()
    assert not page.fping_target_label_2.isReadOnly()
    assert page.fping_target_label_1.text() == first.primary_address
    assert page.fping_target_label_2.text() == second.primary_address
    combo_ids = {page.fping_device_combo_1.itemData(index) for index in range(page.fping_device_combo_1.count())}
    assert combo_ids == {None, first.id, second.id}

    page.fping_target_label_1.setText("203.0.113.250")
    page._fping_target_edited(1)
    page._refresh_ping_target_labels()
    first_config = page._build_config_for_device(first)
    second_config = page._build_config_for_device(second)
    assert first_config is not None
    assert second_config is not None
    assert first_config.fping.target == "203.0.113.250"
    assert second_config.fping.target == second.primary_address


def test_online_mr_single_checked_device_only_fills_ping1_and_preserves_manual_ping2(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    first = _create_onboard_device(repository, onboard.id, "MR-A")
    second = _create_onboard_device(repository, onboard.id, "MR-B")
    page.refresh_all()

    first_row = next(row for row, device in enumerate(page.filtered_devices) if device.id == first.id)
    page.device_table.item(first_row, 0).setCheckState(Qt.Checked)

    assert page.fping_device_combo_1.currentData() == first.id
    assert page.fping_target_label_1.text() == first.primary_address
    assert page.fping_device_combo_2.currentData() is None
    assert page.fping_target_label_2.text() == ""

    page.fping_target_label_2.setText("10.122.7.250")
    page._fping_target_edited(2)
    page.device_table.item(first_row, 0).setCheckState(Qt.Unchecked)
    second_row = next(row for row, device in enumerate(page.filtered_devices) if device.id == second.id)
    page.device_table.item(second_row, 0).setCheckState(Qt.Checked)

    assert page.fping_device_combo_1.currentData() == second.id
    assert page.fping_target_label_1.text() == second.primary_address
    assert page.fping_device_combo_2.currentData() is None
    assert page.fping_target_label_2.text() == "10.122.7.250"


def test_online_mr_summary_binds_station_and_latest_busy_columns(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem("7"))

    now = datetime(2026, 6, 27, 10, 0, 0)
    state = build_realtime_state(
        device_id=7,
        device_name="MR",
        status="COLLECTING",
        events=[
            OnlineMrEvent(now, "s1", 7, "ssh", "mesh", EVENT_MESH_SAMPLE, {"peer_mac": "30f5-277a-5a2f", "mr_rssi": 36, "link_state": "ACTIVE"}),
            OnlineMrEvent(now, "s1", 7, "ssh", "busy", EVENT_BUSY_SAMPLE, {"ctl_busy": 4, "tx_busy": 1, "rx_busy": 3, "sample_time": "2026-06-27 10:00:00"}),
        ],
        sample_count=2,
        resolve_peer=lambda _mac: {"peer_ap_name": "AP-01", "peer_site": "宁波站"},
    )

    page._update_summary_from_state(state)

    headers = [page.summary_table.horizontalHeaderItem(column).text() for column in range(page.summary_table.columnCount())]
    assert page.summary_table.columnCount() == 22
    assert headers[SUMMARY_COL_BUSY_TIME] == "Latest Busy Time"
    assert headers[SUMMARY_COL_BUSY_TOTAL] == "Total Busy"
    assert headers[SUMMARY_COL_BUSY_TX] == "Tx Busy"
    assert headers[SUMMARY_COL_BUSY_RX] == "Rx Busy"
    assert page.summary_table.item(0, SUMMARY_COL_PEER_SITE).text() == "宁波站"
    assert page.summary_table.item(0, SUMMARY_COL_PEER_MAC).text() == "30f5-277a-5a2f"
    assert page.summary_table.item(0, SUMMARY_COL_BUSY_TIME).text() == "2026-06-27 10:00:00"
    assert page.summary_table.item(0, SUMMARY_COL_BUSY_TOTAL).text() == "4%"
    assert page.summary_table.item(0, SUMMARY_COL_BUSY_TX).text() == "1%"
    assert page.summary_table.item(0, SUMMARY_COL_BUSY_RX).text() == "3%"
    assert page.summary_table.item(0, SUMMARY_COL_STATUS).background().color().name().lower() == "#1f7a4d"
    assert page.summary_table.item(0, SUMMARY_COL_DEVICE_ID).text() == "7"


def test_online_mr_snapshot_summary_prefers_peer_name_and_station(tmp_path: Path) -> None:
    from netconsole.models.online_mr_models import OnlineMrSnapshot

    page, _repository, _groups = _online_page_with_devices(tmp_path)
    snapshot = OnlineMrSnapshot(
        "pending:7",
        "STOPPED",
        device_id=7,
        device_name="MR-07",
        host="192.0.2.7",
        active_peer="30f5-277a-5a2f",
        peer_name="AP-X_3111",
        peer_station="横溪站",
        local_rssi=36,
    )

    page._upsert_summary(snapshot)

    headers = [page.summary_table.horizontalHeaderItem(column).text() for column in range(page.summary_table.columnCount())]
    assert headers[SUMMARY_COL_ACTIVE_PEER] == "Peer Name"
    assert headers[SUMMARY_COL_PING_LATENCY] == "Ping Latency"
    assert headers[SUMMARY_COL_LAST_COLLECTION] == "Last Collection"
    assert page.summary_table.item(0, SUMMARY_COL_ACTIVE_PEER).text() == "AP-X_3111"
    assert page.summary_table.item(0, SUMMARY_COL_PEER_SITE).text() == "横溪站"


def test_online_mr_analysis_headers_are_chinese_in_zh(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths, analysis_only=True)

    headers: list[str] = []
    for table in (page.mesh_table, page.mesh_detail_table, page.channel_table, page.switch_history_table, page.active_link_switch_table, page.interface_rate_table, page.fping_1s_table, page.diagnosis_table):
        headers.extend(table.horizontalHeaderItem(column).text() for column in range(table.columnCount()))

    forbidden = {"online_mr.radio_id", "radio_id", "PeerName", "Online time", "对端AP序列号", "原AP序列号", "新AP序列号"}
    assert forbidden.isdisjoint(headers)
    assert "序号" in headers
    assert "射频ID" in headers
    assert "链路状态" in headers
    assert "对端名称" in headers
    assert "原对端名称" in headers
    assert "新对端名称" in headers
    assert "来源" not in [
        page.active_link_switch_table.horizontalHeaderItem(column).text()
        for column in range(page.active_link_switch_table.columnCount())
    ]
    assert "控制信道繁忙度" in headers
    assert "采样时间" in headers
    assert "设备时间" in headers or "Device Time" in headers
    assert "链路明细" in [page.tabs.tabText(index) for index in range(page.tabs.count())]


def test_online_mr_analysis_table_fill_batches_large_results(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    rows = [
        [f"2026-07-10 12:00:{index % 60:02d}", f"MR-{index}", "1", "ACTIVE", f"AP-{index}"]
        for index in range(250)
    ]

    page._apply_analysis_table_payload({"table_rows": {"mesh_link": rows}})
    _process_qt_until(lambda: page.mesh_table.item(249, 0) is not None)

    assert page.mesh_table.rowCount() == 250
    assert page.mesh_table.item(249, 0).text() == "250"
    assert page.mesh_table.item(249, 4).text() == "ACTIVE"


def test_analysis_table_style_centers_headers_and_cells() -> None:
    _qt_app()
    table = QTableWidget(1, 2)
    table.setHorizontalHeaderLabels(["序号", "原始日志"])
    apply_analysis_table_style(table)
    table.setItem(0, 0, make_table_item("1"))
    table.setItem(0, 1, make_table_item("long raw content"))

    assert table.horizontalHeader().defaultAlignment() & Qt.AlignCenter
    assert table.horizontalHeaderItem(0).textAlignment() & Qt.AlignCenter
    assert table.item(0, 0).textAlignment() & Qt.AlignCenter
    assert table.item(0, 1).textAlignment() & Qt.AlignCenter
    assert table.item(0, 1).toolTip() == "long raw content"


def test_analysis_table_auto_fit_keeps_horizontal_scroll_and_caps_long_columns() -> None:
    _qt_app()
    table = QTableWidget(2, 2)
    table.resize(220, 180)
    table.setHorizontalHeaderLabels(["短列", "原始日志"])
    apply_analysis_table_style(table)
    table.setItem(0, 0, make_table_item("短"))
    table.setItem(0, 1, make_table_item("X" * 200))
    table.setItem(1, 0, make_table_item("短"))
    table.setItem(1, 1, make_table_item("Y" * 180))

    auto_fit_table_columns(table, min_widths={0: 60, 1: 120}, max_widths={1: 180})

    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert table.columnWidth(0) >= 60
    assert 120 <= table.columnWidth(1) <= 180
    assert table.columnWidth(0) + table.columnWidth(1) > table.viewport().width()


def test_analysis_table_auto_fit_samples_large_tables_without_full_scan() -> None:
    _qt_app()
    table = QTableWidget(5000, 3)
    table.setHorizontalHeaderLabels(["序号", "时间", "原始内容"])
    apply_analysis_table_style(table)
    started = time.perf_counter()
    for row in range(5000):
        table.setItem(row, 0, make_table_item(row + 1))
        table.setItem(row, 1, make_table_item(f"2026-07-03 19:00:{row % 60:02d}.000"))
        table.setItem(row, 2, make_table_item("raw " + ("X" * (row % 200))))

    auto_fit_table_columns(table, max_rows=500, min_widths={0: 60, 1: 190, 2: 300}, max_widths={2: 700})
    elapsed = time.perf_counter() - started

    assert table.columnWidth(0) >= 60
    assert table.columnWidth(1) >= 190
    assert 300 <= table.columnWidth(2) <= 700
    assert elapsed < 5.0


def test_online_mr_analysis_charts_render_from_parsed_sqlite(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", peer_mac="bc5a-3457-cbef", rssi=36)
        _insert_channel_busy_record(conn, session.meta.session_id, "2026-07-03 19:00:00.000", ctl_busy=7, tx_busy=4, rx_busy=3)
        _insert_fping_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", latency_ms=2.5)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", direction="inbound", interface_name="GE1/0/1", total_pps=100)
        _insert_switch_realtime_event(
            conn,
            session.meta.session_id,
            "2026-07-03 19:00:00.000",
            old_peer_name="AP-A",
            old_peer_mac="1111-2222-3333",
            old_rssi=30,
            new_peer_name="AP-B",
            new_peer_mac="4444-5555-6666",
            new_rssi=36,
            reason_text="Better RSSI",
        )

    page._render_analysis_charts(session.session_dir)

    assert {"rssi", "busy", "ping_loss", "ping", "interface", "switch_rssi", "switch_log_rssi"}.issubset(page.analysis_chart_canvases)
    assert {"rssi", "switch_rssi", "switch_log_rssi"}.issubset(page.analysis_chart_views)
    assert {"rssi", "busy", "ping_loss", "ping", "interface", "traffic", "switch_rssi", "switch_log_rssi"}.issubset(page.analysis_chart_widgets)
    assert "switch" not in page.analysis_chart_canvases
    for key in ("rssi", "busy", "ping_loss", "ping", "interface"):
        axis = page.analysis_chart_canvases[key].figure.axes[0]
        assert axis.lines or axis.collections
        assert axis.spines["right"].get_visible()
        assert any(tick.label2.get_visible() for tick in axis.yaxis.get_major_ticks())
    rssi_view = page.analysis_chart_views["rssi"]
    rssi_widget = page.analysis_chart_widgets["rssi"]
    assert rssi_widget.summary_labels["main_link"].text() == "1"
    assert rssi_widget.summary_labels["switch"].text() == "1"
    assert not rssi_widget.show_switch_points_checkbox.isHidden()
    rssi_axis = page.analysis_chart_canvases["rssi"].figure.axes[0]
    assert rssi_axis.collections
    assert rssi_view.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert rssi_view.scroll_area.widgetResizable() is True
    assert rssi_view.canvas.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert rssi_view.canvas.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    visible_actions = [action for action in rssi_view.toolbar.actions() if action.isVisible()]
    toolbar_texts = {action.text().replace("&", "") for action in visible_actions}
    assert {"复位", "后退", "前进", "平移", "缩放", "保存图片"}.issubset(toolbar_texts)
    visible_tooltips = " ".join(action.toolTip() for action in visible_actions)
    for english in ("Home", "Back", "Forward", "Pan", "Zoom", "Save", "Figure options", "Axes", "Curves"):
        assert english not in visible_tooltips
    assert all(action.text().replace("&", "") not in {"Subplots", "Customize"} or not action.isVisible() for action in rssi_view.toolbar.actions())
    switch_axis = page.analysis_chart_canvases["switch_rssi"].figure.axes[0]
    assert switch_axis.lines or switch_axis.collections
    assert switch_axis.spines["right"].get_visible()
    switch_log_axis = page.analysis_chart_canvases["switch_log_rssi"].figure.axes[0]
    assert switch_log_axis.lines or switch_log_axis.collections
    assert switch_log_axis.spines["right"].get_visible()


def test_online_mr_traffic_chart_renders_iperf_and_empty_state(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    with sqlite3.connect(session.db_path) as conn:
        conn.execute(
            "INSERT INTO iperf_runs (run_id, session_id, mode, protocol, server_ip, port, direction, started_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", session.meta.session_id, "client", "TCP", "10.0.0.10", 5201, "upload", "2026-07-03 19:00:00.000", "PARSED"),
        )
        conn.execute(
            """
            INSERT INTO iperf_intervals (
                run_id, session_id, collector_time, interval_start_sec, interval_end_sec, interval_center_time,
                transfer_bytes, bitrate_mbps, retransmits, role, jitter_ms, loss_percent, raw_line
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", session.meta.session_id, "2026-07-03 19:00:01.000", 0, 1, "2026-07-03 19:00:00.500", 1024, 88.1, 2, "sender", None, None, "iperf"),
        )

    page._render_analysis_charts(session.session_dir)

    traffic_axis = page.analysis_chart_canvases["traffic"].figure.axes[0]
    assert traffic_axis.lines
    assert "traffic" in page.analysis_chart_hover_controllers
    tooltip = page.analysis_chart_hover_controllers["traffic"].tooltip_text(0)
    assert "速率: 88.10 Mbps" in tooltip
    assert "协议: TCP" in tooltip
    assert "TCP重传: 2" in tooltip

    empty_page, _repository, _groups = _online_page_with_devices(tmp_path / "empty")
    empty_session = OnlineMrSessionStore(PathResolver(tmp_path / "empty")).create_session(config)
    empty_page._render_analysis_charts(empty_session.session_dir)
    empty_axis = empty_page.analysis_chart_canvases["traffic"].figure.axes[0]
    assert "当前会话无打流数据" in empty_axis.texts[0].get_text()


def test_online_mr_analysis_charts_use_dynamic_mesh_style_window(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    base_time = datetime.fromisoformat("2026-07-03 19:00:00.000")
    with sqlite3.connect(session.db_path) as conn:
        for index in range(180):
            collected_at = (base_time + timedelta(seconds=index)).isoformat(sep=" ", timespec="milliseconds")
            _insert_main_link_sample(conn, session.meta.session_id, collected_at, peer_mac=f"peer-{index % 3}", rssi=-35 - (index % 10))

    page._render_analysis_charts(session.session_dir)

    assert not hasattr(page, "_plot_analysis_chart")
    rssi_widget = page.analysis_chart_widgets["rssi"]
    assert hasattr(rssi_widget, "time_window_controller")
    assert rssi_widget.view.fill_parent is True
    assert rssi_widget.view.scroll_area.widgetResizable() is True
    assert rssi_widget.canvas.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert rssi_widget.canvas.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert rssi_widget.view.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert rssi_widget.view.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert rssi_widget.time_scrollbar.maximum() > 0
    assert rssi_widget.effective_visible_sample_count() == 120

    index_60 = rssi_widget.visible_samples_combo.findData(60)
    rssi_widget.visible_samples_combo.setCurrentIndex(index_60)

    assert rssi_widget.effective_visible_sample_count() == 60
    assert rssi_widget.time_scrollbar.maximum() >= 120


def test_online_mr_analysis_chart_lock_time_syncs_and_marker_styles(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    base_time = datetime.fromisoformat("2026-07-03 19:00:00.000")
    with sqlite3.connect(session.db_path) as conn:
        for index in range(3):
            collected_at = (base_time + timedelta(seconds=index)).isoformat(sep=" ", timespec="milliseconds")
            _insert_main_link_sample(conn, session.meta.session_id, collected_at, peer_mac=f"peer-{index}", rssi=-15 if index == 1 else -36 - index)
            _insert_channel_busy_record(conn, session.meta.session_id, collected_at, tx_busy=10 + index, rx_busy=20 + index)
        _insert_switch_realtime_event(conn, session.meta.session_id, "2026-07-03 19:00:01.000")

    page._render_analysis_charts(session.session_dir)
    locked_time = datetime.fromisoformat("2026-07-03 19:00:01.000")
    page._set_analysis_chart_locked_time(locked_time)

    assert page.analysis_chart_locked_time == locked_time
    for key in ("rssi", "busy"):
        widget = page.analysis_chart_widgets[key]
        assert widget.locked_time == locked_time
        assert widget.locked_index >= 0
        assert "已锁定时间点：2026-07-03 19:00:01.000" in widget.status_label.text()
        assert "当前图表最近点：2026-07-03 19:00:01.000" in widget.status_label.text()

    assert SWITCH_MARKER_STYLE["label"] == "链路切换点"
    assert ANOMALY_MARKER_STYLE["marker"] == "D"
    assert SWITCH_MARKER_STYLE["color"] != ANOMALY_MARKER_STYLE["color"]
    rssi_axis = page.analysis_chart_canvases["rssi"].figure.axes[0]
    collection_labels = {collection.get_label() for collection in rssi_axis.collections}
    assert "链路切换点" in collection_labels
    assert "异常点" in collection_labels

    page._clear_analysis_chart_locked_time()
    assert page.analysis_chart_locked_time is None
    assert page.analysis_chart_widgets["rssi"].locked_time is None


def test_online_mr_active_rssi_interactive_points_fill_nearby_metrics(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        for index, (collected_at, state, rssi) in enumerate(
            [
                ("2026-07-03 19:00:00.000", "ACTIVE", -36),
                ("2026-07-03 19:00:01.000", "STANDBY", -80),
            ]
        ):
            _insert_main_link_sample(conn, session.meta.session_id, collected_at, link_state=state, peer_mac=f"peer-{index}", rssi=rssi)
        _insert_channel_busy_record(conn, session.meta.session_id, "2026-07-03 19:00:05.000", ctl_busy=7, tx_busy=4, rx_busy=3)
        _insert_fping_sample(conn, session.meta.session_id, "2026-07-03 19:00:01.000", latency_ms=2.5)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:03.000", direction="inbound", interface_name="WLAN-MESH1", total_pps=100)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:03.000", direction="outbound", interface_name="WLAN-MESH1", total_pps=80)

    points = OnlineMrChartBuilder(session.db_path).build_active_rssi_interactive_points()

    assert len(points) == 1
    point = points[0]
    assert point.peer_mac == "peer-0"
    assert point.rssi == 36.0
    assert point.ctl_busy == "7" or point.ctl_busy == 7
    assert point.tx_busy == 4
    assert point.rx_busy == 3
    assert point.ping_loss == 0
    assert point.ping_avg_latency == 2.5
    assert point.inbound_pps == 100.0
    assert point.outbound_pps == 80.0


def test_online_mr_active_rssi_hover_snaps_nearest_and_formats_chinese_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from matplotlib.dates import date2num
    from matplotlib.dates import num2date

    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        for index, collected_at in enumerate(("2026-07-03 19:00:00.000", "2026-07-03 19:00:10.000")):
            _insert_main_link_sample(
                conn,
                session.meta.session_id,
                collected_at,
                link_state="ACTIVE",
                peer_mac=f"peer-{index}",
                peer_name=f"ap240{index}_b",
                resolved_peer_name=f"ap240{index}_b",
                rssi=-30 - index,
                station="03横溪站",
                section="桃源街-皋亭坝",
                online_time=f"00h 00m 0{index}s",
            )
        _insert_main_link_sample(
            conn,
            session.meta.session_id,
            "2026-07-03 19:00:10.000",
            link_state="STANDBY",
            peer_mac="standby-1",
            peer_name="ap2403_b",
            resolved_peer_name="ap2403_b",
            rssi=-28,
            station="04横溪站",
            section="桃源街-皋亭坝",
        )
        _insert_main_link_sample(
            conn,
            session.meta.session_id,
            "2026-07-03 19:00:10.000",
            link_state="STANDBY",
            peer_mac="standby-2",
            peer_name="ap2405_b",
            resolved_peer_name="ap2405_b",
            rssi=-24,
            station="05横溪站",
            section="桃源街-皋亭坝",
        )
        _insert_channel_busy_record(conn, session.meta.session_id, "2026-07-03 19:00:12.000", tx_busy=11, rx_busy=22)

    page._render_analysis_charts(session.session_dir)

    hover = page.analysis_chart_hover_controllers["rssi"]
    axis = page.analysis_chart_canvases["rssi"].figure.axes[0]
    left, right = axis.get_xlim()
    assert num2date(left).year == 2026
    assert num2date(right).year == 2026
    middle = date2num(datetime.fromisoformat("2026-07-03 19:00:07.000"))
    assert hover.nearest_index(middle) == 1
    text = hover.tooltip_text(1)
    assert "采样时间:" in text
    assert "RSSI: 31" in text
    assert "对端名称: ap2401_b" in text
    assert "对端MAC: peer-1" in text
    assert "归属站点: 03横溪站" in text
    assert "归属区间: 桃源街-皋亭坝" in text
    assert "MR侧发送信道繁忙度: 11%" in text
    assert "MR侧接收信道繁忙度: 22%" in text
    assert "备份链路:" in text
    assert "1. ap2403_b / 04横溪站 / 桃源街-皋亭坝 / RSSI 28" in text
    assert "2. ap2405_b / 05横溪站 / 桃源街-皋亭坝 / RSSI 24" in text
    assert "Mesh接口" not in text
    assert "Online Time" not in text
    assert "BSSID" not in text
    assert "链路状态" not in text
    assert "打流:" not in text
    assert "Jitter" not in text
    assert "TCP重传" not in text
    assert "接口 PPS" not in text

    hidden: list[bool] = []
    monkeypatch.setattr(hover, "hide", lambda: hidden.append(True))
    page.analysis_charts.setCurrentIndex((page.analysis_charts.currentIndex() + 1) % page.analysis_charts.count())
    assert hidden


def test_online_mr_analysis_tables_show_row_numbers_and_hide_ap_serial(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "\n".join(
            [
                f"2026-07-03 19:00:0{index} >>> display clock ; display wlan mesh-link\n{LINE_A}"
                for index in range(3)
            ]
        ),
        encoding="utf-8",
    )
    page._load_mesh_link_details(session.session_dir)

    assert [page.mesh_table.item(row, 0).text() for row in range(3)] == ["1", "2", "3"]
    headers = [page.mesh_table.horizontalHeaderItem(column).text() for column in range(page.mesh_table.columnCount())]
    assert headers[:5] == ["No.", "Sample Time", "Device Time", "Radio ID", "Link State"]
    assert "Peer AP Serial" not in headers

    for item in (
        {"switch_time": "2026-07-03 19:00:00", "radio": 1, "to_peer_name": "AP1", "to_peer_mac": "1111-2222-3333"},
        {"switch_time": "2026-07-03 19:00:01", "radio": 1, "to_peer_name": "AP2", "to_peer_mac": "1111-2222-4444"},
        {"switch_time": "2026-07-03 19:00:02", "radio": 1, "to_peer_name": "AP3", "to_peer_mac": "1111-2222-5555"},
    ):
        page._append_switch_history_table_row(item)
    assert [page.switch_history_table.item(row, 0).text() for row in range(3)] == ["1", "2", "3"]
    history_headers = [page.switch_history_table.horizontalHeaderItem(column).text() for column in range(page.switch_history_table.columnCount())]
    assert "归属区间" in history_headers
    assert "From AP Serial" not in history_headers
    assert "To AP Serial" not in history_headers


def test_online_mr_active_link_switch_log_table_row_numbers(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        for index in range(3):
            _insert_switch_realtime_event(
                conn,
                session.meta.session_id,
                f"2026-07-03 19:00:0{index}.000",
                device_name=config.device_name,
            )

    page._load_active_link_switch_logs(session.session_dir)

    assert [page.active_link_switch_table.item(row, 0).text() for row in range(3)] == ["1", "2", "3"]
    headers = [page.active_link_switch_table.horizontalHeaderItem(column).text() for column in range(page.active_link_switch_table.columnCount())]
    assert page.active_link_switch_table.columnCount() == 17
    assert "原归属区间" in headers
    assert "新归属区间" in headers
    assert "Source" not in headers
    assert "From AP Serial" not in headers
    assert "To AP Serial" not in headers


def test_online_mr_active_link_switch_log_table_filters_switch_history_source(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_switch_realtime_event(
            conn,
            session.meta.session_id,
            "2026-07-03 19:00:00.000",
            device_name=config.device_name,
            reason_text="主动切换（未开启移动链路优化）",
        )

    assert page._load_active_link_switch_logs(session.session_dir) == 1
    assert page.active_link_switch_table.item(0, 1).text() == "2026-07-03 19:00:00.000"
    assert page.active_link_switch_table.item(0, 16).text() == "主动切换（未开启移动链路优化）"


def test_online_mr_load_channel_busy_details_row_numbers(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    session, _config = _prepare_parsed_channel_busy_session(tmp_path, count=3)

    assert page._load_channel_busy_details(session.session_dir) == 3
    assert [page.channel_table.item(row, 0).text() for row in range(3)] == ["1", "2", "3"]
    headers = [page.channel_table.horizontalHeaderItem(column).text() for column in range(page.channel_table.columnCount())]
    assert "设备时间" in headers or "Device Time" in headers
    assert "记录序号" not in headers


def test_online_mr_cached_parse_load_continues_if_channel_busy_table_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    session, _config = _prepare_parsed_channel_busy_session(tmp_path, count=3)

    from netconsole.ui import online_mr_parse_worker as load_worker_module

    original_query = load_worker_module._execute_analysis_query

    def fail_channel(conn, name: str, query: str, limit: int):
        if name == "channel_busy":
            raise RuntimeError("channel boom")
        return original_query(conn, name, query, limit)

    monkeypatch.setattr(load_worker_module, "_execute_analysis_query", fail_channel)

    assert page._load_cached_parse_if_valid(session.session_dir) is True
    _process_qt_until(lambda: page.analysis_load_worker is None)
    assert page.diagnosis_table.rowCount() == 1
    assert "channel_busy" in page.log_text.toPlainText()


def test_online_mr_parse_completed_continues_if_channel_busy_table_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    session, _config = _prepare_parsed_channel_busy_session(tmp_path, count=3)

    from netconsole.ui import online_mr_parse_worker as load_worker_module

    original_query = load_worker_module._execute_analysis_query

    def fail_channel(conn, name: str, query: str, limit: int):
        if name == "channel_busy":
            raise RuntimeError("channel boom")
        return original_query(conn, name, query, limit)

    monkeypatch.setattr(load_worker_module, "_execute_analysis_query", fail_channel)
    summary = SimpleNamespace(
        active_segments=1,
        mesh_samples=0,
        radio_stats_samples=0,
        switch_history_samples=0,
        ping_samples=0,
        iperf_samples=0,
        channel_samples=3,
        interface_samples=0,
        issues=0,
    )

    page._parse_completed(session.session_dir, summary)
    _process_qt_until(lambda: page.analysis_load_worker is None)

    assert page.diagnosis_table.rowCount() == 1
    assert page.parse_worker is None
    assert "channel_busy" in page.log_text.toPlainText()


def test_online_mr_export_analysis_report_uses_qfiledialog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    output_path = tmp_path / "report.xlsx"
    monkeypatch.setattr(page, "_selected_session_dir_for_parse", lambda: session.session_dir)
    monkeypatch.setattr(
        "netconsole.ui.pages.online_mr_collection_page.QFileDialog.getSaveFileName",
        lambda *_args: (str(output_path), "Excel (*.xlsx)"),
    )
    page.export_analysis_report()
    _process_qt_until(
        lambda: page.export_report_worker is None and not getattr(page, "_netconsole_export_controllers", []),
        timeout=10.0,
    )

    assert output_path.exists()
    assert not output_path.with_name(f"{output_path.name}.tmp").exists()


def test_online_mr_parse_metadata_cache_valid_and_invalidates_on_raw_change(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    raw_path = session.session_dir / "raw" / "mesh_link_raw.log"
    raw_path.write_text(f"2026-07-03 19:00:00 >>> display clock ; display wlan mesh-link\n{LINE_A}\n", encoding="utf-8")
    parser = OnlineMrDiagnosisParser(session.session_dir)

    summary = parser.parse()
    cached = OnlineMrDiagnosisParser(session.session_dir).cached_summary_if_valid()

    assert summary.mesh_samples == 1
    assert cached is not None
    assert cached.cache_used is True
    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute("SELECT parser_version, raw_fingerprint, status FROM online_parse_metadata WHERE session_id = ?", (session.meta.session_id,)).fetchone()
    assert row[0]
    assert row[1]
    assert row[2] == "OK"

    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n# changed", encoding="utf-8")

    assert OnlineMrDiagnosisParser(session.session_dir).cached_summary_if_valid() is None


def test_online_mr_chart_builder_active_rssi_switch_empty_link_and_export(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", peer_mac="active", rssi=-36)
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", link_state="STANDBY", peer_mac="standby", rssi=-80)
        _insert_switch_realtime_event(
            conn,
            session.meta.session_id,
            "2026-07-03 19:01:00.000",
            device_name=config.device_name,
            old_peer_name="AP-A",
            old_peer_mac="1111-2222-3333",
            old_rssi=32,
            old_station="站点A",
            new_peer_name="NA",
            new_peer_mac="0000-0000-0000",
            new_rssi=0,
            new_station="-",
            peer_quantity=2,
            link_quantity=1,
            reason_code=4,
            reason_text="被动切换或强制断开后切换",
        )

    builder = OnlineMrChartBuilder(session.db_path)
    rssi = builder.build_active_rssi_series()
    switch = builder.build_switch_rssi_series()

    assert rssi.series[0].points == [("2026-07-03 19:00:00.000", 36.0)]
    assert switch.series[0].points == [("2026-07-03 19:01:00.000", 32)]
    assert switch.series[1].points == []
    assert switch.tooltip_rows[0]["to_peer_name"] == "空链路"

    export_path = tmp_path / "report.xlsx"
    OnlineMrAnalysisReportExporter().export(session.session_dir, export_path)
    from openpyxl import load_workbook

    workbook = load_workbook(export_path)
    assert {
        "综合结论",
        "会话信息",
        "质量总览",
        "时间轴质量分析",
        "fping业务质量",
        "Mesh主链路质量",
        "Peer稳定性分析",
        "切换影响分析",
        "丢包关联分析",
        "异常事件清单",
        "空口繁忙度分析",
        "射频统计分析",
        "接口速率分析",
        "链路重建与连接异常",
        "原始证据片段",
        "参数配置",
        "主链路信号趋势表",
        "主链路信号趋势图",
        "主链路切换前后信号趋势表",
        "主链路切换前后信号趋势图",
        "信道繁忙度趋势表",
        "信道繁忙度趋势图",
        "Ping丢包率趋势表",
        "Ping丢包率趋势图",
        "主链路切换原因统计表",
    }.issubset(set(workbook.sheetnames))


def test_vehicle_mr_offline_report_exports_diagnostic_sheets_without_default_details(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", peer_mac="active", rssi=36, station="站点A", section="区间A")
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", link_state="STANDBY", peer_mac="standby", rssi=30, station="站点A", section="区间A")
        _insert_channel_busy_record(conn, session.meta.session_id, "2026-07-03 19:00:00.000", tx_busy=10, rx_busy=12)
        _insert_fping_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", latency_ms=2.5)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", total_pps=128)
        _insert_switch_realtime_event(conn, session.meta.session_id, "2026-07-03 19:01:00.000", old_rssi=35, new_rssi=36)

    from netconsole.services.vehicle_mr_offline_excel_report import VehicleMrOfflineExcelReportExporter
    from openpyxl import load_workbook

    export_path = tmp_path / "vehicle_report.xlsx"
    VehicleMrOfflineExcelReportExporter().export(session.session_dir, export_path)
    workbook = load_workbook(export_path)

    expected_order = [
        "报告总览",
        "会话信息",
        "数据完整性",
        "质量评分",
        "时间轴质量概览",
        "fping业务质量",
        "Mesh主链路区段",
        "Peer质量排名",
        "切换影响分析",
        "丢包关联分析",
        "异常事件清单",
        "空口繁忙度分析",
        "射频统计分析",
        "接口速率分析",
        "链路重建与连接异常",
        "原始证据片段",
        "参数配置",
    ]
    assert workbook.sheetnames == expected_order
    assert "fping原始样本" not in workbook.sheetnames
    assert "趋势图表" not in workbook.sheetnames
    assert workbook["报告总览"]["A2"].value == "报告类型"
    assert workbook["fping业务质量"].max_row >= 2
    assert workbook["Mesh主链路区段"]["A2"].value == "未生成主链路区段数据，请先执行离线解析。"
    assert workbook["异常事件清单"]["A2"].value == "未发现异常事件。"


def test_online_mr_switch_rssi_chart_keeps_active_context_and_skips_empty_zero(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        for index, (collected_at, state, rssi) in enumerate(
            [
                ("2026-07-03 19:00:50.000", "ACTIVE", -35),
                ("2026-07-03 19:00:55.000", "ACTIVE", -36),
                ("2026-07-03 19:01:05.000", "ACTIVE", -42),
                ("2026-07-03 19:01:10.000", "STANDBY", -80),
            ]
        ):
            _insert_main_link_sample(conn, session.meta.session_id, collected_at, link_state=state, peer_mac=f"peer-{index}", rssi=rssi)
        _insert_switch_realtime_event(
            conn,
            session.meta.session_id,
            "2026-07-03 19:01:00.000",
            device_name=config.device_name,
            old_peer_name="AP-A",
            old_peer_mac="1111-2222-3333",
            old_rssi=34,
            old_station="站点A",
            new_peer_name="NA",
            new_peer_mac="0000-0000-0000",
            new_rssi=0,
            new_station="-",
            reason_code=4,
            reason_text="被动切换或强制断开后切换",
        )

    chart = OnlineMrChartBuilder(session.db_path).build_switch_rssi_series()

    before_points = chart.series[0].points
    after_points = chart.series[1].points
    assert before_points == [
        ("2026-07-03 19:00:50.000", 35.0),
        ("2026-07-03 19:00:55.000", 36.0),
        ("2026-07-03 19:01:00.000", 34.0),
    ]
    assert after_points == [("2026-07-03 19:01:05.000", 42.0)]
    assert all(value != 0 for _time, value in before_points + after_points)
    assert chart.tooltip_rows[0]["to_peer_name"] == "空链路"


def test_online_mr_switch_log_rssi_chart_uses_switch_event_rssi_only(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:00:55.000", link_state="ACTIVE", peer_mac="active-before", rssi=-36)
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-03 19:01:05.000", link_state="ACTIVE", peer_mac="active-after", rssi=-42)
        _insert_switch_realtime_event(
            conn,
            session.meta.session_id,
            "2026-07-03 19:01:00.000",
            device_name=config.device_name,
            old_peer_name="AP-A",
            old_peer_mac="1111-2222-3333",
            old_rssi=34,
            old_station="站点A",
            new_peer_name="NA",
            new_peer_mac="0000-0000-0000",
            new_rssi=0,
            new_station="-",
            reason_code=4,
            reason_text="被动切换或强制断开后切换",
        )

    chart = OnlineMrChartBuilder(session.db_path).build_switch_log_rssi_series()

    assert chart.series[0].points == [("2026-07-03 19:01:00.000", 34.0)]
    assert chart.series[1].points == []
    assert chart.tooltip_rows[0]["to_peer_name"] == "空链路"
    assert chart.events[0].severity == "warning"


def test_online_mr_chart_builder_interface_pps_keeps_interface_series(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", direction="inbound", interface_name="WLAN-MESH1", total_pps=300)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", direction="inbound", interface_name="WLAN-MESH1", total_pps=310)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", direction="outbound", interface_name="WLAN-MESH1", total_pps=250)
        _insert_interface_rate_sample(conn, session.meta.session_id, "2026-07-03 19:00:00.000", direction="inbound", interface_name="XGE1/0/1", total_pps=90)

    chart = OnlineMrChartBuilder(session.db_path).build_interface_rate_series()

    assert [series.name for series in chart.series] == ["WLAN-MESH1 入方向PPS", "WLAN-MESH1 出方向PPS"]
    assert chart.series[0].points == [("2026-07-03 19:00:00.000", 310.0)]
    assert chart.series[1].points == [("2026-07-03 19:00:00.000", 250.0)]
    assert all("广播PPS" not in series.name and "组播PPS" not in series.name for series in chart.series)


def test_online_mr_peer_resolver_supports_ap_name_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)

    monkeypatch.setattr(
        "netconsole.ui.pages.online_mr_collection_page.AcRepository.list_all_fit_ap_resources_with_metadata",
        lambda _self: [
            {
                "ap_name": "AP-X_3111",
                "ap_mac": "083b-e9ec-da40",
                "serial_number": "SN-3111",
                "site": "横溪站",
            }
        ],
    )

    assert page._resolve_peer_identity_cached(" ap-x_3111 ") is None
    _process_qt_until(lambda: page.peer_name_cache_worker is None)
    resolved = page._resolve_peer_identity_cached(" ap-x_3111 ")

    assert resolved is not None
    assert resolved["peer_ap_name"] == "AP-X_3111"
    assert resolved["peer_site"] == "横溪站"
    assert resolved["peer_mac"] == "083b-e9ec-da40"


def test_online_mr_stream_mesh_event_updates_summary_without_file_polling(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.session_dirs[session.meta.session_id] = session.session_dir
    page.session_to_device_id[session.meta.session_id] = int(device.id)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))

    page._handle_raw_stream_event(
        OnlineMrEvent(
            datetime(2026, 6, 27, 10, 0, 0),
            session.meta.session_id,
            int(device.id),
            "ssh_stream",
            "mesh",
            EVENT_MESH_SAMPLE,
            {},
            raw="bc5a-3457-c8a0         bc5a-3457-c8bf 35   74ad-cb9d-317f WLAN-MeshLink774  Active(ax)       00h 05m 28s",
        )
    )

    assert not hasattr(page, "_read_raw_tail")
    assert page.summary_table.item(0, 3).text() == "bc5a-3457-c8a0"
    assert page.summary_table.item(0, SUMMARY_COL_MR_RSSI).text() == "35"
    assert page.summary_table.item(0, SUMMARY_COL_LAST_COLLECTION).text().startswith("2026-06-27 10:00:00")


def test_online_mr_stream_mesh_event_accepts_ap_name_without_file_polling(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.session_dirs[session.meta.session_id] = session.session_dir
    page.session_to_device_id[session.meta.session_id] = int(device.id)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))

    page._handle_raw_stream_event(
        OnlineMrEvent(
            datetime(2026, 6, 27, 10, 0, 0),
            session.meta.session_id,
            int(device.id),
            "ssh_stream",
            "mesh",
            EVENT_MESH_SAMPLE,
            {},
            raw="AP-X_3111              083b-e9ec-da40 39   74ad-cb9d-3321 WLAN-MeshLink694  Active(ax)       00h 36m 52s",
        )
    )

    assert page.summary_table.item(0, SUMMARY_COL_ACTIVE_PEER).text() == "AP-X_3111"
    assert page.summary_table.item(0, SUMMARY_COL_MR_RSSI).text() == "39"


def test_online_mr_stream_event_creates_summary_row_for_second_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "B")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.session_dirs[session.meta.session_id] = session.session_dir
    page.session_to_device_id[session.meta.session_id] = int(device.id)

    page._handle_raw_stream_event(
        OnlineMrEvent(
            datetime(2026, 6, 27, 10, 0, 0),
            session.meta.session_id,
            int(device.id),
            "ssh_stream",
            "mesh",
            EVENT_MESH_SAMPLE,
            {},
            raw="AP-S_3406 083b-e9ec-da41 40 74ad-cb9d-3322 WLAN-MeshLink695 Active(ax)",
        )
    )

    row = page._find_row(page.summary_table, str(device.id), column=SUMMARY_COL_DEVICE_ID)
    assert row >= 0
    assert page.summary_table.item(row, SUMMARY_COL_ACTIVE_PEER).text() == "AP-S_3406"
    assert page.summary_table.item(row, SUMMARY_COL_MR_RSSI).text() == "40"


def test_online_mr_raw_output_is_split_by_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    first = _create_onboard_device(repository, onboard.id, "MR-A")
    second = _create_onboard_device(repository, onboard.id, "MR-B")
    page.refresh_all()
    first_session = OnlineMrSessionStore(page.paths).create_session(page._build_config_for_device(first))
    second_session = OnlineMrSessionStore(page.paths).create_session(page._build_config_for_device(second))
    page.session_dirs[first_session.meta.session_id] = first_session.session_dir
    page.session_dirs[second_session.meta.session_id] = second_session.session_dir
    page.session_to_device_id[first_session.meta.session_id] = int(first.id)
    page.session_to_device_id[second_session.meta.session_id] = int(second.id)

    page._handle_raw_stream_event(OnlineMrEvent(datetime(2026, 6, 27, 10, 0, 0), first_session.meta.session_id, int(first.id), "ssh_stream", "mesh", EVENT_MESH_SAMPLE, {}, raw="AP-X_3111 083b-e9ec-da40 39 74ad-cb9d-3321 WLAN-MeshLink694 Active(ax)"))
    page._handle_raw_stream_event(OnlineMrEvent(datetime(2026, 6, 27, 10, 0, 1), second_session.meta.session_id, int(second.id), "ssh_stream", "mesh", EVENT_MESH_SAMPLE, {}, raw="AP-S_3406 083b-e9ec-da41 40 74ad-cb9d-3322 WLAN-MeshLink695 Active(ax)"))
    page._flush_output_buffers()

    first_text = page.output_widgets_by_device_id[int(first.id)].toPlainText()
    second_text = page.output_widgets_by_device_id[int(second.id)].toPlainText()
    assert "AP-X_3111" in first_text
    assert "AP-S_3406" not in first_text
    assert "AP-S_3406" in second_text
    assert "AP-X_3111" not in second_text


def test_online_mr_hide_output_keeps_parser_and_summary_active(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.session_dirs[session.meta.session_id] = session.session_dir
    page.session_to_device_id[session.meta.session_id] = int(device.id)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))
    page.output_toggle.setChecked(True)

    page._handle_raw_stream_event(
        OnlineMrEvent(
            datetime(2026, 6, 27, 10, 0, 0),
            session.meta.session_id,
            int(device.id),
            "ssh_stream",
            "mesh",
            EVENT_MESH_SAMPLE,
            {},
            raw="AP-X_3111 083b-e9ec-da40 39 74ad-cb9d-3321 WLAN-MeshLink694 Active(ax)",
        )
    )

    assert page.summary_table.item(0, SUMMARY_COL_ACTIVE_PEER).text() == "AP-X_3111"
    assert page.output_buffers_by_device_id[int(device.id)]
    assert page.output_widgets_by_device_id[int(device.id)].toPlainText() == ""
    assert page.output_splitter.isVisible() is False


def test_online_mr_stream_mesh_active_change_writes_link_switch_event(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.session_dirs[session.meta.session_id] = session.session_dir
    page.session_to_device_id[session.meta.session_id] = int(device.id)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))

    for offset, peer in enumerate(("bc5a-3457-c8bf", "bc5a-3457-a97f")):
        page._handle_raw_stream_event(
            OnlineMrEvent(
                datetime(2026, 6, 27, 10, 0, offset),
                session.meta.session_id,
                int(device.id),
                "ssh_stream",
                "mesh",
                EVENT_MESH_SAMPLE,
                {},
                raw=f"bc5a-3457-c8a0         {peer} 35   74ad-cb9d-317f WLAN-MeshLink774  Active(ax)       00h 05m 28s",
            )
        )

    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute("SELECT event_type, payload_json FROM event_stream WHERE event_type = ?", (EVENT_LINK_SWITCH,)).fetchone()
    assert row is not None
    assert row[0] == EVENT_LINK_SWITCH
    assert "bc5a3457c8bf" in row[1]
    assert "bc5a3457a97f" in row[1]
    assert "bc5a3457c8bf -> bc5a3457a97f" in page.switch_history_text.toPlainText()


def test_online_mr_iperf_controls_ignore_mouse_wheel(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("en_US"), "demo", paths)

    spin_values = {
        page.iperf_port_spin: page.iperf_port_spin.value(),
        page.iperf_parallel_spin: page.iperf_parallel_spin.value(),
        page.iperf_interval_spin: page.iperf_interval_spin.value(),
    }
    combo_indexes = {
        page.iperf_protocol_combo: page.iperf_protocol_combo.currentIndex(),
        page.iperf_direction_combo: page.iperf_direction_combo.currentIndex(),
    }

    for widget, value in spin_values.items():
        event = FakeWheelEvent()
        widget.wheelEvent(event)
        assert event.ignored is True
        assert widget.value() == value

    for widget, index in combo_indexes.items():
        event = FakeWheelEvent()
        widget.wheelEvent(event)
        assert event.ignored is True
        assert widget.currentIndex() == index


def test_online_mr_page_table_widths_persist(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("en_US"), "demo", paths)
    page.mesh_table.setColumnWidth(0, 222)
    QApplication.processEvents()
    saved = page.settings.get_value("online_mr/table_widths/mesh_link")
    assert isinstance(saved, list)
    assert saved[0] == 222



def test_online_mr_filters_current_site_onboard_fat_ap_type_variants(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    other = groups.create("\u8f66\u7ad9")
    _create_onboard_device(repository, onboard.id, "A", "FAT-AP")
    _create_onboard_device(repository, onboard.id, "B", "FAT_AP")
    _create_onboard_device(repository, onboard.id, "C", "FAT AP")
    _create_onboard_device(repository, onboard.id, "D", "FATAP")
    _create_onboard_device(repository, onboard.id, "SW", "SW")
    _create_onboard_device(repository, other.id, "OTHER", "FAT-AP")
    page.refresh_all()

    assert [device.name for device in page.filtered_devices] == ["A", "B", "C", "D"]
    assert [is_fat_ap_device(value) for value in ("FAT-AP", "FAT_AP", "FAT AP", "FATAP")] == [True, True, True, True]
    assert page.available_device_count_label.text() == "4"


def test_online_mr_vehicle_device_sort_is_natural_name_host_id_order(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    for name in ("256", "10-xxx", "02-xxx", "25ct", "01-xxx"):
        _create_onboard_device(repository, onboard.id, name)
    page.refresh_all()
    assert [device.name for device in page.filtered_devices] == ["01-xxx", "02-xxx", "10-xxx", "25ct", "256"]
    assert sorted(page.filtered_devices, key=natural_device_sort_key) == page.filtered_devices


def test_online_mr_blocks_selecting_more_than_two_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    for name in ("A", "B", "C"):
        _create_onboard_device(repository, onboard.id, name)
    page.refresh_all()
    messages: list[str] = []
    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.QMessageBox.warning", lambda *_args: messages.append(str(_args[-1])))

    for row in range(3):
        page.device_table.item(row, 0).setCheckState(Qt.Checked)

    assert len(page._selected_devices()) == 2
    assert "maximum of 2" in messages[-1]


def test_online_mr_builds_config_from_device_management_and_device_session_dir(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, 'MR/01:*?"<>|', "FAT AP")
    page.refresh_all()
    page.enable_iperf_check.setChecked(True)
    page.iperf_server_edit.setText("10.0.0.1")
    page.iperf_tcp_threshold_edit.setText("100")

    config = page._build_config_for_device(device)
    assert config is not None
    assert config.mr_name == device.name
    assert config.device_id == device.id
    assert config.host == device.ip_address
    assert config.username == "admin"
    assert config.password == "secret"
    assert config.connection_targets == ()
    worker_config = collection_config_from_payload(collection_config_to_payload(config), page.paths)
    assert [target.method for target in worker_config.connection_targets] == ["primary_direct"]
    assert config.iperf.enabled is True
    assert config.iperf.target_bandwidth is None
    assert config.iperf.tcp_report_threshold_mbps == 100.0
    assert config.iperf.normalized().target_bandwidth is None
    assert config.iperf.normalized().report_threshold_mbps == 100.0
    assert config.fping.preset_key == "pis_high_ping_acceptance"
    assert config.fping.preset_name == "PIS 高频 Ping / 验收"
    assert config.fping.packet_size == 64
    assert config.fping.interval_ms == 10
    assert config.fping.loss_threshold_ms == 100
    assert config.fping.loss_warn_percent == 0.7
    assert config.fping.latency_warn_ms == 100
    assert config.fping.as_dict()["packet_size_bytes"] == 64
    assert config.fping.as_dict()["timeout_ms"] == 100
    assert config.safe_mr_name == safe_device_folder_name(device)
    session = OnlineMrSessionStore(page.paths).create_session(config)
    assert f"__{device.id}" in str(session.session_dir)
    assert "MR_01" in str(session.session_dir)


def test_online_mr_worker_rebuilds_tunnel_targets_for_enabled_vehicle_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = repository.create(
        Device(
            name="MR-01",
            group_id=onboard.id,
            device_type="FAT-AP",
            primary_address="10.0.0.1",
            backup_address="10.0.1.1",
            ssh_enabled=1,
            ssh_username="admin",
            ssh_password="secret",
            tunnel_enabled=1,
            tunnel1_enabled=1,
            tunnel1_host="jump1",
            tunnel1_username="jump",
            tunnel2_enabled=1,
            tunnel2_host="jump2",
            tunnel2_username="jump",
        )
    )
    page.refresh_all()

    config = page._build_config_for_device(device)

    assert config is not None
    assert config.connection_targets == ()
    worker_config = collection_config_from_payload(collection_config_to_payload(config), page.paths)
    assert [target.method for target in worker_config.connection_targets] == ["primary_direct", "backup_direct", "tunnel1", "tunnel2"]


def test_netmiko_shell_connection_falls_back_to_tunnel_and_releases_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _paths, config = _config(tmp_path)
    device = Device(
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )
    from netconsole.services.netmiko_connection import connection_targets

    config.connection_targets = tuple(connection_targets(device))
    calls: list[str] = []
    closed: list[bool] = []

    class FakeNetmiko:
        def send_command_timing(self, command, **_kwargs):
            return f"{command}\nOK"

        def disconnect(self):
            closed.append(True)

    def fake_connect(**params):
        calls.append(str(params["host"]))
        if params["host"] != "127.0.0.1":
            raise RuntimeError("direct failed")
        return FakeNetmiko()

    class FakeSession:
        local_host = "127.0.0.1"
        local_port = 10022

        def close(self):
            closed.append(True)

    monkeypatch.setitem(sys.modules, "netmiko", SimpleNamespace(ConnectHandler=fake_connect))
    monkeypatch.setattr("netconsole.services.online_mr_collector.TunnelManager.open_tunnel", lambda *_args: FakeSession())

    connection = NetmikoShellConnection(config)
    output = connection.send_command("display clock", 10)
    connection.close()

    assert output.endswith("OK")
    assert config.connection_method == "tunnel1"
    assert calls == ["10.0.0.1", "10.0.1.1", "127.0.0.1"]
    assert closed == [True, True]


def test_online_mr_skips_incomplete_connection_without_hiding_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    incomplete = repository.create(Device(name="NoPassword", group_id=onboard.id, device_type="FAT-AP", ip_address="192.0.2.50", ssh_enabled=1, ssh_username="admin", ssh_password=""))
    page.refresh_all()

    assert [device.name for device in page.filtered_devices] == ["NoPassword"]
    assert page._build_config_for_device(incomplete) is None


def test_online_mr_wireless_status_is_always_collected(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")

    config = page._build_config_for_device(device)

    assert config is not None
    assert TASK_WIRELESS_STATUS in config.tasks.enabled_tasks()


def test_online_mr_stop_selected_and_stop_all_are_device_scoped(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    first = _create_onboard_device(repository, onboard.id, "A")
    second = _create_onboard_device(repository, onboard.id, "B")
    page.refresh_all()

    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    first_worker = FakeWorker()
    second_worker = FakeWorker()
    page.workers_by_device_id = {first.id: first_worker, second.id: second_worker}
    page.manager.register_device(first.id, first_worker)
    page.manager.register_device(second.id, second_worker)
    row_for_first = next(row for row, device in enumerate(page.filtered_devices) if device.id == first.id)
    page.device_table.item(row_for_first, 0).setCheckState(Qt.Checked)

    page.stop_selected()
    assert first_worker.cancelled is True
    assert second_worker.cancelled is False
    page.stop_all()
    assert second_worker.cancelled is True


def test_online_mr_stop_all_covers_session_workers_and_probe_workers(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()

    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class FakeProbeWorker:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    session_worker = FakeWorker()
    fping_worker = FakeProbeWorker()
    iperf_worker = FakeProbeWorker()
    page.workers["session-1"] = session_worker
    page.session_to_device_id["session-1"] = int(device.id)
    page.manager.register("session-1", session_worker)
    page.fping_workers_by_device_id[int(device.id)] = fping_worker
    page.iperf_workers_by_device_id[int(device.id)] = iperf_worker

    page.stop_all()

    assert session_worker.cancelled is True
    assert fping_worker.stopped is True
    assert iperf_worker.stopped is True
    assert page.status_value == "STOPPING"
    assert page.stop_animation_timer.isActive()


def test_online_mr_reuses_one_iperf_worker_for_same_batch_config(tmp_path: Path, monkeypatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    tool = tmp_path / "tools" / "iperf" / "iperf3.exe"
    tool.parent.mkdir(parents=True)
    tool.write_text("fake", encoding="utf-8")
    session_a = tmp_path / "session-a"
    session_b = tmp_path / "session-b"
    (session_a / "raw").mkdir(parents=True)
    (session_b / "raw").mkdir(parents=True)

    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

    class FakeIperfWorker:
        instances = []

        def __init__(self, _tool, _command, log_file, **_kwargs) -> None:
            self.log_file = Path(log_file)
            self.mirrors: list[Path] = []
            self.started = False
            self.line_received = FakeSignal()
            self.interval_received = FakeSignal()
            self.error_received = FakeSignal()
            self.completed = FakeSignal()
            self.failed = FakeSignal()
            FakeIperfWorker.instances.append(self)

        def isRunning(self) -> bool:
            return self.started

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

        def add_mirror_log_file(self, path: Path, context=None) -> None:
            self.mirrors.append((Path(path), context or {}))

    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.IperfProcessWorker", FakeIperfWorker)
    iperf = IperfTrafficConfig(enabled=True, server_ip="192.0.2.254", port=5201, protocol="TCP", direction="upload", parallel=1, target_bandwidth=None, follow_collection=True)
    config = OnlineMrConnectionConfig(
        site="demo",
        mr_id="mr",
        mr_name="MR",
        safe_mr_name="MR",
        device_id=1,
        device_name="MR",
        host="192.0.2.1",
        iperf=iperf,
        duration_minutes=1,
    )
    ssh_worker = SimpleNamespace(collector=SimpleNamespace(config=config))
    meta_a = SimpleNamespace(session_id="s-a", session_dir=session_a, device_id=1)
    meta_b = SimpleNamespace(session_id="s-b", session_dir=session_b, device_id=2)
    page.session_to_device_id["s-a"] = 1
    page.session_to_device_id["s-b"] = 2

    page._start_iperf_worker(meta_a, ssh_worker)
    page._start_iperf_worker(meta_b, ssh_worker)

    assert len(FakeIperfWorker.instances) == 1
    worker = FakeIperfWorker.instances[0]
    assert page.iperf_workers["s-a"] is worker
    assert page.iperf_workers["s-b"] is worker
    assert worker.mirrors[0][0] == session_b / "raw" / "iperf_client_raw.log"
    assert worker.mirrors[0][1]["session_id"] == "s-b"
    assert worker.mirrors[0][1]["device_id"] == 2


def test_online_mr_discards_failed_iperf_batch_worker(tmp_path: Path, monkeypatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    tool = tmp_path / "tools" / "iperf" / "iperf3.exe"
    tool.parent.mkdir(parents=True)
    tool.write_text("fake", encoding="utf-8")
    session_dir = tmp_path / "session-a"
    (session_dir / "raw").mkdir(parents=True)

    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback) -> None:
            self.callbacks.append(callback)

    class FailedWorker:
        runner = SimpleNamespace(last_status="FAILED:1", last_error_code="unable_to_connect", stop_requested=False, process=None)
        stopped = False

        def isRunning(self) -> bool:
            return True

        def stop(self, status: str = "STOPPED_BY_USER") -> None:
            self.stopped = True

    class FakeIperfWorker:
        instances = []

        def __init__(self, _tool, _command, log_file, **_kwargs) -> None:
            self.log_file = Path(log_file)
            self.line_received = FakeSignal()
            self.interval_received = FakeSignal()
            self.error_received = FakeSignal()
            self.completed = FakeSignal()
            self.failed = FakeSignal()
            self.started = False
            FakeIperfWorker.instances.append(self)

        def isRunning(self) -> bool:
            return self.started

        def start(self) -> None:
            self.started = True

        def stop(self, status: str = "STOPPED_BY_USER") -> None:
            self.started = False

    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.IperfProcessWorker", FakeIperfWorker)
    iperf = IperfTrafficConfig(enabled=True, server_ip="192.0.2.254", port=5201, protocol="TCP", direction="upload", parallel=1, follow_collection=True)
    client_config = page._iperf_client_config_from_traffic(
        iperf.normalized(),
        duration_seconds=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        follow_collection=True,
    )
    batch_key = page._iperf_batch_key(client_config)
    failed_worker = FailedWorker()
    page.iperf_batch_workers[batch_key] = failed_worker
    page.iperf_batch_sessions[batch_key] = {"old-session"}
    config = OnlineMrConnectionConfig(
        site="demo",
        mr_id="mr",
        mr_name="MR",
        safe_mr_name="MR",
        device_id=1,
        device_name="MR",
        host="192.0.2.1",
        iperf=iperf,
    )
    ssh_worker = SimpleNamespace(collector=SimpleNamespace(config=config))
    meta = SimpleNamespace(session_id="s-a", session_dir=session_dir, device_id=1)

    page._start_iperf_worker(meta, ssh_worker)

    assert failed_worker.stopped is True
    assert len(FakeIperfWorker.instances) == 1
    assert page.iperf_workers["s-a"] is FakeIperfWorker.instances[0]


def test_online_mr_stop_all_does_not_wait_for_worker_process_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "MR-01")
    page.refresh_all()
    paths, config = _config(tmp_path)
    config.device_id = int(device.id)

    worker = OnlineMrCollectorWorker(config, paths)
    cancelled: list[str] = []
    monkeypatch.setattr(worker._manager, "cancel_job", cancelled.append)
    page.workers["session-1"] = worker
    page.workers_by_device_id[int(device.id)] = worker
    page.session_to_device_id["session-1"] = int(device.id)
    page.manager.register_device(int(device.id), worker)

    started = time.perf_counter()
    page.stop_all()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.3
    assert cancelled == [worker.job_id]
    assert worker.collector.status == STATE_STOPPING
    assert page.status_value == "STOPPING"
    assert page.stop_animation_timer.isActive()


def test_online_mr_prepare_shutdown_stops_timers_and_workers(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.stop_animation_timer.start()
    worker = _ShutdownWorker()
    probe = _ShutdownWorker()
    iperf = _ShutdownWorker()
    page.workers["session-1"] = worker
    page.workers_by_device_id[1] = worker
    page.fping_workers_by_device_id[1] = probe
    page.fping_workers["session-1"] = probe
    page.iperf_workers_by_device_id[1] = iperf
    page.iperf_workers["session-1"] = iperf

    page.prepare_shutdown("app_exit")

    assert page._shutdown_requested is True
    assert all(not timer.isActive() for timer in page._runtime_timers())
    assert worker.cancelled is True
    assert probe.stopped is True
    assert iperf.stopped is True


def test_online_mr_normal_page_close_detaches_without_stopping_workers(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    worker = _ShutdownWorker()
    probe = _ShutdownWorker()
    iperf = _ShutdownWorker()
    page.workers["session-1"] = worker
    page.workers_by_device_id[1] = worker
    page._attached_worker_sessions.add("session-1")
    page.fping_workers["session-1"] = probe
    page.fping_workers_by_device_id[1] = probe
    page.iperf_workers["session-1"] = iperf
    page.iperf_workers_by_device_id[1] = iperf

    page.prepare_shutdown("window_close")

    assert page._shutdown_requested is False
    assert all(not timer.isActive() for timer in page._runtime_timers())
    assert worker.cancelled is False
    assert probe.stopped is False
    assert iperf.stopped is False

    page.on_enter()

    assert page._ui_updates_enabled is True
    assert page.refresh_timer.isActive()
    assert page.output_render_timer.isActive()
    assert page.reconcile_timer.isActive()
    assert worker.cancelled is False


def test_online_mr_new_session_clears_device_realtime_view(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.output_buffers_by_device_id[1] = deque(["old raw"], maxlen=2000)
    page.latest_iperf_by_device_id[1] = {"bitrate_mbps": 88.1}
    page.realtime_states_by_device_id[1] = SimpleNamespace()
    page._last_active_peer_by_device_id[1] = "old-peer"
    page._stream_sample_count_by_device_id[1] = 99
    page._ensure_output_widget(1, "old-session").setPlainText("old raw")
    for table in (page.mesh_table, page.channel_table, page.interface_rate_table, page.iperf_table, page.events_table):
        table.setRowCount(1)

    page._reset_device_realtime_view_for_new_session(1)

    assert list(page.output_buffers_by_device_id[1]) == []
    assert 1 not in page.latest_iperf_by_device_id
    assert 1 not in page.realtime_states_by_device_id
    assert 1 not in page._last_active_peer_by_device_id
    assert 1 not in page._stream_sample_count_by_device_id
    assert page.output_widgets_by_device_id[1].toPlainText() == ""
    assert all(table.rowCount() == 0 for table in (page.mesh_table, page.channel_table, page.interface_rate_table, page.iperf_table, page.events_table))


def test_online_mr_finalize_stops_session_probe_and_nonbatch_iperf(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    collector = _ShutdownWorker()
    probe = _ShutdownWorker()
    iperf = _ShutdownWorker()
    page.workers["session-1"] = collector
    page.workers_by_device_id[1] = collector
    page.session_to_device_id["session-1"] = 1
    page.fping_workers["session-1"] = probe
    page.fping_workers_by_device_id[1] = probe
    page.iperf_workers["session-1"] = iperf
    page.iperf_workers_by_device_id[1] = iperf

    page._finalize_collection_state(
        device_id=1,
        session_id="session-1",
        final_status="STOPPED",
        reason="completed",
    )

    assert probe.stopped is True
    assert iperf.stopped is True
    assert "session-1" not in page.workers
    assert 1 not in page.workers_by_device_id


def test_online_mr_callbacks_do_not_touch_ui_after_prepare_shutdown(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    page.prepare_shutdown("app_exit")
    page.available_metric_label = None
    page.running_count_label = None
    page.fping_status_label_1 = None
    page.fping_status_label_2 = None

    page._flush_snapshot()
    page._reconcile_collection_state()
    page._refresh_collection_animation()
    page._refresh_top_metrics()
    page.refresh_all()


def test_online_mr_stop_updates_device_and_summary_status(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()

    class FakeWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    worker = FakeWorker()
    page.workers_by_device_id = {device.id: worker}
    page.manager.register_device(device.id, worker)
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))
    row = next(row for row, row_device in enumerate(page.filtered_devices) if row_device.id == device.id)
    page.device_table.item(row, 0).setCheckState(Qt.Checked)

    page.stop_selected()

    assert worker.cancelled is True
    assert page.status_value == "STOPPING"
    assert page.stop_animation_timer.isActive()
    assert "stopping" in page.summary_table.item(0, 2).text().lower()


def test_online_mr_reconcile_prunes_orphan_collecting_summary_row(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))
    page.summary_table.setItem(0, SUMMARY_COL_SESSION, QTableWidgetItem("orphan-session"))
    page.summary_table.setItem(0, SUMMARY_COL_STATUS, QTableWidgetItem(page._status_text(STATE_COLLECTING)))

    page._reconcile_collection_state()

    assert page.summary_table.item(0, SUMMARY_COL_STATUS).text() == page._status_text(STATE_STOPPED)
    assert page.status_value == STATE_STOPPED


def test_online_mr_pages_share_runtime_for_same_site(tmp_path: Path) -> None:
    page, repository, _groups = _online_page_with_devices(tmp_path)
    second = OnlineMrCollectionPage(repository, I18n("en_US"), "demo", page.paths)

    assert second.manager is page.manager
    assert second.realtime_cache is page.realtime_cache
    assert second.workers is page.workers
    assert second.output_buffers_by_device_id is page.output_buffers_by_device_id


def test_online_mr_output_hidden_state_syncs_between_pages(tmp_path: Path) -> None:
    page, repository, _groups = _online_page_with_devices(tmp_path)
    second = OnlineMrCollectionPage(repository, I18n("en_US"), "demo", page.paths)

    page.output_toggle.setChecked(True)

    assert second.output_toggle.isChecked() is True
    assert second.output_render_enabled is False

    second.output_toggle.setChecked(False)

    assert page.output_toggle.isChecked() is False
    assert page.output_render_enabled is True


def test_online_mr_site_switch_clears_page_ui_without_stopping_runtime(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    page.summary_table.setRowCount(1)
    page.summary_table.setItem(0, SUMMARY_COL_DEVICE_ID, QTableWidgetItem(str(device.id)))
    page.summary_table.setItem(0, SUMMARY_COL_SESSION, QTableWidgetItem("demo-session"))
    page.summary_table.setItem(0, SUMMARY_COL_STATUS, QTableWidgetItem(page._status_text(STATE_COLLECTING)))
    page.output_buffers_by_device_id.setdefault(int(device.id), deque(maxlen=2000)).append("line")
    page._ensure_output_widget(int(device.id), "demo-session")
    page.selected_device_ids.add(int(device.id))

    page.set_site("other")

    assert page.site_name == "other"
    assert page.summary_table.rowCount() == 0
    assert page.output_widgets_by_device_id == {}
    assert page.selected_device_ids == set()


def test_online_mr_reconcile_restores_running_summary_row_from_runtime(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    snapshot = OnlineMrSnapshot(
        session_id="running-session",
        device_id=int(device.id),
        device_name=device.name,
        host=device.primary_address or "",
        status=STATE_COLLECTING,
        collected_count=3,
    )

    class _Signal:
        def connect(self, _callback) -> None:
            return None

    class _Collector:
        config = SimpleNamespace(site="demo", device_name=device.name, host=device.primary_address or "", connection_method="SSH")

        def snapshot(self) -> OnlineMrSnapshot:
            return snapshot

    worker = SimpleNamespace(
        collector=_Collector(),
        snapshot=_Signal(),
        raw_stream_event=_Signal(),
        completed=_Signal(),
        failed=_Signal(),
    )
    page.workers["running-session"] = worker
    page.workers_by_device_id[int(device.id)] = worker
    page.session_to_device_id["running-session"] = int(device.id)

    page._reconcile_collection_state()

    assert page.summary_table.rowCount() == 1
    assert page.summary_table.item(0, SUMMARY_COL_DEVICE_ID).text() == str(device.id)
    assert page.running_count_label.text() == "1"


def test_online_mr_view_device_follows_checked_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    first = _create_onboard_device(repository, onboard.id, "A")
    second = _create_onboard_device(repository, onboard.id, "B")
    page.refresh_all()
    row_for_second = next(row for row, device in enumerate(page.filtered_devices) if device.id == second.id)

    page.device_table.item(row_for_second, 0).setCheckState(Qt.Checked)

    assert page.view_device_combo.currentData() == second.id
    assert page.view_device_combo.itemData(0) == second.id


def test_online_mr_parse_prefers_current_view_device_session(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "A")
    page.refresh_all()
    config = page._build_config_for_device(device)
    assert config is not None
    session = OnlineMrSessionStore(page.paths).create_session(config)
    page.last_session_dir_by_device_id[int(device.id)] = session.session_dir
    page._fill_view_devices(prefer_device_id=int(device.id))

    assert page._selected_session_dir_for_parse() == session.session_dir


def test_online_mr_diagnosis_parser_rebuilds_raw_session_tables(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        f"2025-12-03 10:12:30 >>> display clock ; display wlan mesh-link\n{LINE_A}\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "channel_busy_raw.log").write_text(
        "2025-12-03 10:12:31 >>> display clock ; display ar5drv 1 channelbusy\nTxBusy: 11 RxBusy: 22\n"
        "2025-12-03 10:12:32 >>> display clock ; display ar5drv 1 channelbusy\nTxBusy: 11 RxBusy: 22\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "interface_rate_raw.log").write_text(
        "2025-12-03 10:12:33 >>> display clock ; dis counters rate inbound interface\ninterface raw\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "ap_radio_statistics_raw.log").write_text(
        "2025-12-03 10:12:34 >>> display clock ; display ar5drv 1 statistics\n"
        "[Radio Statistics]\n"
        " TxFrameAllCnt       : 100\n"
        " TxFrameAllBytes     : 200\n"
        " RxFrameAllCnt       : 300\n"
        " RxFrameAllBytes     : 400\n"
        " TxRetryFrmCnt       : 5 6 7 8\n"
        " TxErrFrmCnt         : 1 2 3 4\n"
        " TxDiscardFrmCnt     : 9 10 11 12\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "Fping.txt").write_text(
        "10:12:30.500 : Reply[6] from 10.62.90.252: bytes=64 time=4.9 ms TTL=255\n"
        "10:12:31.500 : Request timed out\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "iperf_client_raw.log").write_text(
        "[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.mesh_samples == 1
    assert summary.radio_stats_samples == 1
    assert summary.ping_samples == 2
    assert summary.iperf_samples == 1
    assert summary.active_segments >= 1
    with sqlite3.connect(session.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM fping_samples").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM radio_statistics_samples").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM active_segment_metrics").fetchone()[0] >= 1


def test_online_mr_diagnosis_parser_accepts_stream_rx_raw(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2025-12-03 10:12:30 [collector=repeat] START commands:\n"
        "display clock\n"
        "display wlan mesh-link\n"
        "repeat 2 delay 1\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX display clock\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX [MR-probe]display wlan mesh-link\n"
        f"2025-12-03 10:12:31.001 [collector=repeat] RX {LINE_A}\n"
        "2025-12-03 10:12:32.002 [collector=repeat] RX display clock\n"
        "2025-12-03 10:12:32.002 [collector=repeat] RX [MR-probe]display wlan mesh-link\n"
        f"2025-12-03 10:12:32.002 [collector=repeat] RX {LINE_A}\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.mesh_samples == 2
    with sqlite3.connect(session.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0] >= 2


def _prompted_mesh_stream_block(clock_stamp: str, mesh_stamp: str, rssi: int, active_peer: str = "30f5-277a-169f") -> str:
    return (
        f"{clock_stamp} [collector=repeat] RX <NBL12-LC07-MR-CT>display clock\n"
        f"{clock_stamp} [collector=repeat] RX 20:50:18 BeiJing Mon 07/06/2026\n"
        f"{clock_stamp} [collector=repeat] RX Time Zone : BeiJing add 08:00:00\n"
        f"{mesh_stamp} [collector=repeat] RX <NBL12-LC07-MR-CT>display wlan mesh-link\n"
        f"{mesh_stamp} [collector=repeat] RX  Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        f"{mesh_stamp} [collector=repeat] RX  30f5-277a-1680         {active_peer} {rssi}   74ad-cb9d-318f WLAN-MeshLink881  Active(ax)       00h 21m 36s\n"
        f"{mesh_stamp} [collector=repeat] RX  bc5a-3457-a740         bc5a-3457-a74f 22   74ad-cb9d-318f WLAN-MeshLink434  Standby(ax)      00h 00m 01s\n"
        f"{mesh_stamp} [collector=repeat] RX  bc5a-3457-9f60         bc5a-3457-9f6f 21   74ad-cb9d-318f WLAN-MeshLink429  Standby(ax)      00h 00m 09s\n"
    )


def test_online_mr_diagnosis_parser_splits_prompted_mesh_stream_into_samples(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2026-07-06 20:59:58 [collector=repeat] START commands:\n"
        "display clock\n"
        "display wlan mesh-link\n"
        "repeat 2 delay 1\n"
        + _prompted_mesh_stream_block("2026-07-06 20:59:59.100", "2026-07-06 20:59:59.200", 31)
        + _prompted_mesh_stream_block("2026-07-06 21:00:00.100", "2026-07-06 21:00:00.200", 32)
        + _prompted_mesh_stream_block("2026-07-06 21:00:01.100", "2026-07-06 21:00:01.200", 33),
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.mesh_samples == 3
    with sqlite3.connect(session.db_path) as conn:
        sample_rows = conn.execute(
            """
            SELECT collector_time, device_clock, 'display clock' || char(10) || 'display wlan mesh-link'
            FROM main_link_samples
            WHERE UPPER(link_state) LIKE 'ACTIVE%'
            ORDER BY collector_time
            """
        ).fetchall()
        active_count = conn.execute("SELECT COUNT(*) FROM main_link_samples WHERE UPPER(link_state) LIKE 'ACTIVE%'").fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0]
        segment = conn.execute("SELECT active_peer_mac, start_time, end_time, sample_count, event_type, avg_mr_rssi FROM active_segments").fetchone()
        metadata = conn.execute("SELECT parser_version, row_counts FROM online_parse_metadata WHERE session_id = ?", (session.meta.session_id,)).fetchone()
    assert [row[0] for row in sample_rows] == [
        "2026-07-06 20:59:59.200",
        "2026-07-06 21:00:00.200",
        "2026-07-06 21:00:01.200",
    ]
    assert all(row[1] == "20:50:18 BeiJing Mon 07/06/2026" for row in sample_rows)
    assert all(row[2] == "display clock\ndisplay wlan mesh-link" for row in sample_rows)
    assert active_count == 3
    assert total_count == 9
    assert segment[0] == "30f5277a169f"
    assert segment[1] == "2026-07-06 20:59:59.200"
    assert segment[2] == "2026-07-06 21:00:01.200"
    assert segment[3] == 3
    assert segment[4] == "ACTIVE"
    assert segment[5] == pytest.approx(32.0)
    row_counts = json.loads(metadata[1])
    assert metadata[0] == PARSER_VERSION
    assert row_counts["main_link_sample_count"] == 9
    assert row_counts["active_link_count"] == 3
    assert row_counts["analysis_start"] == "2026-07-06 20:59:59.200"
    assert row_counts["analysis_end"] == "2026-07-06 21:00:01.200"


def test_online_mr_cached_summary_rejects_collapsed_mesh_sample_parse(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        _prompted_mesh_stream_block("2026-07-06 20:59:59.100", "2026-07-06 20:59:59.200", 31)
        + _prompted_mesh_stream_block("2026-07-06 21:00:00.100", "2026-07-06 21:00:00.200", 32),
        encoding="utf-8",
    )
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        conn.execute(
            "INSERT INTO live_samples (session_id, task_type, collected_at, command_group, raw_file, raw_offset_start, raw_offset_end, parse_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session.meta.session_id, TASK_MESH_LINK, "2026-07-06 20:59:59.200", "display clock\ndisplay wlan mesh-link", "raw/mesh_link_raw.log", 0, 9999, "OK"),
        )
        sample_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO live_mesh_links (sample_id, link_state, peer_mac_raw, peer_mac_normalized, local_rssi_db) VALUES (?, ?, ?, ?, ?)", (sample_id, "ACTIVE", "30f5-277a-169f", "30f5277a169f", 31))
        conn.execute(
            "INSERT INTO active_segments (session_id, radio, active_peer_mac, start_time, end_time, sample_count, event_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.meta.session_id, 1, "30f5277a169f,30f5277a169f,30f5277a169f,30f5277a169f,30f5277a169f", "2026-07-06 20:59:59.200", "2026-07-06 20:59:59.200", 1, "MULTI_ACTIVE"),
        )
        conn.execute(
            "INSERT INTO online_parse_metadata (session_id, parsed_at, parser_version, raw_fingerprint, row_counts, status, error_summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session.meta.session_id,
                "2026-07-06 21:03:00.000",
                PARSER_VERSION,
                parser.raw_fingerprint(),
                json.dumps({"mesh_samples": 1, "main_link_sample_count": 1}, ensure_ascii=False),
                "OK",
                "",
            ),
        )

    assert OnlineMrDiagnosisParser(session.session_dir).cached_summary_if_valid() is None
    assert OnlineMrDiagnosisParser(session.session_dir).cache_status() == "stale"


def test_online_mr_mesh_detail_table_defaults_to_active_links(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        _prompted_mesh_stream_block("2026-07-06 20:59:59.100", "2026-07-06 20:59:59.200", 31)
        + _prompted_mesh_stream_block("2026-07-06 21:00:00.100", "2026-07-06 21:00:00.200", 32),
        encoding="utf-8",
    )

    loaded = page._load_mesh_link_details(session.session_dir)

    assert loaded == 2
    assert page.mesh_table.rowCount() == 2
    assert [page.mesh_table.item(row, 1).text() for row in range(2)] == [
        "2026-07-06 20:59:59.200",
        "2026-07-06 21:00:00.200",
    ]
    assert [page.mesh_table.item(row, 2).text() for row in range(2)] == [
        "2026-07-06 20:59:59.200",
        "2026-07-06 21:00:00.200",
    ]
    assert [page.mesh_table.item(row, 4).text() for row in range(2)] == ["ACTIVE", "ACTIVE"]


def test_online_mr_link_detail_table_loads_all_link_states(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-06 20:59:59.200", link_state="ACTIVE", peer_mac="30f5-277a-2f8f", online_time="00h 43m 04s")
        _insert_main_link_sample(conn, session.meta.session_id, "2026-07-06 20:59:59.200", link_state="STANDBY", peer_mac="30f5-277a-3bef", online_time="00h 43m 07s")

    assert page._load_mesh_link_detail_records(session.session_dir) == 2
    headers = [page.mesh_detail_table.horizontalHeaderItem(column).text() for column in range(page.mesh_detail_table.columnCount())]
    assert page.mesh_detail_table.columnCount() == 15
    assert "Radio模式" not in headers
    assert [page.mesh_detail_table.item(row, 0).text() for row in range(2)] == ["1", "2"]
    assert [page.mesh_detail_table.item(row, 4).text() for row in range(2)] == ["ACTIVE", "STANDBY"]
    assert [page.mesh_detail_table.item(row, 14).text() for row in range(2)] == ["00h 43m 04s", "00h 43m 07s"]


def test_online_mr_diagnosis_parser_writes_mesh_online_time(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2026-07-07 01:29:30 >>> display wlan mesh-link\n"
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        "                        4ce9-e4ef-aae0 30   5cf7-9605-960f WLAN-MeshLink24   Standby(a)       00h 43m 07s\n"
        "                        4ce9-e4f1-b880 53   5cf7-9605-960f WLAN-MeshLink25   Active(a)        00h 43m 04s\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.mesh_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        rows = conn.execute(
            "SELECT link_state, peer_mac, online_time FROM main_link_samples ORDER BY link_state ASC"
        ).fetchall()
        parser_version = conn.execute("SELECT parser_version FROM online_parse_metadata WHERE session_id = ?", (session.meta.session_id,)).fetchone()[0]
    assert rows == [
        ("ACTIVE", "4ce9-e4f1-b880", "00h 43m 04s"),
        ("STANDBY", "4ce9-e4ef-aae0", "00h 43m 07s"),
    ]
    assert parser_version == PARSER_VERSION


def test_online_mr_fping_1s_summary_table_loads_rows(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    parser = OnlineMrDiagnosisParser(session.session_dir)
    parser._ensure_tables()
    with sqlite3.connect(session.db_path) as conn:
        _insert_fping_sample(conn, session.meta.session_id, "2026-07-07 01:29:19.341", target_ip="172.28.29.45", success=1, latency_ms=1.1)

    assert page._load_fping_1s_details(session.session_dir) == 1
    headers = [page.fping_1s_table.horizontalHeaderItem(column).text() for column in range(page.fping_1s_table.columnCount())]
    assert "时间" in headers or "Time" in headers
    assert "设备对齐时间" in headers
    assert "本地时间" in headers
    assert page.fping_1s_table.item(0, 0).text() == "1"
    assert page.fping_1s_table.item(0, 4).text() == "172.28.29.45"
    assert page.fping_1s_table.item(0, 14).text() == "正常"


def test_online_mr_diagnosis_parser_accepts_stream_channel_busy_table(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "channel_busy_raw.log").write_text(
        "2025-12-03 10:12:30 [collector=repeat] START commands:\n"
        "display clock\n"
        "display ar5drv 1 channelbusy\n"
        "repeat 2 delay 9\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX display clock\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX 03:05:13 BeiJing Tue 07/07/2026\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX [MR-probe]display ar5drv 1 channelbusy\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX ChannelBusy information\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX        Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX  01     03:05:07         81          2         77          -\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX  02     03:04:58         82          3         78          -\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.channel_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute("SELECT device_time, ctl_busy, tx_busy, rx_busy FROM channel_busy_records").fetchone()
        count = conn.execute("SELECT COUNT(*) FROM channel_busy_records").fetchone()[0]
    assert row == ("2026-07-07 03:05:07", 81, 2, 77)
    assert count == 1


def test_online_mr_diagnosis_parser_groups_fping_v5_by_target(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "fping_v5_samples.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"ts": "2026-06-27T04:58:18.793", "target": "10.122.6.249", "seq": 0, "ok": True, "rtt_ms": 65.6, "timeout_ms": 100, "size": 64, "error": "", "backend": "fping_v5_json", "raw_type": "resp"}),
                json.dumps({"ts": "2026-06-27T04:58:18.803", "target": "10.122.6.250", "seq": 0, "ok": False, "rtt_ms": None, "timeout_ms": 100, "size": 64, "error": "timeout", "backend": "fping_v5_json", "raw_type": "timeout"}),
                json.dumps({"ts": "2026-06-27T04:58:19.793", "target": "10.122.6.249", "seq": 1, "ok": True, "rtt_ms": 70.0, "timeout_ms": 100, "size": 64, "error": "", "backend": "fping_v5_json", "raw_type": "resp"}),
            ]
        ),
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.ping_samples == 3
    with sqlite3.connect(session.db_path) as conn:
        rows = conn.execute(
            """
            SELECT target_ip, SUM(sent), SUM(received), SUM(sent - received), AVG(loss_percent), MAX(max_latency_ms)
            FROM fping_1s_summary
            GROUP BY target_ip
            ORDER BY target_ip
            """
        ).fetchall()
    assert rows == [
        ("10.122.6.249", 2, 2, 0, 0.0, 70.0),
        ("10.122.6.250", 1, 0, 1, 100.0, None),
    ]


def test_online_mr_diagnosis_parser_falls_back_to_fping_v5_raw_log(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "fping_v5_raw.log").write_text(
        "\n".join(
            [
                '2026-07-07T01:29:19.341 {"resp": {"host": "172.28.29.45", "seq": 0, "size": 64, "rtt": 1.10}}',
                '2026-07-07T01:29:19.382 {"timeout": {"host": "172.28.29.45", "seq": 1}}',
            ]
        ),
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.ping_samples == 2
    with sqlite3.connect(session.db_path) as conn:
        rows = conn.execute("SELECT collector_time, target_ip, seq, success, latency_ms FROM fping_samples ORDER BY seq").fetchall()
        summary_row = conn.execute(
            """
            SELECT target_ip, SUM(sent), SUM(received), SUM(sent - received), AVG(loss_percent), MAX(max_latency_ms)
            FROM fping_1s_summary
            GROUP BY target_ip
            """
        ).fetchone()
    assert rows == [
        ("2026-07-07 01:29:19.341", "172.28.29.45", 0, 1, 1.1),
        ("2026-07-07 01:29:19.382", "172.28.29.45", 1, 0, None),
    ]
    assert summary_row == ("172.28.29.45", 2, 1, 1, 50.0, 1.1)


def test_online_mr_estimates_device_time_from_local_offset() -> None:
    sample = TimeSyncSample(
        collector_time=datetime(2026, 7, 7, 2, 32, 58, 532000),
        device_time=datetime(2026, 7, 7, 2, 33, 0),
        offset_ms=1468.0,
        source="mesh_link_display_clock",
    )

    aligned, offset_ms, source = estimate_device_time_from_local(datetime(2026, 7, 7, 2, 32, 58, 532000), [sample])

    assert aligned == datetime(2026, 7, 7, 2, 33, 0)
    assert offset_ms == 1468.0
    assert source == "first_sample"


def test_online_mr_diagnosis_parser_aligns_fping_raw_with_mesh_clock(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2026-07-07 01:29:17.532 [collector=repeat] RX <MR>display clock\n"
        "2026-07-07 01:29:17.532 [collector=repeat] RX 01:29:19 BeiJing Tue 07/07/2026\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "fping_v5_raw.log").write_text(
        '2026-07-07T01:29:19.341 {"resp": {"host": "172.28.29.45", "seq": 0, "size": 64, "rtt": 1.10}}\n',
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.ping_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        sync_row = conn.execute("SELECT collector_time, device_time, offset_ms, source FROM time_sync_samples").fetchone()
        fping_row = conn.execute(
            "SELECT local_time, device_aligned_time, clock_offset_ms, offset_source FROM fping_samples"
        ).fetchone()
    assert sync_row == ("2026-07-07 01:29:17.532", "2026-07-07 01:29:19.000", 1468.0, "mesh_link_display_clock")
    assert fping_row == ("2026-07-07 01:29:19.341", "2026-07-07 01:29:20.809", 1468.0, "last_sample")


def test_online_mr_diagnosis_parser_aligns_iperf_with_mesh_clock(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    session.meta.started_at = datetime(2026, 7, 7, 1, 29, 19)
    session.write_meta()
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2026-07-07 01:29:17.532 [collector=repeat] RX <MR>display clock\n"
        "2026-07-07 01:29:17.532 [collector=repeat] RX 01:29:19 BeiJing Tue 07/07/2026\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "iperf_client_raw.log").write_text(
        "[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.iperf_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute(
            """
            SELECT collector_time, interval_center_time, device_aligned_time,
                   device_interval_center_time, clock_offset_ms, offset_source, time_source
            FROM iperf_intervals
            """
        ).fetchone()
    assert row is not None
    assert row[0]
    assert row[1:] == (
        "2026-07-07 01:29:19.500",
        "2026-07-07 01:29:20.968",
        "2026-07-07 01:29:20.968",
        1468.0,
        "last_sample",
        "mr_device_clock_aligned",
    )


def test_online_mr_diagnosis_parser_keeps_fping_local_time_without_offset(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "fping_v5_raw.log").write_text(
        '2026-07-07T01:29:19.341 {"resp": {"host": "172.28.29.45", "seq": 0, "size": 64, "rtt": 1.10}}\n',
        encoding="utf-8",
    )

    OnlineMrDiagnosisParser(session.session_dir).parse()

    with sqlite3.connect(session.db_path) as conn:
        fping_row = conn.execute(
            "SELECT local_time, device_aligned_time, clock_offset_ms, offset_source FROM fping_samples"
        ).fetchone()
        summary_row = conn.execute("SELECT bucket_time, local_bucket_time, device_bucket_time FROM fping_1s_summary").fetchone()
    assert fping_row == ("2026-07-07 01:29:19.341", None, None, "none")
    assert summary_row == ("2026-07-07 01:29:19", "2026-07-07 01:29:19", None)


def test_online_mr_diagnosis_parser_groups_fping_by_device_bucket(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        "2026-07-07 01:29:17.532 [collector=repeat] RX <MR>display clock\n"
        "2026-07-07 01:29:17.532 [collector=repeat] RX 01:29:19 BeiJing Tue 07/07/2026\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "fping_v5_raw.log").write_text(
        "\n".join(
            [
                '2026-07-07T01:29:19.341 {"resp": {"host": "172.28.29.45", "seq": 0, "size": 64, "rtt": 1.10}}',
                '2026-07-07T01:29:19.382 {"resp": {"host": "172.28.29.45", "seq": 1, "size": 64, "rtt": 1.20}}',
                '2026-07-07T01:29:19.414 {"resp": {"host": "172.28.29.45", "seq": 2, "size": 64, "rtt": 1.30}}',
            ]
        ),
        encoding="utf-8",
    )

    OnlineMrDiagnosisParser(session.session_dir).parse()

    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute(
            "SELECT local_bucket_time, device_bucket_time, sent, received, avg_latency_ms FROM fping_1s_summary"
        ).fetchone()
    assert row == ("2026-07-07 01:29:19", "2026-07-07 01:29:20", 3, 3, 1.2)


def test_online_mr_diagnosis_parser_finds_alternate_switch_history_filename(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh-link switch-history.txt").write_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        " bc5a-3457-cde0         bc5a-3457-cdef(A) N/A               54/0        06-27 20:32:35 01h 07m 41s\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.switch_history_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute("SELECT switch_reason_text, new_peer_mac FROM switch_history_events").fetchone()
    assert row == ("N/A", "bc5a-3457-cdef")


def test_online_mr_diagnosis_parser_keeps_active_logs_terminal_only(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "terminal_monitor_raw.log").write_text(
        "%Jul  3 19:19:27:496 2026 NBL12-LC05-MR-CT WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from bc5a-3457-cbe0_bc5a-3457-cbef(33) to bc5a-3457-cc60_bc5a-3457-cc6f(41): "
        "peer quantity = 14, link quantity = 3, switch reason = 2.\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "switch_history_latest.log").write_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        " bc5a-3457-cbe0         bc5a-3457-cbef(A) Better RSSI       33/27       07-03 19:19:26 00h 00m 01s\n"
        " bc5a-3457-cc60         bc5a-3457-cc6f(A) Better RSSI       41/33       07-03 19:19:28 00h 00m 01s\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.active_link_switch_logs == 1
    assert summary.switch_history_samples == 2
    with sqlite3.connect(session.db_path) as conn:
        terminal_row = conn.execute(
            """
            SELECT time_source, device_time, device_name, old_peer_name, old_peer_mac, old_rssi,
                   new_peer_name, new_peer_mac, new_rssi, peer_quantity, link_quantity,
                   switch_reason_code, switch_reason_text
            FROM switch_realtime_events
            WHERE time_source = 'device_event_time'
            """
        ).fetchone()
        switch_history_event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM switch_history_events
            """
        ).fetchone()[0]
        active_sources = conn.execute("SELECT DISTINCT time_source FROM switch_realtime_events").fetchall()
    assert terminal_row == (
        "device_event_time",
        "2026-07-03 19:19:27.496",
        config.device_name,
        "bc5a-3457-cbe0",
        "bc5a-3457-cbef",
        33,
        "bc5a-3457-cc60",
        "bc5a-3457-cc6f",
        41,
        14,
        3,
        2,
        "主动切换（未开启移动链路优化）",
    )
    assert switch_history_event_count == 2
    assert active_sources == [("device_event_time",)]


def test_online_mr_diagnosis_parser_writes_empty_link_without_resolver(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "terminal_monitor_raw.log").write_text(
        "%Jul  3 19:19:27:496 2026 NBL12-LC05-MR-CT WMESH/5/MESH_ACTIVELINK_SWITCH: "
        "Switch an active link from NA_0000-0000-0000(0) to bc5a-3457-cc60_bc5a-3457-cc6f(41): "
        "peer quantity = 14, link quantity = 3, switch reason = 1.\n",
        encoding="utf-8",
    )

    OnlineMrDiagnosisParser(session.session_dir).parse()

    with sqlite3.connect(session.db_path) as conn:
        row = conn.execute(
            """
            SELECT old_peer_name, old_peer_mac, old_rssi, old_belong_station
            FROM switch_realtime_events
            WHERE time_source = 'device_event_time'
            """
        ).fetchone()
    assert row == ("空链路", None, None, "-")


def test_online_mr_switch_history_never_populates_active_link_switch_logs(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "switch_history_latest.log").write_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        "                        0000-0000-0000(A) Link establish    0 /0        07-03 19:19:26 00h 00m 01s\n",
        encoding="utf-8",
    )

    OnlineMrDiagnosisParser(session.session_dir).parse()

    with sqlite3.connect(session.db_path) as conn:
        active_count = conn.execute("SELECT COUNT(*) FROM switch_realtime_events").fetchone()[0]
        switch_history_event_count = conn.execute("SELECT COUNT(*) FROM switch_history_events").fetchone()[0]
    builder = OnlineMrChartBuilder(session.db_path)
    chart = builder.build_switch_rssi_series()
    log_chart = builder.build_switch_log_rssi_series()

    assert active_count == 0
    assert switch_history_event_count == 1
    assert chart.series[1].points == []
    assert log_chart.series[0].points == []
    assert log_chart.series[1].points == []


def test_online_mr_diagnosis_parser_skips_locked_fping_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
        f"2025-12-03 10:12:30 >>> display clock ; display wlan mesh-link\n{LINE_A}\n",
        encoding="utf-8",
    )
    (session.session_dir / "raw" / "Fping.txt").write_text("locked", encoding="utf-8")

    import netconsole.services.rail_transit.online_mr_diagnosis_parser as parser_module

    original_reader = parser_module.read_text_with_retry

    def fake_reader(path: Path, *args, **kwargs):
        if path.name == "Fping.txt":
            raise PermissionError("locked")
        return original_reader(path, *args, **kwargs)

    monkeypatch.setattr(parser_module, "read_text_with_retry", fake_reader)

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.mesh_samples == 1
    assert summary.ping_samples == 0
    assert summary.issues >= 1


def test_online_mr_realtime_page_hides_offline_parse_controls(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    assert page.analysis_only is False
    assert page.view_row.parentWidget() is None
    assert page.parse_session_button.parentWidget() is page.view_row
    assert page.tabs.count() == 3

    from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

    analysis = OnlineMrCollectionAnalysisPage(page.repository, I18n("en_US"), "demo", page.paths)
    assert analysis.analysis_only is True
    assert analysis.view_row.parentWidget() is not None
    assert analysis.parse_session_button.parentWidget() is analysis.view_row
    tab_names = [analysis.tabs.tabText(index) for index in range(analysis.tabs.count())]
    assert "Link Details" in tab_names or "链路明细" in tab_names
    assert "fping 1s聚合" in tab_names or "fping 1s Summary" in tab_names


def test_online_mr_analysis_filters_and_selects_session_combo(tmp_path: Path) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)
    first_paths, first_config = _config(tmp_path)
    second_config = OnlineMrConnectionConfig(
        site="demo",
        mr_id="mr-02",
        mr_name="MR-02",
        safe_mr_name="MR-02",
        device_id=2,
        device_name="FAT-AP-02",
        host="198.51.100.20",
        username="admin",
        password="secret",
    )
    first_session = OnlineMrSessionStore(first_paths).create_session(first_config, datetime(2026, 1, 1, 8, 0, 0))
    second_session = OnlineMrSessionStore(first_paths).create_session(second_config, datetime(2026, 1, 1, 9, 0, 0))

    from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

    analysis = OnlineMrCollectionAnalysisPage(page.repository, I18n("en_US"), "demo", page.paths)
    analysis.refresh_all()
    _process_qt_until(lambda: not analysis._device_refresh_job_id)
    _process_qt_until(lambda: analysis.history_load_worker is None)

    assert analysis.session_select_combo.count() == 2
    analysis.session_search_input.setText("198.51.100.20")
    analysis._refresh_session_select_combo()

    assert analysis.session_select_combo.count() == 1
    assert analysis.session_select_combo.currentData() == str(second_session.session_dir)
    assert analysis._selected_session_dir_for_parse() == second_session.session_dir
    assert first_session.session_dir != second_session.session_dir


def test_online_mr_analysis_parse_requires_explicit_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, _repository, _groups = _online_page_with_devices(tmp_path)

    from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

    analysis = OnlineMrCollectionAnalysisPage(page.repository, I18n("en_US"), "demo", page.paths)
    warnings: list[str] = []
    monkeypatch.setattr(
        "netconsole.ui.pages.online_mr_collection_page.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    analysis.parse_selected_session()

    assert warnings == ["Select a collection session first."]


def test_online_mr_device_search_filters_and_keeps_checked_devices(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("\u8f66\u8f7d-MR")
    first = _create_onboard_device(repository, onboard.id, "MR-07")
    second = _create_onboard_device(repository, onboard.id, "MR-19")
    page.refresh_all()

    first_row = next(row for row, device in enumerate(page.filtered_devices) if device.id == first.id)
    page.device_table.item(first_row, 0).setCheckState(Qt.Checked)
    assert first.id in page.selected_device_ids

    page.device_search_input.setText("MR-19")
    assert [device.id for device in page.filtered_devices] == [second.id]
    assert first.id in page.selected_device_ids

    page.device_search_input.clear()
    restored_row = next(row for row, device in enumerate(page.filtered_devices) if device.id == first.id)
    assert page.device_table.item(restored_row, 0).checkState() == Qt.Checked


def test_online_mr_pending_worker_failure_and_stop_all_are_device_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    monkeypatch.setattr("netconsole.ui.pages.online_mr_collection_page.QMessageBox.warning", lambda *_args: None)
    onboard = groups.create("\u8f66\u8f7d")
    device = _create_onboard_device(repository, onboard.id, "MR-01")
    page.refresh_all()

    class FakePendingWorker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    worker = FakePendingWorker()
    page.workers_by_device_id[int(device.id)] = worker
    page.manager.register_device(int(device.id), worker)
    assert page.manager.running_count() == 1

    page._upsert_summary(SimpleNamespace(session_id="pending-session"))
    assert page.summary_table.rowCount() == 0

    page.stop_all()
    assert worker.cancelled is True

    page.workers_by_device_id[int(device.id)] = worker
    page.manager.register_device(int(device.id), worker)
    page._worker_failed("connect failed", int(device.id))
    assert int(device.id) not in page.workers_by_device_id
    assert page.manager.running_count() == 0
