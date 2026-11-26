from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import ConnectionTarget
from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_workspace import (
    TerminalRecordingWriter,
    TerminalSessionManager,
    TerminalSessionSnapshot,
    TerminalTicketStore,
)


def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class _FakeTransport:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.outputs = ["password=test-secret\r\n<LAB-SW>\r\n"]
        self.lock = threading.Lock()
        self.connected_with: tuple[int, int] | None = None
        self.sizes: list[tuple[int, int]] = []
        self.closed = False

    def connect(self, cols: int, rows: int) -> None:
        self.connected_with = (cols, rows)

    def write(self, value: str) -> None:
        with self.lock:
            self.writes.append(value)
            self.outputs.append(f"{value}<LAB-SW>")

    def read(self, maximum: int = 65536) -> str:
        with self.lock:
            return self.outputs.pop(0) if self.outputs else ""

    def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))

    def close(self) -> None:
        self.closed = True


def _manager_fixture(
    tmp_path: Path, monkeypatch
) -> tuple[TerminalSessionManager, Device, _FakeTransport]:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("terminal-test", display_name="终端测试")
    repository = DeviceRepository(Database(paths.site_db_path("terminal-test")))
    device = repository.create(
        Device(
            name="LAB-SW",
            system_name="LAB-SW",
            primary_address="192.0.2.10",
            ssh_enabled=1,
            ssh_username="operator",
            ssh_password="test-secret",
        )
    )
    target = ConnectionTarget(
        protocol="ssh",
        device_type="hp_comware",
        host="192.0.2.10",
        port=22,
        username="operator",
        password="test-secret",
    )
    transport = _FakeTransport()
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.connection_targets",
        lambda _device: [target],
    )
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport",
        lambda *_args, **_kwargs: transport,
    )
    return TerminalSessionManager(paths), device, transport


def test_explicit_backup_address_creates_an_independent_session(tmp_path, monkeypatch) -> None:
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    from netconsole.services import terminal_workspace

    primary = terminal_workspace.connection_targets(device)[0]
    backup = replace(primary, host="192.0.2.20", port=2222, target_role="backup")
    monkeypatch.setattr(terminal_workspace, "connection_targets", lambda _device: [primary, backup])
    try:
        snapshot, _ = manager.create_session(str(device.device_uuid), protocol="SSH", address_role="backup", cols=144, rows=45)
        _wait_until(lambda: transport.connected_with is not None)
        assert transport.connected_with == (144, 45)
        assert (snapshot["address"], snapshot["port"], snapshot["address_role"]) == ("192.0.2.20", 2222, "backup")
        assert device.primary_address == primary.host
        with pytest.raises(ValueError, match="备用"):
            manager.create_session(str(device.device_uuid), protocol="TELNET", address_role="backup")
    finally:
        manager.close()


def test_closing_session_drains_queued_writes_without_sending_them(tmp_path, monkeypatch) -> None:
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    ready, release = threading.Event(), threading.Event()
    write = transport.write

    def blocking_write(value: str) -> None:
        ready.set()
        assert release.wait(3)
        write(value)

    monkeypatch.setattr(transport, "write", blocking_write)
    snapshot, _ = manager.create_session(str(device.device_uuid))
    session_id = snapshot["session_id"]
    runtime = manager.get_runtime(session_id)
    receipt = {"done": threading.Event(), "error": "", "scope": "single"}
    try:
        _wait_until(lambda: runtime.snapshot.state == "RUNNING")
        manager.input(session_id, "in flight\r")
        assert ready.wait(3)
        manager.input(session_id, "queued\r", receipt=receipt)
        assert manager.close_session(session_id)["state"] == "CLOSING"
        assert manager.close_session(session_id)["state"] == "CLOSING"
        with pytest.raises(ValueError):
            manager.input(session_id, "too late\r")
        assert runtime.snapshot.command_count == 2
        release.set()
        assert receipt["done"].wait(3)
        assert "未发送" in receipt["error"]
    finally:
        release.set()
        manager.close()
    assert runtime.snapshot.state == "CLOSED"
    assert transport.closed
    assert transport.writes == ["in flight\r"]


