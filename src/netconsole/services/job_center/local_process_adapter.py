from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import BinaryIO, Callable

from netconsole.core import app_logger
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.runtime.task_runtime import TaskLaunch
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.sensitive_bootstrap import encode_sensitive_bootstrap


PopenFactory = Callable[..., subprocess.Popen[bytes]]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsJobObject:
    """持有启用 KILL_ON_JOB_CLOSE 的 Windows Job Object。"""

    _EXTENDED_LIMIT_INFORMATION = 9
    _LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self, handle: int, kernel32: object) -> None:
        self._handle = handle
        self._kernel32 = kernel32
        self._lock = threading.Lock()

    @classmethod
    def bind(cls, process_handle: int, kernel32: object) -> _WindowsJobObject:
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "创建 Windows Job Object 失败")
        try:
            information = _JobObjectExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = cls._LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                cls._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise OSError(ctypes.get_last_error(), "设置 Windows Job Object 失败")
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise OSError(ctypes.get_last_error(), "绑定 Worker 到 Windows Job Object 失败")
            return cls(handle, kernel32)
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def close(self) -> None:
        with self._lock:
            handle = self._handle
            self._handle = 0
        if handle and not self._kernel32.CloseHandle(handle):
            raise OSError(ctypes.get_last_error(), "关闭 Windows Job Object 失败")


ProcessTreeGuard = _WindowsJobObject
ProcessTreeFactory = Callable[[subprocess.Popen[bytes]], ProcessTreeGuard | None]


@dataclass(frozen=True)
class LocalProcessCompletion:
    job_id: str
    task_type: str
    exit_code: int | None
    payload: dict[str, object] | None
    cancelled: bool
    forced: bool


CompletionCallback = Callable[[LocalProcessCompletion], None]


def _windows_process_tree_factory(process: subprocess.Popen[bytes]) -> ProcessTreeGuard | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process_handle = getattr(process, "_handle", None)
    if not process_handle:
        raise OSError("Worker 进程句柄不可用")
    return _WindowsJobObject.bind(process_handle, kernel32)


@dataclass
class _RunningLocalProcess:
    launch: TaskLaunch
    process: subprocess.Popen[bytes]
    process_tree: ProcessTreeGuard | None = None
    on_complete: CompletionCallback | None = None
    done: threading.Event = field(default_factory=threading.Event)
    finalize_lock: threading.Lock = field(default_factory=threading.Lock)
    process_tree_lock: threading.Lock = field(default_factory=threading.Lock)
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    wait_thread: threading.Thread | None = None
    cancel_thread: threading.Thread | None = None
    cancel_scheduled: bool = False
    protocol_fatal_scheduled: bool = False
    finalized: bool = False
    process_tree_closed: bool = False
    forced: bool = False

    @property
    def job_id(self) -> str:
        return self.launch.job.job_id


