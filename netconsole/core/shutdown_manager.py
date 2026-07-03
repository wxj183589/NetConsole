from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Callable, Literal, Protocol

from netconsole.core import app_logger


class ManagedTask(Protocol):
    name: str

    def request_stop(self) -> None:
        ...

    def is_running(self) -> bool:
        ...

    def wait(self, timeout: float) -> bool:
        ...


@dataclass
class CallbackTask:
    name: str
    stop_callback: Callable[[], None]
    running_callback: Callable[[], bool] | None = None

    def request_stop(self) -> None:
        self.stop_callback()

    def is_running(self) -> bool:
        return bool(self.running_callback()) if self.running_callback else False

    def wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while self.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        return not self.is_running()


@dataclass
class ProcessHandle:
    name: str
    process: subprocess.Popen
    kind: Literal["internal_tool", "internal_task", "external_tool"] = "internal_tool"
    shutdown_policy: Literal["terminate", "ignore"] = "terminate"

    @property
    def pid(self) -> int:
        return int(getattr(self.process, "pid", 0) or 0)

    def is_running(self) -> bool:
        return self.process.poll() is None

    def terminate(self) -> None:
        if self.is_running():
            self.process.terminate()

    def kill(self) -> None:
        if self.is_running():
            self.process.kill()

    def wait(self, timeout: float) -> bool:
        try:
            self.process.wait(timeout=max(0.0, timeout))
            return True
        except subprocess.TimeoutExpired:
            return False


@dataclass
class ShutdownSnapshot:
    shutting_down: bool
    reason: str
    task_count: int
    process_count: int
    external_process_count: int = 0