def test_repeated_close_during_connection_setup_closes_transport_once(tmp_path, monkeypatch) -> None:
    manager, device, _transport_value = _manager_fixture(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()
    created = []

    class _DelayedConnectTransport(_FakeTransport):
        def connect(self, cols: int, rows: int) -> None:
            started.set()
            assert release.wait(3)
            super().connect(cols, rows)

    def make_transport(*_args, **_kwargs):
        transport = _DelayedConnectTransport()
        created.append(transport)
        return transport

    monkeypatch.setattr("netconsole.services.terminal_workspace.create_terminal_transport", make_transport)
    snapshot, ticket = manager.create_session(str(device.device_uuid))
    session_id = snapshot["session_id"]
    try:
        assert started.wait(3)
        cancelled = manager.close_session(session_id)
        assert cancelled["state"] == "CLOSING"
        assert ticket.ticket
        with pytest.raises(ValueError):
            manager.issue_ticket(session_id)
        manager.close_session(session_id)
    finally:
        release.set()
        manager.close()
    assert manager.get_runtime(session_id).snapshot.state == "CLOSED"
    assert len(created) == 1
    assert created[0].closed


def test_terminal_ticket_is_single_use() -> None:
    store = TerminalTicketStore(ttl_seconds=30)
    ticket = store.issue("session-a")

    assert store.consume(ticket.ticket, "session-a") is True
    assert store.consume(ticket.ticket, "session-a") is False
    assert store.consume(store.issue("session-a").ticket, "session-b") is False


def test_terminal_ticket_expires(monkeypatch) -> None:
    now = [1_000_000]
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace._utc_ms", lambda: now[0]
    )
    store = TerminalTicketStore(ttl_seconds=5)
    ticket = store.issue("session-a")
    now[0] += 5_001

    assert store.consume(ticket.ticket, "session-a") is False


def test_terminal_session_passes_interactive_input_and_records_history(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    snapshot, ticket = manager.create_session(
        str(device.device_uuid), cols=132, rows=40
    )
    session_id = str(snapshot["session_id"])

    assert manager.tickets.consume(ticket.ticket, session_id) is True
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")

    interactive_input = ["system-view\r", "save\r", "\x03", "\x1b[A", "\t"]
    for value in interactive_input:
        manager.input(session_id, value)
    manager.resize(session_id, 160, 48)
    _wait_until(lambda: transport.writes == interactive_input)
    _wait_until(lambda: transport.sizes == [(160, 48)])

    assert transport.connected_with == (132, 40)
    assert manager.get_runtime(session_id).snapshot.command_count == 2

    manager.close_session(session_id)
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "CLOSED")

    detail = manager.session_detail(session_id)
    manager.close()
    detail = manager.session_detail(session_id)
    assert detail["recording_status"] == "COMPLETED"
    assert detail["recording_sha256"]
    metadata_text = json.dumps(detail, ensure_ascii=False)
    assert "test-secret" not in metadata_text
    assert "operator" not in metadata_text

    events = manager.recording_events(session_id, limit=2000)
    assert all("at_ms" in event for event in events)
    assert "test-secret" in json.dumps(
        events, ensure_ascii=False
    )  # Real device output is retained.
    assert all(event.get("event_type") != "INPUT_REJECTED" for event in events)
    assert any(
        event.get("event_type") == "INPUT" and event.get("data") == "system-view\r"
        for event in events
    )
    txt_path, _ = manager.export_path(session_id, "txt")
    assert "system-view" in txt_path.read_text(encoding="utf-8")
    assert "save" in txt_path.read_text(encoding="utf-8")
    assert transport.closed is True


def test_terminal_session_replays_bounded_display_backlog_on_reattach(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, _connection = _manager_fixture(tmp_path, monkeypatch)
    snapshot, _ticket = manager.create_session(str(device.device_uuid))
    session_id = str(snapshot["session_id"])
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.output_bytes > 0)

    listener = manager.get_runtime(session_id).subscribe()
    assert listener.get(timeout=1)["type"] == "snapshot"
    backlog = listener.get(timeout=1)

    assert backlog["type"] == "backlog"
    assert "<LAB-SW>" in backlog["data"]
    assert "test-secret" in backlog["data"]

    manager.get_runtime(session_id).unsubscribe(listener)
    manager.close_session(session_id)
    manager.close()


