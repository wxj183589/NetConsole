from __future__ import annotations

import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from netconsole.core.shutdown_manager import ShutdownManager
from netconsole.ui.window_registry import WindowRegistry


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class FakeTask:
    def __init__(self, name: str = "task") -> None:
        self.name = name
        self.stop_requested = False
        self.running = True
        self.wait_calls = 0

    def request_stop(self) -> None:
        self.stop_requested = True

    def is_running(self) -> bool:
        return self.running

    def wait(self, timeout: float) -> bool:
        self.wait_calls += 1
        self.running = False
        return True


class FakeProcess:
    def __init__(self, pid: int = 1001) -> None:
        self.pid = pid
        self.args = ["fake.exe"]
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None):
        if self.terminated:
            self.returncode = 0
            return 0
        raise subprocess.TimeoutExpired(self.args, timeout)


def test_window_registry_closes_all_registered_windows() -> None:
    app = _app()
    registry = WindowRegistry()
    windows = [QWidget() for _ in range(3)]
    closed: list[QWidget] = []
    for window in windows:
        window.closeEvent = lambda event, w=window: (closed.append(w), event.accept())
        registry.register(window)
        window.show()
    app.processEvents()

    assert registry.close_all(main_window=None) >= 3

    assert set(closed) == set(windows)


def test_shutdown_request_exit_only_runs_once() -> None:
    manager = ShutdownManager()

    assert manager.request_exit("first") is True
    assert manager.request_exit("second") is False
    assert manager.snapshot().reason == "first"


def test_shutdown_manager_requests_task_stop_and_waits() -> None:
    manager = ShutdownManager()
    task = FakeTask()

    assert manager.register_task(task) is True
    assert manager.request_exit("test") is True
    manager.request_stop_tasks()

    assert task.stop_requested is True
    assert manager.wait_tasks_once(0.01) is True
    assert task.wait_calls == 1
    assert manager.snapshot().task_count == 0


def test_shutdown_manager_terminates_and_waits_for_process() -> None:
    manager = ShutdownManager()
    process = FakeProcess()

    handle = manager.register_process(process, "fake")
    assert handle is not None
    assert manager.request_exit("test") is True
    manager.terminate_processes()

    assert process.terminated is True
    assert manager.wait_processes_once(0.01) is True
    assert manager.snapshot().process_count == 0


def test_shutdown_manager_rejects_new_task_after_shutdown_started() -> None:
    manager = ShutdownManager()
    assert manager.request_exit("test") is True

    assert manager.register_task(FakeTask("late")) is False


def test_shutdown_manager_terminates_late_process_after_shutdown_started() -> None:
    manager = ShutdownManager()
    process = FakeProcess()
    assert manager.request_exit("test") is True

    assert manager.register_process(process, "late") is None

    assert process.terminated is True


def test_shutdown_manager_ignores_external_tool_processes() -> None:
    manager = ShutdownManager()
    process = FakeProcess()

    handle = manager.register_process(process, "WinSCP", kind="external_tool", shutdown_policy="ignore")
    assert handle is not None
    assert manager.snapshot().process_count == 0
    assert manager.snapshot().external_process_count == 1

    assert manager.request_exit("test") is True
    manager.terminate_processes()

    assert process.terminated is False
    assert manager.wait_processes_once(0.01) is True


def test_shutdown_manager_ignores_late_external_tool_processes() -> None:
    manager = ShutdownManager()
    process = FakeProcess()
    assert manager.request_exit("test") is True

    handle = manager.register_process(process, "SecureCRT", kind="external_tool", shutdown_policy="ignore")

    assert handle is not None
    assert process.terminated is False
    assert manager.snapshot().process_count == 0