@dataclass
class ShutdownManager:
    _tasks: dict[str, ManagedTask] = field(default_factory=dict)
    _processes: dict[int, ProcessHandle] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _shutting_down: bool = False
    _reason: str = ""

    def request_exit(self, reason: str) -> bool:
        with self._lock:
            if self._shutting_down:
                app_logger.log_warning("SHUTDOWN_REQUEST_IGNORED", f"reason={reason} active_reason={self._reason}")
                return False
            self._shutting_down = True
            self._reason = reason
        app_logger.log_info("SHUTDOWN_REQUESTED", f"reason={reason}")
        return True

    def is_shutting_down(self) -> bool:
        with self._lock:
            return self._shutting_down

    def reset_for_tests(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._processes.clear()
            self._shutting_down = False
            self._reason = ""

    def register_task(self, task: ManagedTask, *, allow_during_shutdown: bool = False) -> bool:
        with self._lock:
            if self._shutting_down and not allow_during_shutdown:
                app_logger.log_warning("SHUTDOWN_TASK_REJECTED", getattr(task, "name", task.__class__.__name__))
                return False
            self._tasks[task.name] = task
            return True

    def unregister_task(self, task: ManagedTask | str) -> None:
        name = task if isinstance(task, str) else task.name
        with self._lock:
            self._tasks.pop(name, None)

    def register_process(
        self,
        process: subprocess.Popen,
        name: str = "",
        *,
        kind: Literal["internal_tool", "internal_task", "external_tool"] = "internal_tool",
        shutdown_policy: Literal["terminate", "ignore"] = "terminate",
    ) -> ProcessHandle | None:
        with self._lock:
            if shutdown_policy == "ignore":
                handle = ProcessHandle(name or _process_name(process), process, kind=kind, shutdown_policy=shutdown_policy)
                self._processes[handle.pid] = handle
                app_logger.log_info("SHUTDOWN_EXTERNAL_PROCESS_IGNORED", f"name={handle.name} pid={handle.pid} kind={handle.kind}")
                return handle
            if self._shutting_down:
                app_logger.log_warning("SHUTDOWN_PROCESS_REJECTED", name or str(getattr(process, "pid", "")))
                try:
                    if process.poll() is None:
                        process.terminate()
                except Exception as exc:
                    app_logger.log_error("SHUTDOWN_PROCESS_REJECT_TERMINATE_FAILED", f"{name}: {exc}")
                return None
            handle = ProcessHandle(name or _process_name(process), process, kind=kind, shutdown_policy=shutdown_policy)
            self._processes[handle.pid] = handle
            return handle

    def unregister_process(self, process_or_pid: subprocess.Popen | int) -> None:
        pid = int(process_or_pid if isinstance(process_or_pid, int) else getattr(process_or_pid, "pid", 0) or 0)
        with self._lock:
            self._processes.pop(pid, None)

    def snapshot(self) -> ShutdownSnapshot:
        with self._lock:
            tasks = [task for task in self._tasks.values() if _task_running(task)]
            processes = [handle for handle in self._processes.values() if handle.shutdown_policy == "terminate" and handle.is_running()]
            external = [handle for handle in self._processes.values() if handle.shutdown_policy == "ignore" and handle.is_running()]
            return ShutdownSnapshot(self._shutting_down, self._reason, len(tasks), len(processes), len(external))

    def request_stop_tasks(self) -> None:
        for task in self._task_list():
            try:
                task.request_stop()
                app_logger.log_info("SHUTDOWN_TASK_STOP_REQUESTED", task.name)
            except Exception as exc:
                app_logger.log_error("SHUTDOWN_TASK_STOP_FAILED", f"{task.name}: {exc}")

    def wait_tasks_once(self, timeout_per_task: float = 0.05) -> bool:
        remaining: list[str] = []
        for task in self._task_list():
            if not _task_running(task):
                self.unregister_task(task)
                continue
            try:
                if task.wait(timeout_per_task):
                    self.unregister_task(task)
                else:
                    remaining.append(task.name)
            except Exception as exc:
                self.unregister_task(task)
                app_logger.log_error("SHUTDOWN_TASK_WAIT_FAILED", f"{task.name}: {exc}")
        return not remaining

    def terminate_processes(self) -> None:
        for handle in self._process_list():
            try:
                if handle.is_running():
                    app_logger.log_info("SHUTDOWN_PROCESS_TERMINATE", f"name={handle.name} pid={handle.pid}")
                    handle.terminate()
            except Exception as exc:
                app_logger.log_error("SHUTDOWN_PROCESS_TERMINATE_FAILED", f"{handle.name} pid={handle.pid}: {exc}")

    def wait_processes_once(self, timeout_per_process: float = 0.05) -> bool:
        remaining: list[int] = []
        for handle in self._process_list():
            if not handle.is_running():
                self.unregister_process(handle.pid)
                continue
            if handle.wait(timeout_per_process):
                self.unregister_process(handle.pid)
            else:
                remaining.append(handle.pid)
        return not remaining

    def kill_processes(self) -> None:
        for handle in self._process_list():
            try:
                if handle.is_running():
                    app_logger.log_warning("SHUTDOWN_PROCESS_KILL", f"name={handle.name} pid={handle.pid}")
                    handle.kill()
                    handle.wait(0.5)
                self.unregister_process(handle.pid)
            except Exception as exc:
                app_logger.log_error("SHUTDOWN_PROCESS_KILL_FAILED", f"{handle.name} pid={handle.pid}: {exc}")

    def wait_for_shutdown(self, timeout: float = 5.0) -> bool:
        self.request_stop_tasks()
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            tasks_done = self.wait_tasks_once(0.05)
            if tasks_done:
                break
        self.terminate_processes()
        while time.monotonic() < deadline:
            processes_done = self.wait_processes_once(0.05)
            if processes_done:
                return True
        return self.snapshot().task_count == 0 and self.snapshot().process_count == 0

    def _task_list(self) -> list[ManagedTask]:
        with self._lock:
            return list(self._tasks.values())

    def _process_list(self) -> list[ProcessHandle]:
        with self._lock:
            return [handle for handle in self._processes.values() if handle.shutdown_policy == "terminate"]


def _task_running(task: ManagedTask) -> bool:
    try:
        return task.is_running()
    except Exception:
        return True


def _process_name(process: subprocess.Popen) -> str:
    args = getattr(process, "args", "")
    if isinstance(args, (list, tuple)) and args:
        return str(args[0])
    return str(args or "process")


shutdown_manager = ShutdownManager()