def test_terminal_dangerous_command_warning_never_blocks_transport(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    snapshot, _ticket = manager.create_session(str(device.device_uuid))
    session_id = str(snapshot["session_id"])
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")
    listener = manager.get_runtime(session_id).subscribe()
    assert listener.get(timeout=1)["type"] == "snapshot"

    manager.input(session_id, "reboot\r")
    _wait_until(lambda: "reboot\r" in transport.writes)

    messages = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            messages.append(listener.get(timeout=0.05))
        except Exception:
            pass
        if any(item.get("type") == "risk_warning" for item in messages):
            break
    manager.close_session(session_id)
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "CLOSED")

    assert any(item.get("type") == "risk_warning" for item in messages)
    assert any(
        item.get("event_type") == "RISK" and item.get("command") == "reboot"
        for item in manager.recording_events(session_id, limit=2000)
    )


def test_manual_session_log_has_independent_pause_resume_and_file(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    snapshot, _ticket = manager.create_session(str(device.device_uuid))
    session_id = str(snapshot["session_id"])
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")

    started = manager.start_manual_log(
        session_id, filename="commissioning", log_format="jsonl"
    )
    log_id = str(started["manual_log_id"])
    manager.input(session_id, "display version\r")
    _wait_until(lambda: "display version\r" in transport.writes)
    manager.pause_manual_log(session_id)
    manager.input(session_id, "system-view\r")
    _wait_until(lambda: "system-view\r" in transport.writes)
    manager.resume_manual_log(session_id)
    manager.input(session_id, "save\r")
    _wait_until(lambda: "save\r" in transport.writes)
    stopped = manager.stop_manual_log(session_id)

    log_path, filename = manager.manual_log_export_path(session_id, log_id)
    events = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    recorded_inputs = [item["data"] for item in events if item["event_type"] == "INPUT"]

    assert filename == "commissioning.jsonl"
    assert stopped["manual_log_status"] == "COMPLETE"
    assert recorded_inputs == ["display version\r", "save\r"]
    assert manager.recording_events(session_id, limit=2000)
    manager.close_session(session_id)


def test_terminal_recording_marks_queue_overflow_incomplete(
    tmp_path: Path, monkeypatch
) -> None:
    release = threading.Event()
    original_run = TerminalRecordingWriter._run

    def delayed_run(writer: TerminalRecordingWriter) -> None:
        release.wait(timeout=2)
        original_run(writer)

    monkeypatch.setattr(TerminalRecordingWriter, "_run", delayed_run)
    snapshot = TerminalSessionSnapshot(
        session_id="a" * 32,
        device_uuid="device-a",
        device_name="LAB-SW",
        site_id="site-a",
        site_name="终端测试",
        protocol="SSH",
        encoding="utf-8",
        mode="INTERACTIVE",
        state="RUNNING",
        address="192.0.2.10",
        port=22,
        created_at_ms=1,
        updated_at_ms=1,
    )
    writer = TerminalRecordingWriter(tmp_path, snapshot, queue_size=1)

    assert writer.append("OUTPUT", data="first") is True
    assert writer.append("OUTPUT", data="dropped") is False
    release.set()
    writer.close(snapshot)

    assert snapshot.recording_status == "INCOMPLETE"
    assert snapshot.recording_dropped_events >= 1


def test_terminal_recording_close_does_not_block_when_queue_is_full(
    tmp_path: Path, monkeypatch
) -> None:
    release = threading.Event()
    original_run = TerminalRecordingWriter._run

    def delayed_run(writer: TerminalRecordingWriter) -> None:
        release.wait(timeout=2)
        original_run(writer)

    monkeypatch.setattr(TerminalRecordingWriter, "_run", delayed_run)
    snapshot = TerminalSessionSnapshot(
        session_id="b" * 32,
        device_uuid="device-b",
        device_name="LAB-SW",
        site_id="site-a",
        site_name="终端测试",
        protocol="SSH",
        encoding="utf-8",
        mode="INTERACTIVE",
        state="RUNNING",
        address="192.0.2.10",
        port=22,
        created_at_ms=1,
        updated_at_ms=1,
    )
    writer = TerminalRecordingWriter(tmp_path, snapshot, queue_size=1)
    assert writer.append("OUTPUT", data="first") is True

    closer = threading.Thread(target=writer.close, args=(snapshot,))
    closer.start()
    closer.join(timeout=1)
    release.set()
    closer.join(timeout=3)

    assert closer.is_alive() is False
    assert snapshot.recording_status == "INCOMPLETE"


def test_terminal_session_can_be_cancelled_before_connect_starts(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, _connection = _manager_fixture(tmp_path, monkeypatch)
    release = threading.Event()
    original_run = manager._run_session

    def delayed_run(session) -> None:
        release.wait(timeout=2)
        original_run(session)

    monkeypatch.setattr(manager, "_run_session", delayed_run)
    snapshot, _ticket = manager.create_session(str(device.device_uuid))
    session_id = str(snapshot["session_id"])

    cancelled = manager.close_session(session_id)
    release.set()
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "CLOSED")

    assert cancelled["state"] == "CANCELLED"
    manager.close()
    assert manager.session_detail(session_id)["recording_status"] == "COMPLETED"


def test_terminal_manager_allows_three_independent_sessions_per_device(
    tmp_path: Path, monkeypatch
) -> None:
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    transports = []

    def factory(*args, **kwargs):
        transport = _FakeTransport()
        transports.append(transport)
        return transport

    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport", factory
    )
    first, _ = manager.create_session(str(device.device_uuid))
    second, _ = manager.clone_session(first["session_id"])
    third, _ = manager.clone_session(first["session_id"])
    ids = [item["session_id"] for item in (first, second, third)]
    try:
        assert len(set(ids)) == 3
        assert [item["session_name"] for item in (first, second, third)] == [
            "LAB-SW-01",
            "LAB-SW-02",
            "LAB-SW-03",
        ]
        for index, session_id in enumerate(ids):
            _wait_until(
                lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING"
            )
            manager.input(session_id, f"display unique-{index}\r")
        _wait_until(lambda: all(item.writes for item in transports))
        manager.close_session(ids[0])
        _wait_until(lambda: transports[0].closed)
        assert not transports[1].closed and not transports[2].closed
        manager.input(ids[1], "display alive\r")
    finally:
        manager.close()
    names = set()
    for index, session_id in enumerate(ids):
        log, _ = manager.export_path(session_id, "log")
        text = log.read_text(encoding="utf-8")
        assert f"unique-{index}" in text
        assert all(
            f"unique-{other}" not in text for other in range(3) if other != index
        )
        names.add(log.name)
    assert len(names) == 3


