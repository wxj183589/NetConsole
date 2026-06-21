from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import (
    INIT_COMMANDS,
    STATE_ABORTED,
    STATE_COLLECTING,
    STATE_RECONNECTING,
    STATE_STOPPED,
    TASK_CHANNEL_BUSY,
    TASK_AP_RADIO_STATISTICS,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    repeat_command_group,
)
from netconsole.services.fping_v3 import (
    aggregate_ping_for_active_segment,
    build_fping_args,
    detect_fping_version,
    find_fping_tool,
    parse_fping_lines,
    parse_fping_summary,
)
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.services.online_mr_collector import RepeatSshSession
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage, is_fat_ap_device, natural_device_sort_key, safe_device_folder_name
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr_collector import OnlineMrCollectionManager, OnlineMrCollector
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser
from netconsole.ui.pages.online_mr_collection_page import OnlineMrUiThrottle


LINE_A = "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def _qt_app():
    return QApplication.instance() or QApplication([])


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
    return OnlineMrCollectionPage(device_repo, I18n("en_US"), "demo", paths), device_repo, group_repo


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


def test_ui_throttle_coalesces_many_snapshots() -> None:
    throttle = OnlineMrUiThrottle(500)
    for index in range(100):
        from netconsole.models.online_mr_models import OnlineMrSnapshot

        throttle.enqueue(OnlineMrSnapshot(str(index), STATE_COLLECTING))
    snapshot = throttle.flush()
    assert snapshot.session_id == "99"
    assert throttle.flush() is None
    assert throttle.flush_count == 1


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
    exe = tmp_path / "tools" / "fping_v3" / "Fping_v3.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")
    assert find_fping_tool(PathResolver(tmp_path)) == exe.resolve()


def test_fping_version_accepts_nonzero_return_code(tmp_path: Path) -> None:
    exe = tmp_path / "Fping_v3.exe"
    exe.write_text("fake", encoding="utf-8")

    def runner(*args, **kwargs):
        class Result:
            stdout = "Fast pinger version 3.00\nHost not found: -v error 11001"
            stderr = ""
            returncode = 1

        return Result()

    status = detect_fping_version(exe, runner=runner)
    assert status.found is True
    assert status.version == "3.00"


def test_fping_command_args_are_list_with_expected_parameters(tmp_path: Path) -> None:
    args = build_fping_args(tmp_path / "Fping_v3.exe", "127.0.0.1", 64, 10, 100, tmp_path / "Fping.txt")
    assert args == [
        str(tmp_path / "Fping_v3.exe"),
        "127.0.0.1",
        "-s",
        "64",
        "-t",
        "10",
        "-c",
        "-w",
        "100",
        "-T",
        "-L",
        str((tmp_path / "Fping.txt").resolve()),
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
        "screen-length disable",
        "display clock",
        "display wlan mesh-link",
        "repeat 2 delay 1",
    )
    assert repeat_command_group(TASK_CHANNEL_BUSY, interval=9, radio_id=1) == (
        "screen-length disable",
        "display clock",
        "display ar5drv 1 channelbusy",
        "repeat 2 delay 9",
    )
    assert "display ar5drv 3 channelbusy" in repeat_command_group(TASK_CHANNEL_BUSY, interval=9, radio_id=3)
    assert repeat_command_group(TASK_AP_RADIO_STATISTICS, interval=10, radio_id=1)[2] == "display ar5drv 1 statistics"
    assert repeat_command_group(TASK_SWITCH_HISTORY, interval=300)[-1] == "repeat 2 delay 300"
    assert repeat_command_group(TASK_INTERFACE_RATE, interval=2) == (
        "screen-length disable",
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
        "Fping.txt",
    }.issubset(raw_names)
    assert "iperf_client_raw.log" not in raw_names


def test_default_online_mr_intervals_and_radio() -> None:
    config = OnlineMrIntervals()
    assert config.mesh_link == 1
    assert config.channel_busy == 9
    assert config.ap_radio_statistics == 10
    assert config.switch_history == 300
    assert config.interface_rate == 2


