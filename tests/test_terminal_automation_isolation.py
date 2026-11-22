from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import ModuleType

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services import netmiko_connection
from netconsole.services.device_activity import device_write_resource_key
from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_workspace import TerminalSessionManager


class _TerminalTransport:
    def __init__(self) -> None:
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.writes: list[str] = []

    def connect(self, _cols: int, _rows: int) -> None:
        self.connected.set()

    def read(self, _maximum: int = 65536) -> str:
        return ""

    def write(self, data: str) -> None:
        self.writes.append(data)

    def resize(self, _cols: int, _rows: int) -> None:
        return None

    def close(self) -> None:
        self.closed.set()


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("demo", display_name="Demo")
    return paths


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_interactive_terminal_and_netmiko_automation_keep_independent_connections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    terminal_transport = _TerminalTransport()
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport",
        lambda *_args, **_kwargs: terminal_transport,
    )

    automation_entered = threading.Event()
    automation_release = threading.Event()
    automation_connection = object()
    netmiko_module = ModuleType("netmiko")

    def fake_connect_handler(**_kwargs):
        automation_entered.set()
        assert automation_release.wait(timeout=3)
        return automation_connection

    netmiko_module.ConnectHandler = fake_connect_handler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "netmiko", netmiko_module)

    paths = _paths(tmp_path)
    manager = TerminalSessionManager(paths)
    session, _ticket = manager.create_quick_session(
        {
            "name": "LAB-SW",
            "host": "192.0.2.10",
            "port": 22,
            "protocol": "SSH",
            "username": "operator",
            "encoding": "utf-8",
            "vendor": "H3C",
            "device_type": "SW",
        },
        password="terminal-secret",
    )
    assert terminal_transport.connected.wait(timeout=3)
    assert _wait_until(
        lambda: manager.get_runtime(session["session_id"]).snapshot.state == "RUNNING"
    )

    automation_result: list[object] = []
    automation_thread = threading.Thread(
        target=lambda: automation_result.append(
            netmiko_connection.ConnectHandler(
                device_type="",
                host="192.0.2.10",
                username="collector",
                password="automation-secret",
            )
        )
    )
    automation_thread.start()
    assert automation_entered.wait(timeout=3)

    now = utc_now_iso()
    TaskRepository(paths.site_tasks_db_path("demo")).save(
        TaskSnapshot(
            task_id="automation-write-a",
            task_type="config_push",
            task_name="配置下发",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            site_name="demo",
            resource_keys=[
                device_write_resource_key("demo", str(session["device_uuid"]))
            ],
        )
    )
    refreshed = manager.list_active()[0]
    assert refreshed["automation_write_active"] is True
    assert refreshed["automation_write_task_id"] == "automation-write-a"

    manager.input(session["session_id"], "display version\r")
    assert _wait_until(lambda: terminal_transport.writes == ["display version\r"])
    manager.close_session(session["session_id"])
    assert terminal_transport.closed.wait(timeout=3)
    assert automation_thread.is_alive()

    automation_release.set()
    automation_thread.join(timeout=3)
    assert automation_result == [automation_connection]
    assert terminal_transport is not automation_connection
    manager.close()