def test_quick_connect_uses_an_unmanaged_interactive_transport_and_reconnects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("terminal-quick", display_name="快速连接")
    transports: list[_FakeTransport] = []
    calls: list[dict[str, object]] = []

    def create_transport(*_args, **kwargs):
        transport = _FakeTransport()
        transports.append(transport)
        calls.append(kwargs)
        return transport

    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport",
        create_transport,
    )
    manager = TerminalSessionManager(paths)
    created, _ticket = manager.create_quick_session(
        {
            "name": "临时交换机",
            "host": "192.0.2.55",
            "port": 22,
            "protocol": "SSH",
            "username": "operator",
            "encoding": "gb18030",
            "vendor": "H3C",
            "device_type": "SW",
        },
        password="quick-secret",
    )
    session_id = str(created["session_id"])
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")

    assert created["encoding"] == "gb18030"
    assert created["device_uuid"].startswith("terminal-quick-")
    assert calls[0]["managed_device"] is False
    assert manager.get_runtime(session_id).target.method == "terminal_quick_connect"

    manager.close_session(session_id)
    _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "CLOSED")
    reconnected, _ticket = manager.reconnect(session_id)
    second_id = str(reconnected["session_id"])
    _wait_until(lambda: manager.get_runtime(second_id).snapshot.state == "RUNNING")

    assert second_id != session_id
    assert len(transports) == 2
    assert calls[1]["managed_device"] is False
    with pytest.raises(ValueError, match="已有"):
        manager.reconnect(session_id)
    assert len(transports) == 2
    manager.close_session(second_id)
    manager.close()
