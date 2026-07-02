from __future__ import annotations

import json
import sqlite3
import sys
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTableWidgetItem

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import (
    CONFIG_COLLECT_COMMANDS,
    FpingConfig,
    INIT_COMMANDS,
    STATE_ABORTED,
    STATE_COLLECTING,
    STATE_CONNECTING,
    STATE_RECONNECTING,
    STATE_STOPPED,
    TASK_CHANNEL_BUSY,
    TASK_AP_RADIO_STATISTICS,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
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
from netconsole.services.online_mr_collector import NetmikoShellConnection, RepeatSshSession
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.network_tools.iperf_parser import parse_iperf_lines, read_iperf_text
from netconsole.services.online_mr_parser import parse_ap_radio_statistics_text, parse_channel_busy_text, parse_mesh_link_text, parse_switch_history_text
from netconsole.services.online_mr.core.event_model import EVENT_BUSY_SAMPLE, EVENT_FPING_V5_SAMPLE, EVENT_LINK_SWITCH, EVENT_MESH_SAMPLE, OnlineMrEvent
from netconsole.services.online_mr.core.realtime_model import RealtimeAggregator, build_realtime_state
from netconsole.services.online_mr.core.realtime_cache import OnlineMrRawEvent, OnlineMrRealtimeCache
from netconsole.services.online_mr.core.realtime_parser import OnlineMrRealtimeParser
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.ui.pages.online_mr_collection_page import (
    OnlineMrCollectionPage,
    SUMMARY_COL_ACTIVE_PEER,
    SUMMARY_COL_DEVICE_ID,
    SUMMARY_COL_LAST_COLLECTION,
    SUMMARY_COL_MR_RSSI,
    SUMMARY_COL_PEER_SITE,
    SUMMARY_COL_PING_LATENCY,
    SUMMARY_COL_SESSION,
    SUMMARY_COL_STATUS,
    is_fat_ap_device,
    natural_device_sort_key,
    safe_device_folder_name,
)
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr_collector import OnlineMrCollectionManager, OnlineMrCollector
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser
from netconsole.ui.pages.online_mr_collection_page import OnlineMrUiThrottle
from netconsole.services.online_mr.workers.fping_v5_worker import FpingV5ProbeWorker
from netconsole.ui.online_mr_collector_worker import OnlineMrCollectorWorker


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
    assert saved_meta["raw_log_path"] == str(collector.session.session_dir / "raw" / "terminal_monitor_raw.txt")
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
    assert saved_meta["raw_log_path"] == str(collector.session.session_dir / "raw" / "terminal_monitor_raw.txt")
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


def test_terminal_monitor_raw_receives_collector_raw_output(tmp_path: Path) -> None:
    collector, _ = _collector(tmp_path)
    collector.start()
    collector.run_once(TASK_MESH_LINK)

    terminal_raw = collector.session.session_dir / "raw" / "terminal_monitor_raw.txt"
    text = terminal_raw.read_text(encoding="utf-8")
    assert "display wlan mesh-link" in text
    assert LINE_A in text


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


def test_collector_worker_cancel_only_requests_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, config = _config(tmp_path)
    calls: list[str] = []

    class FakeCollector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request_stop(self) -> None:
            calls.append("request_stop")

        def stop(self) -> None:
            calls.append("stop")

    monkeypatch.setattr("netconsole.ui.online_mr_collector_worker.OnlineMrCollector", FakeCollector)
    worker = OnlineMrCollectorWorker(config, OnlineMrSessionStore(paths))

    worker.cancel()

    assert calls == ["request_stop"]


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


def test_channel_busy_parser_uses_first_01_table_row() -> None:
    rows = parse_channel_busy_text(
        "Date/Month/Year: 26/06/2026\n"
        "      Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
        "01     22:08:24          4          1          3          -\n"
        "01     22:08:33          7          5          6          -\n"
    )

    assert rows == [
        {
            "radio": 1,
            "tx_busy": 1,
            "rx_busy": 3,
            "raw_text": "01     22:08:24          4          1          3          -",
            "sample_time": "2026-06-26 22:08:24",
            "ctl_busy": 4,
        }
    ]


def test_channel_busy_parser_does_not_allow_02_to_override_01() -> None:
    rows = parse_channel_busy_text(
        "Date/Month/Year: 27/06/2026\n"
        "      Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
        "01     02:22:52          7          4          3          -\n"
        "02     02:22:43          4          1          3          -\n"
    )

    assert rows[0]["ctl_busy"] == 7
    assert rows[0]["tx_busy"] == 4
    assert rows[0]["rx_busy"] == 3


def test_switch_history_parser_accepts_h3c_rows() -> None:
    rows = parse_switch_history_text(
        " Peer Name              Peer MAC          Reason            In/Out RSSI Switched At    ActiveTime\n"
        " bc5a-3457-cde0         bc5a-3457-cdef(A) N/A               54/0        06-27 20:32:35 01h 07m 41s\n"
        "                        0000-0000-0000(A) Link establish    0 /0        06-27 20:32:27 00h 00m 07s\n"
        " bc5a-3457-cc60         bc5a-3457-cc7f(A) Active link fault 27/27       06-27 20:32:27 00h 00m 00s\n",
        datetime(2026, 6, 27, 21, 40, 12),
    )

    assert len(rows) == 3
    assert rows[0]["switch_time"] == "2026-06-27 20:32:35"
    assert rows[0]["to_peer_name"] == "bc5a-3457-cde0"
    assert rows[0]["to_peer_mac"] == "bc5a-3457-cdef"
    assert rows[0]["to_peer_mac_normalized"] == "bc5a3457cdef"
    assert rows[0]["reason"] == "N/A"
    assert rows[0]["in_rssi"] == 54
    assert rows[1]["to_peer_name"] == ""
    assert rows[1]["reason"] == "Link establish"
    assert rows[2]["reason"] == "Active link fault"


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
    assert state.ctl_busy == 4
    assert state.loss == 0.5
    assert state.rtt == 2.5


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
    assert page.view_device_combo.maximumWidth() <= 360
    assert page.device_table.columnCount() == 9
    assert page.enable_iperf_check.isChecked() is False
    assert page.iperf_bandwidth_unit_combo.currentText() == "M"
    assert page.iperf_bandwidth_hint_label.text()
    assert page.connection_box.maximumHeight() <= 76
    assert page.connection_box.layout().count() >= 10
    assert page.page_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert page.available_device_count_label.parentWidget() is None
    assert page.available_metric_label.text()
    top_layout = page.connection_box.layout()
    assert top_layout.itemAt(top_layout.count() - 1).widget() is page.status_label
    assert top_layout.indexOf(page.refresh_devices_button) < top_layout.indexOf(page.status_label)
    assert page.start_button.minimumWidth() >= 86
    assert page.start_button.minimumHeight() >= 28
    assert page.status_label.minimumWidth() >= 72
    assert page.status_label.maximumWidth() <= 96
    assert page.fping_status_label_1.parentWidget() is None
    assert page.fping_status_label_2.parentWidget() is None
    page._refresh_collection_animation()
    assert page.collect_status_label_1.text().find("Ping 1") >= 0
    assert page.collect_status_label_1.text().find("Ping 2") >= 0
    assert page.collect_param_box.minimumHeight() >= 220
    assert page.collect_param_box.maximumHeight() <= 280
    assert page.advanced_box.minimumWidth() >= 260
    assert page.advanced_box.maximumWidth() <= 320
    assert page.advanced_box.minimumHeight() >= 190
    assert page.advanced_box.maximumHeight() <= 240
    assert page.period_box.layout().columnStretch(1) == 1
    assert page.collect_status_box.title() == "实时采集状态"
    assert page.collect_status_box.minimumHeight() >= 140
    assert page.collect_status_box.maximumHeight() <= 190
    assert page.collect_card_1.parentWidget() is page.collect_status_box
    assert page.collect_card_2.parentWidget() is page.collect_status_box
    assert not page.collect_progress_1.isVisible()
    assert page.device_table.minimumHeight() >= 260
    assert page.device_table.maximumHeight() <= 330
    assert page.device_table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert page.device_table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert page.main_work_panel.layout().columnStretch(0) == 6
    assert page.main_work_panel.layout().columnStretch(1) == 4
    assert page.device_panel.minimumHeight() >= 280
    assert page.right_control_scroll.minimumWidth() >= 560
    assert page.right_control_scroll.maximumWidth() <= 700
    assert page.ping_box.minimumHeight() >= 220
    assert page.ping_box.maximumHeight() <= 280
    assert page.fping_device_combo_1.minimumWidth() >= 220
    assert page.fping_device_combo_1.maximumWidth() <= 360
    assert page.fping_target_label_1.minimumWidth() >= 160
    assert page.fping_target_label_1.maximumWidth() <= 260
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
        SUMMARY_COL_MR_RSSI: 80,
        SUMMARY_COL_PEER_SITE: 120,
        6: 80,
        SUMMARY_COL_PING_LATENCY: 90,
        8: 90,
        9: 90,
        10: 90,
        SUMMARY_COL_LAST_COLLECTION: 160,
        12: 100,
        13: 80,
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
    assert analysis_page.tabs.count() == 11
    assert analysis_page.tabs.tabText(0) == "历史会话"
    assert analysis_page.tabs.tabText(6) == "分析图表"
    assert analysis_page.tabs.tabText(8) == "诊断结果"

    wheel = FakeWheelEvent()
    assert page._no_wheel_filter.eventFilter(page.mesh_interval, wheel) is True
    assert wheel.ignored is True
    combo_wheel = FakeWheelEvent()
    assert page._no_wheel_filter.eventFilter(page.radio_port, combo_wheel) is True
    assert combo_wheel.ignored is True


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


def test_online_mr_summary_binds_station_without_busy_columns(tmp_path: Path) -> None:
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
            OnlineMrEvent(now, "s1", 7, "ssh", "busy", EVENT_BUSY_SAMPLE, {"ctl_busy": 4, "tx_busy": 1, "rx_busy": 3}),
        ],
        sample_count=2,
        resolve_peer=lambda _mac: {"peer_ap_name": "AP-01", "peer_site": "宁波站"},
    )

    page._update_summary_from_state(state)

    headers = [page.summary_table.horizontalHeaderItem(column).text() for column in range(page.summary_table.columnCount())]
    assert page.summary_table.columnCount() == 16
    assert "CtlBusy(%)" not in headers
    assert "TxBusy(%)" not in headers
    assert "RxBusy(%)" not in headers
    assert "Status" not in headers[12:15]
    assert page.summary_table.item(0, 5).text() == "宁波站"
    assert page.summary_table.item(0, 6).text() == "-"
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
    assert headers[SUMMARY_COL_PING_LATENCY] == "Ping延迟"
    assert headers[SUMMARY_COL_LAST_COLLECTION] == "最后采集"
    assert page.summary_table.item(0, SUMMARY_COL_ACTIVE_PEER).text() == "AP-X_3111"
    assert page.summary_table.item(0, SUMMARY_COL_PEER_SITE).text() == "横溪站"


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
    assert page.summary_table.item(0, 4).text() == "35"
    assert page.summary_table.item(0, 11).text().startswith("2026-06-27 10:00:00")


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
    page.iperf_bandwidth_edit.setText("100")
    page.iperf_bandwidth_unit_combo.setCurrentText("M")

    config = page._build_config_for_device(device)
    assert config is not None
    assert config.mr_name == device.name
    assert config.device_id == device.id
    assert config.host == device.ip_address
    assert config.username == "admin"
    assert config.password == "secret"
    assert [target.method for target in config.connection_targets] == ["primary_direct"]
    assert config.iperf.enabled is True
    assert config.iperf.target_bandwidth == "100M"
    assert config.safe_mr_name == safe_device_folder_name(device)
    session = OnlineMrSessionStore(page.paths).create_session(config)
    assert f"__{device.id}" in str(session.session_dir)
    assert "MR_01" in str(session.session_dir)