def test_online_mr_page_uses_card_layout_and_bounded_inputs(tmp_path: Path) -> None:
    _qt_app()
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = OnlineMrCollectionPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)
    assert page.connection_box.title() == "车载MR在线收集"
    assert page.period_box.title() == "采集周期"
    assert page.radio_box.title() == "射频参数"
    assert page.ping_box.title() == "高频Ping"
    assert not hasattr(page, "profile_combo")
    assert not hasattr(page, "device_combo")
    assert not hasattr(page, "host_edit")
    assert page.view_device_combo.maximumWidth() <= 320
    assert page.device_table.columnCount() == 9
    assert page.enable_iperf_check.isChecked() is False
    assert page.iperf_bandwidth_unit_combo.currentText() == "M"
    assert page.iperf_bandwidth_hint_label.text()
    assert page.summary_table.maximumHeight() <= 180
    assert page.tabs.minimumHeight() >= 300
    assert page.tabs.count() == 10
    assert page.tabs.tabText(4) == "接口速率"
    assert page.tabs.tabText(7) == "打流测试"
    assert page.tabs.tabText(8) == "诊断结果"
    assert not page.advanced_detail.isVisible()


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
        page.iperf_duration_spin: page.iperf_duration_spin.value(),
    }
    combo_indexes = {
        page.iperf_protocol_combo: page.iperf_protocol_combo.currentIndex(),
        page.iperf_direction_combo: page.iperf_direction_combo.currentIndex(),
        page.iperf_bandwidth_unit_combo: page.iperf_bandwidth_unit_combo.currentIndex(),
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
    onboard = groups.create("车载")
    other = groups.create("车站")
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
    onboard = groups.create("车载")
    for name in ("256", "10-xxx", "02-xxx", "25ct", "01-xxx"):
        _create_onboard_device(repository, onboard.id, name)
    page.refresh_all()
    assert [device.name for device in page.filtered_devices] == ["01-xxx", "02-xxx", "10-xxx", "25ct", "256"]
    assert sorted(page.filtered_devices, key=natural_device_sort_key) == page.filtered_devices


def test_online_mr_blocks_selecting_more_than_two_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
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
    onboard = groups.create("车载")
    device = _create_onboard_device(repository, onboard.id, 'MR/01:*?"<>|', "FAT AP")
    page.refresh_all()
    page.enable_iperf_check.setChecked(True)
    page.iperf_server_edit.setText("10.0.0.1")
    page.iperf_bandwidth_edit.setText("100")
    page.iperf_bandwidth_unit_combo.setCurrentText("M")

    config = page._build_config_for_device(device)
    assert config is not None
    assert config.mr_name == device.name
    assert config.device_id == device.id
    assert config.host == device.ip_address
    assert config.username == "admin"
    assert config.password == "secret"
    assert config.iperf.enabled is True
    assert config.iperf.target_bandwidth == "100M"
    assert config.safe_mr_name == safe_device_folder_name(device)
    session = OnlineMrSessionStore(page.paths).create_session(config)
    assert f"__{device.id}" in str(session.session_dir)
    assert "MR_01" in str(session.session_dir)


def test_online_mr_skips_incomplete_connection_without_hiding_device(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
    incomplete = repository.create(Device(name="NoPassword", group_id=onboard.id, device_type="FAT-AP", ip_address="192.0.2.50", ssh_enabled=1, ssh_username="admin", ssh_password=""))
    page.refresh_all()

    assert [device.name for device in page.filtered_devices] == ["NoPassword"]
    assert page._build_config_for_device(incomplete) is None


def test_online_mr_stop_selected_and_stop_all_are_device_scoped(tmp_path: Path) -> None:
    page, repository, groups = _online_page_with_devices(tmp_path)
    onboard = groups.create("车载")
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
    assert summary.ping_samples == 2
    assert summary.iperf_samples == 1
    assert summary.active_segments >= 1
    with sqlite3.connect(session.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM live_mesh_links").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM ping_samples").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM active_segment_metrics").fetchone()[0] >= 1