class LocalProcessAdapter:
    supports_runtime_bootstrap = True

    """使用现有 TaskRuntime 协议拉起本地 Worker 的纯 Python 进程宿主。

    Worker stdout 仍只承载低频 Job JSONL 协议。Traffic 高频样本应写入
    TrafficEventStore，由 Controller 侧独立同步，不能通过本 Adapter 转发。
    """

    def __init__(
        self,
        task_service: TaskApplicationService,
        *,
        popen_factory: PopenFactory = subprocess.Popen,
        process_tree_factory: ProcessTreeFactory = _windows_process_tree_factory,
        terminate_timeout_seconds: float = 3.0,
        read_size: int = 65536,
    ) -> None:
        self.task_service = task_service
        self._popen_factory = popen_factory
        self._process_tree_factory = process_tree_factory
        self._terminate_timeout_seconds = max(0.01, float(terminate_timeout_seconds))
        self._read_size = max(1024, int(read_size))
        self._states: dict[str, _RunningLocalProcess] = {}
        self._state_lock = threading.RLock()
        self._service_lock = threading.RLock()
        self._closing = False
        self._pending_bootstraps: dict[str, bytearray] = {}

    def start_job(
        self,
        job: BackgroundJob,
        *,
        on_complete: CompletionCallback | None = None,
        sensitive_bootstrap: Mapping[str, str] | None = None,
        runtime_bootstrap: bytearray | None = None,
    ) -> str:
        """准备任务并启动已有 ``netconsole.background_worker``。"""

        with self._state_lock:
            if self._closing:
                raise RuntimeError("本地 Worker 进程宿主正在关闭")
        if sensitive_bootstrap is not None and runtime_bootstrap is not None:
            raise ValueError("敏感启动数据不能重复提供")
        bootstrap_values = sensitive_bootstrap
        if runtime_bootstrap is not None:
            try:
                bootstrap_values = {
                    "runtime_bootstrap": bytes(runtime_bootstrap).decode("utf-8")
                }
            except UnicodeDecodeError as exc:
                raise ValueError("运行时启动数据必须是 UTF-8") from exc
        prepared_job = job
        bootstrap_bytes = None
        if bootstrap_values is not None:
            bootstrap_bytes = encode_sensitive_bootstrap(bootstrap_values)
            prepared_job = BackgroundJob(
                job_id=job.job_id,
                task_type=job.task_type,
                params={**dict(job.params or {}), "_requires_sensitive_bootstrap": True},
                cancel_path=job.cancel_path,
            )
        with self._service_lock:
            launch = self.task_service.prepare(prepared_job)
        if bootstrap_bytes is not None:
            self._pending_bootstraps[launch.job.job_id] = bootstrap_bytes
        try:
            process = self._start_process(launch)
        except Exception as exc:
            with self._service_lock:
                self.task_service.fail_start(launch.job.job_id, str(exc) or exc.__class__.__name__)
            raise
        finally:
            pending = self._pending_bootstraps.pop(launch.job.job_id, None)
            if pending is not None:
                pending[:] = b"\x00" * len(pending)

        process_tree = self._bind_process_tree(process, launch.job.job_id)
        state = _RunningLocalProcess(
            launch=launch,
            process=process,
            process_tree=process_tree,
            on_complete=on_complete,
        )
        try:
            with self._service_lock:
                self.task_service.mark_running(state.job_id)
        except Exception as exc:
            self._stop_process_now(process, process_tree)
            with self._service_lock:
                self.task_service.fail_start(state.job_id, str(exc) or exc.__class__.__name__)
            state.done.set()
            raise

        start_error: Exception | None = None
        rejected_by_shutdown = False
        with self._state_lock:
            if self._closing:
                rejected_by_shutdown = True
            else:
                self._states[state.job_id] = state
                try:
                    self._start_threads(state)
                except Exception as exc:
                    self._states.pop(state.job_id, None)
                    start_error = exc
        if rejected_by_shutdown or start_error is not None:
            self._stop_process_now(process, process_tree)
            message = "本地 Worker 进程宿主正在关闭" if rejected_by_shutdown else str(start_error or "Worker 监控线程启动失败")
            with self._service_lock:
                if rejected_by_shutdown:
                    self.task_service.request_cancel(state.job_id)
                self.task_service.fail_start(state.job_id, message)
            state.done.set()
            if rejected_by_shutdown:
                raise RuntimeError(message)
            assert start_error is not None
            raise start_error
        return state.job_id

    def cancel_job(self, job_id: str) -> bool:
        """请求协作取消；宽限期后 terminate，再超时则 kill。"""

        with self._state_lock:
            state = self._states.get(str(job_id or ""))
            if state is None or state.done.is_set():
                return False
            if state.cancel_scheduled:
                return True
            state.cancel_scheduled = True
        with self._service_lock:
            grace_ms = self.task_service.request_cancel(state.job_id)
        thread = threading.Thread(
            target=self._cancel_after_grace,
            args=(state, grace_ms),
            name=f"local-job-cancel-{state.job_id}",
            daemon=True,
        )
        state.cancel_thread = thread
        thread.start()
        return True

    def is_running(self, job_id: str) -> bool:
        with self._state_lock:
            state = self._states.get(str(job_id or ""))
            return state is not None and not state.done.is_set()

    def active_job_ids(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(job_id for job_id, state in self._states.items() if not state.done.is_set())

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        with self._state_lock:
            state = self._states.get(str(job_id or ""))
        if state is None:
            return True
        return state.done.wait(timeout=None if timeout is None else max(0.0, float(timeout)))

    def force_stop_job(self, job_id: str, *, timeout_seconds: float = 1.0) -> bool:
        """立即终止本地 Worker 进程树，并以有界等待收口 Task 状态。"""

        with self._state_lock:
            state = self._states.get(str(job_id or ""))
            if state is None or state.done.is_set():
                return False
            schedule_cancel = not state.cancel_scheduled
            state.cancel_scheduled = True
        if schedule_cancel:
            with self._service_lock:
                self.task_service.request_cancel(state.job_id)
        self._terminate_process(state)
        timeout = max(0.0, float(timeout_seconds))
        if state.done.wait(timeout):
            return True
        self._kill_process(state)
        if state.done.wait(min(self._terminate_timeout_seconds, max(0.01, timeout))):
            return True
        self._abandon(state)
        return True

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        """在总时间预算内停止所有本地 Worker；不会影响远端 Agent 任务。"""

        started = time.monotonic()
        timeout = max(0.0, float(timeout_seconds))
        deadline = started + timeout
        with self._state_lock:
            self._closing = True
            states = tuple(self._states.values())
        for state in states:
            thread = threading.Thread(
                target=self.cancel_job,
                args=(state.job_id,),
                name=f"local-job-shutdown-cancel-{state.job_id}",
                daemon=True,
            )
            thread.start()

        self._wait_states(states, started + timeout * 0.4)
        remaining = tuple(state for state in states if not state.done.is_set())
        for state in remaining:
            self._terminate_process(state)
        self._wait_states(remaining, started + timeout * 0.6)
        remaining = tuple(state for state in remaining if not state.done.is_set())
        for state in remaining:
            self._kill_process(state)
        self._wait_states(remaining, started + timeout * 0.7)
        abandon_threads: list[threading.Thread] = []
        for state in remaining:
            if not state.done.is_set():
                thread = threading.Thread(
                    target=self._abandon,
                    args=(state,),
                    name=f"local-job-shutdown-abandon-{state.job_id}",
                    daemon=True,
                )
                abandon_threads.append(thread)
                thread.start()
        for thread in abandon_threads:
            remaining_budget = deadline - time.monotonic()
            if remaining_budget <= 0:
                break
            thread.join(remaining_budget)

    def _start_process(self, launch: TaskLaunch) -> subprocess.Popen[bytes]:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        bootstrap = self._pending_bootstraps.get(launch.job.job_id)
        process = self._popen_factory(
            [launch.program, *launch.arguments],
            cwd=str(launch.working_directory),
            env=dict(launch.environment),
            stdin=subprocess.PIPE if bootstrap is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
        )
        if bootstrap is not None:
            try:
                if process.stdin is None:
                    raise RuntimeError("Worker 敏感启动管道不可用")
                process.stdin.write(bootstrap)
                process.stdin.flush()
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=self._terminate_timeout_seconds)
                except Exception:
                    process.kill()
                raise
            finally:
                if process.stdin is not None:
                    process.stdin.close()
                bootstrap[:] = b"\x00" * len(bootstrap)
        return process

    def _start_threads(self, state: _RunningLocalProcess) -> None:
        state.stdout_thread = threading.Thread(
            target=self._read_pipe,
            args=(state.job_id, state.process.stdout, False),
            name=f"local-job-stdout-{state.job_id}",
            daemon=True,
        )
        state.stderr_thread = threading.Thread(
            target=self._read_pipe,
            args=(state.job_id, state.process.stderr, True),
            name=f"local-job-stderr-{state.job_id}",
            daemon=True,
        )
        state.wait_thread = threading.Thread(
            target=self._wait_for_process,
            args=(state,),
            name=f"local-job-wait-{state.job_id}",
            daemon=True,
        )
        state.stdout_thread.start()
        state.stderr_thread.start()
        state.wait_thread.start()

    def _read_pipe(self, job_id: str, pipe: BinaryIO | None, is_stderr: bool) -> None:
        if pipe is None:
            return
        read_chunk = getattr(pipe, "read1", pipe.read)
        try:
            while True:
                chunk = read_chunk(self._read_size)
                if not chunk:
                    break
                payload = chunk.encode("utf-8", errors="strict") if isinstance(chunk, str) else bytes(chunk)
                with self._service_lock:
                    if is_stderr:
                        fatal = self.task_service.feed_stderr(job_id, payload)
                    else:
                        fatal = self.task_service.feed_stdout(job_id, payload)
                if fatal:
                    self._schedule_protocol_termination(job_id)
                    break
        except Exception as exc:
            app_logger.log_error("LOCAL_WORKER_PIPE_READ_FAILED", f"job_id={job_id} error={exc}")
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _wait_for_process(self, state: _RunningLocalProcess) -> None:
        try:
            exit_code = int(state.process.wait())
        except Exception as exc:
            exit_code = -1
            with self._service_lock:
                self.task_service.feed_stderr(state.job_id, str(exc).encode("utf-8", errors="strict"))
        # Worker 被终止时，其子进程可能仍持有 stdout/stderr 管道。先关闭 Job
        # Object 回收整棵进程树，避免下面的 pipe join 永久等待。
        self._close_process_tree(state)
        for thread in (state.stdout_thread, state.stderr_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join()
        if not self._claim_finalization(state):
            return
        payload: dict[str, object] | None = None
        try:
            with self._service_lock:
                payload = self.task_service.complete(state.job_id, exit_code)
        except Exception as exc:
            app_logger.log_error("LOCAL_WORKER_COMPLETE_FAILED", f"job_id={state.job_id} error={exc}")
        finally:
            self._notify_completion(
                state,
                exit_code=exit_code,
                payload=payload,
                cancelled=bool(payload and payload.get("cancelled")),
            )
            self._remove_state(state)

    def _cancel_after_grace(self, state: _RunningLocalProcess, grace_ms: int) -> None:
        if state.done.wait(max(0, int(grace_ms)) / 1000.0):
            return
        self._terminate_process(state)
        if state.done.wait(self._terminate_timeout_seconds):
            return
        self._kill_process(state)

    def _schedule_protocol_termination(self, job_id: str) -> None:
        with self._state_lock:
            state = self._states.get(job_id)
            if state is None or state.done.is_set() or state.protocol_fatal_scheduled:
                return
            state.protocol_fatal_scheduled = True
        thread = threading.Thread(
            target=self._terminate_protocol_failure,
            args=(state,),
            name=f"local-job-protocol-fatal-{state.job_id}",
            daemon=True,
        )
        thread.start()

    def _terminate_protocol_failure(self, state: _RunningLocalProcess) -> None:
        app_logger.log_error("WORKER_PROTOCOL_TERMINATE_REQUESTED", f"job_id={state.job_id}")
        self._terminate_process(state)
        if state.done.wait(self._terminate_timeout_seconds):
            return
        app_logger.log_error("WORKER_PROTOCOL_TERMINATE_TIMEOUT", f"job_id={state.job_id}")
        self._kill_process(state)
        app_logger.log_error("WORKER_PROTOCOL_PROCESS_KILLED", f"job_id={state.job_id}")
        if state.done.wait(self._terminate_timeout_seconds):
            return
        if not self._claim_finalization(state):
            return
        self._close_process_pipes(state)
        self._notify_completion(
            state,
            exit_code=state.process.poll(),
            payload=None,
            cancelled=False,
        )
        self._remove_state(state)

    def _terminate_process(self, state: _RunningLocalProcess) -> None:
        state.forced = True
        try:
            if state.process.poll() is None:
                state.process.terminate()
        except Exception as exc:
            app_logger.log_error("LOCAL_WORKER_TERMINATE_FAILED", f"job_id={state.job_id} error={exc}")

    def _kill_process(self, state: _RunningLocalProcess) -> None:
        state.forced = True
        self._close_process_tree(state)
        try:
            if state.process.poll() is None:
                state.process.kill()
        except Exception as exc:
            app_logger.log_error("LOCAL_WORKER_KILL_FAILED", f"job_id={state.job_id} error={exc}")

    @staticmethod
    def _stop_process_now(
        process: subprocess.Popen[bytes],
        process_tree: ProcessTreeGuard | None = None,
    ) -> None:
        if process_tree is not None:
            try:
                process_tree.close()
            except Exception:
                pass
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        except Exception:
            pass

    @staticmethod
    def _wait_states(states: tuple[_RunningLocalProcess, ...], deadline: float) -> None:
        for state in states:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            state.done.wait(remaining)

    @staticmethod
    def _claim_finalization(state: _RunningLocalProcess) -> bool:
        with state.finalize_lock:
            if state.finalized:
                return False
            state.finalized = True
            return True

    def _abandon(self, state: _RunningLocalProcess) -> None:
        if not self._claim_finalization(state):
            return
        try:
            with self._service_lock:
                self.task_service.abandon(state.job_id)
        finally:
            self._notify_completion(
                state,
                exit_code=None,
                payload=None,
                cancelled=True,
            )
            self._remove_state(state)

    def _remove_state(self, state: _RunningLocalProcess) -> None:
        self._close_process_tree(state)
        with self._state_lock:
            if self._states.get(state.job_id) is state:
                self._states.pop(state.job_id, None)
        state.done.set()

    @staticmethod
    def _close_process_pipes(state: _RunningLocalProcess) -> None:
        for pipe in (state.process.stdout, state.process.stderr):
            if pipe is None:
                continue
            try:
                pipe.close()
            except Exception:
                pass

    def _bind_process_tree(
        self,
        process: subprocess.Popen[bytes],
        job_id: str,
    ) -> ProcessTreeGuard | None:
        try:
            return self._process_tree_factory(process)
        except Exception as exc:
            # 旧版 Windows、受宿主 Job 限制或测试替身无法绑定时，任务仍按
            # 原来的单进程 terminate/kill 语义运行，不能因此拒绝启动。
            app_logger.log_warning("LOCAL_WORKER_PROCESS_TREE_UNAVAILABLE", f"job_id={job_id} error={exc}")
            return None

    @staticmethod
    def _close_process_tree(state: _RunningLocalProcess) -> None:
        with state.process_tree_lock:
            if state.process_tree_closed:
                return
            state.process_tree_closed = True
            process_tree = state.process_tree
        if process_tree is None:
            return
        try:
            process_tree.close()
        except Exception as exc:
            app_logger.log_error("LOCAL_WORKER_PROCESS_TREE_CLOSE_FAILED", f"job_id={state.job_id} error={exc}")

    @staticmethod
    def _notify_completion(
        state: _RunningLocalProcess,
        *,
        exit_code: int | None,
        payload: dict[str, object] | None,
        cancelled: bool,
    ) -> None:
        callback = state.on_complete
        if callback is None:
            return
        completion = LocalProcessCompletion(
            job_id=state.job_id,
            task_type=state.launch.job.task_type,
            exit_code=exit_code,
            payload=dict(payload) if payload is not None else None,
            cancelled=bool(cancelled),
            forced=state.forced,
        )
        try:
            callback(completion)
        except Exception as exc:
            app_logger.log_error(
                "LOCAL_WORKER_COMPLETION_CALLBACK_FAILED",
                f"job_id={state.job_id} error={exc}",
            )


LocalWorkerProcessAdapter = LocalProcessAdapter


__all__ = ["LocalProcessAdapter", "LocalProcessCompletion", "LocalWorkerProcessAdapter"]