def test_online_mr_config_includes_tunnel_targets_for_enabled_vehicle_device(tmp_path: Path) -> None:
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
    assert [target.method for target in config.connection_targets] == ["primary_direct", "backup_direct", "tunnel1", "tunnel2"]


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
        assert conn.execute("SELECT COUNT(*) FROM live_mesh_links").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM ping_samples").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM live_events WHERE event_type = 'AP_RADIO_STATS'").fetchone()[0] == 1
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
        assert conn.execute("SELECT COUNT(*) FROM live_mesh_links").fetchone()[0] >= 2


def test_online_mr_diagnosis_parser_accepts_stream_channel_busy_table(tmp_path: Path) -> None:
    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    (session.session_dir / "raw" / "channel_busy_raw.log").write_text(
        "2025-12-03 10:12:30 [collector=repeat] START commands:\n"
        "display clock\n"
        "display ar5drv 1 channelbusy\n"
        "repeat 2 delay 9\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX display clock\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX [MR-probe]display ar5drv 1 channelbusy\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX ChannelBusy information\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX  Date/Month/Year: 26/06/2026\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX        Time(h/m/s):   CtlBusy(%) TxBusy(%)  RxBusy(%)  ExtBusy(%)\n"
        "2025-12-03 10:12:31.001 [collector=repeat] RX  01     22:08:24          4          1          3          -\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session.session_dir).parse()

    assert summary.channel_samples == 1
    with sqlite3.connect(session.db_path) as conn:
        assert conn.execute("SELECT tx_busy, rx_busy FROM live_channel_busy").fetchone() == (1, 3)


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
        rows = conn.execute("SELECT target_ip, sent, received, lost, loss_percent, latest_latency_ms FROM ping_summary ORDER BY target_ip").fetchall()
    assert rows == [
        ("10.122.6.249", 2, 2, 0, 0.0, 70.0),
        ("10.122.6.250", 1, 0, 1, 100.0, None),
    ]


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
        row = conn.execute("SELECT event_type, to_peer_mac FROM live_events WHERE event_type = 'SWITCH_HISTORY'").fetchone()
    assert row == ("SWITCH_HISTORY", "bc5a-3457-cdef")


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
    assert analysis.tabs.count() == 11


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
