from __future__ import annotations

import io
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import cancelled_event, finished_event, progress_event
from netconsole.services.job_center.local_process_adapter import (
    LocalProcessAdapter,
    LocalProcessCompletion,
    _WindowsJobObject,
)
from netconsole.services.job_center.sensitive_bootstrap import read_sensitive_bootstrap
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.worker_protocol import encode_event


class _BarrierPipe:
    def __init__(self, payload: bytes, barrier: threading.Barrier) -> None:
        self._payload = payload
        self._barrier = barrier
        self._read = False

    def read(self, _size: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        self._barrier.wait(timeout=1.0)
        return self._payload

    def close(self) -> None:
        return None


class _StreamingPipe:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks: queue.Queue[bytes] = queue.Queue()
        for chunk in chunks:
            self._chunks.put(chunk)

    def read(self, _size: int = -1) -> bytes:
        raise AssertionError("实时管道不能等待缓冲区填满")

    def read1(self, _size: int = -1) -> bytes:
        return self._chunks.get(timeout=1.0)

    def push(self, chunk: bytes) -> None:
        self._chunks.put(chunk)

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: object | None = None,
        stderr: object | None = None,
        exit_code: int = 0,
        auto_finish: bool = True,
        terminate_exits: bool = False,
        stdin: object | None = None,
    ) -> None:
        self.stdin = stdin
        self.stdout = stdout or io.BytesIO()
        self.stderr = stderr or io.BytesIO()
        self._exit_code = exit_code
        self._done = threading.Event()
        self._terminate_exits = terminate_exits
        self.terminate_called = False
        self.kill_called = False
        if auto_finish:
            self._done.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("fake-worker", timeout)
        return self._exit_code

    def poll(self) -> int | None:
        return self._exit_code if self._done.is_set() else None

    def terminate(self) -> None:
        self.terminate_called = True
        if self._terminate_exits:
            self._exit_code = -15
            self._done.set()

    def kill(self) -> None:
        self.kill_called = True
        self._exit_code = -9
        self._done.set()

    def finish(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self._done.set()


class _UnstoppableProcess(_FakeProcess):
    def kill(self) -> None:
        self.kill_called = True


class _FakeProcessTree:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakeKernel32:
    def __init__(self, *, assign_result: bool = True) -> None:
        self.assign_result = assign_result
        self.set_calls: list[tuple[object, int, object, int]] = []
        self.assign_calls: list[tuple[object, object]] = []
        self.close_calls: list[object] = []

    def CreateJobObjectW(self, _security, _name):
        return 101

    def SetInformationJobObject(self, handle, info_class, information, size):
        self.set_calls.append((handle, info_class, information, size))
        return True

    def AssignProcessToJobObject(self, job_handle, process_handle):
        self.assign_calls.append((job_handle, process_handle))
        return self.assign_result

    def CloseHandle(self, handle):
        self.close_calls.append(handle)
        return True


class _PopenFactory:
    def __init__(self, *processes: _FakeProcess) -> None:
        self.processes = list(processes)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.processes.pop(0)


class _RecordingPipe:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes | bytearray) -> int:
        self.data.extend(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _BlockingPopenFactory(_PopenFactory):
    def __init__(self, process: _FakeProcess) -> None:
        super().__init__(process)
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        assert self.release.wait(2)
        return super().__call__(*args, **kwargs)


def _service(tmp_path: Path) -> tuple[PathResolver, TaskApplicationService]:
    paths = PathResolver(tmp_path)
    return paths, TaskApplicationService(paths=paths, site_name="demo")


def _job(paths: PathResolver, job_id: str, *, cancel_grace_ms: int = 0) -> BackgroundJob:
    return BackgroundJob(
        job_id=job_id,
        task_type="traffic_local_test",
        params={
            "site_name": "demo",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "_cancel_grace_ms": cancel_grace_ms,
        },
    )


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_local_process_adapter_completes_and_reads_both_pipes(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-normal"
    barrier = threading.Barrier(2)
    stdout = _BarrierPipe(
        (
            encode_event(progress_event(job_id, "run", 1, 1, "运行中"))
            + encode_event(finished_event(job_id, {"ok": True}, "完成"))
        ).encode("utf-8"),
        barrier,
    )
    stderr = _BarrierPipe("诊断输出".encode("utf-8"), barrier)
    process = _FakeProcess(stdout=stdout, stderr=stderr)
    factory = _PopenFactory(process)
    adapter = LocalProcessAdapter(service, popen_factory=factory)

    assert adapter.start_job(_job(paths, job_id)) == job_id
    _wait_until(lambda: service.get_task(job_id).status is TaskState.COMPLETED)

    snapshot = service.get_task(job_id)
    assert snapshot is not None
    assert snapshot.result == {"ok": True}
    _wait_until(lambda: not adapter.is_running(job_id))
    command = factory.calls[0][0][0]
    kwargs = factory.calls[0][1]
    assert command[0] == service.runtime.worker_command(Path("unused"))[0]
    assert kwargs["shell"] is False
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    job_dir = paths.runtime_cache_dir / "background_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()


def test_local_process_adapter_streams_progress_before_worker_exit(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-live-progress"
    stdout = _StreamingPipe(encode_event(progress_event(job_id, "session_created", 0, 1, "会话已创建")).encode("utf-8"))
    process = _FakeProcess(stdout=stdout, auto_finish=False)
    adapter = LocalProcessAdapter(service, popen_factory=_PopenFactory(process))
    events: list[dict[str, object]] = []
    service.events.subscribe(events.append)

    adapter.start_job(_job(paths, job_id))
    _wait_until(
        lambda: any(
            event.get("task_id") == job_id
            and event.get("type") == "progress"
            and dict(event.get("payload") or {}).get("stage") == "session_created"
            for event in events
        )
    )

    assert adapter.is_running(job_id)
    assert service.get_task(job_id).status is TaskState.RUNNING

    stdout.push(encode_event(finished_event(job_id, {"ok": True})).encode("utf-8"))
    stdout.push(b"")
    process.finish()
    _wait_until(lambda: service.get_task(job_id).status is TaskState.COMPLETED)


def test_protocol_fatal_terminates_worker_and_unregisters_runtime(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-protocol-fatal-terminate"
    process = _FakeProcess(
        stdout=io.BytesIO(b"\xff"),
        auto_finish=False,
        terminate_exits=True,
    )
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: None,
        terminate_timeout_seconds=0.03,
    )

    adapter.start_job(_job(paths, job_id))
    _wait_until(lambda: not adapter.is_running(job_id))

    snapshot = service.get_task(job_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.FAILED
    assert snapshot.result["error_code"] == "WORKER_PROTOCOL_CORRUPTED"
    assert snapshot.text_integrity == "current_corrupted"
    assert process.terminate_called is True
    assert process.kill_called is False
    assert service.runtime.is_running(job_id) is False
    assert service.complete(job_id, 0) is None
    assert adapter.cancel_job(job_id) is False
    terminal_states = [
        event
        for event in service.list_events(job_id)
        if event["type"] == "state"
        and event["payload"].get("state") == TaskState.FAILED.value
    ]
    assert len(terminal_states) == 1


def test_protocol_fatal_kills_worker_after_terminate_timeout(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-protocol-fatal-kill"
    process = _FakeProcess(stdout=io.BytesIO(b"\xff"), auto_finish=False)
    process_tree = _FakeProcessTree()
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: process_tree,
        terminate_timeout_seconds=0.03,
    )

    adapter.start_job(_job(paths, job_id))
    _wait_until(lambda: not adapter.is_running(job_id))

    assert service.get_task(job_id).status is TaskState.FAILED
    assert process.terminate_called is True
    assert process.kill_called is True
    assert process_tree.close_calls == 1


@pytest.mark.skipif(sys.platform != "win32", reason="正式 Worker 进程树交付目标为 Windows")
def test_real_worker_bad_bytes_then_sleep_is_stopped_without_manual_complete(
    tmp_path: Path,
) -> None:
    paths, service = _service(tmp_path)
    job_id = "real-protocol-fatal-sleep"
    processes: list[subprocess.Popen[bytes]] = []

    def start_bad_worker(_command, **kwargs):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os,time; os.write(1, b'\\xff'); time.sleep(60)",
            ],
            **kwargs,
        )
        processes.append(process)
        return process

    adapter = LocalProcessAdapter(
        service,
        popen_factory=start_bad_worker,
        process_tree_factory=lambda _process: None,
        terminate_timeout_seconds=0.2,
    )

    started = time.monotonic()
    adapter.start_job(_job(paths, job_id))
    assert adapter.wait(job_id, timeout=3)
    elapsed = time.monotonic() - started

    assert elapsed < 3
    assert len(processes) == 1 and processes[0].poll() is not None
    assert service.get_task(job_id).status is TaskState.FAILED
    assert service.runtime.is_running(job_id) is False


def test_local_process_adapter_binds_tree_closes_once_and_calls_completion(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-process-tree"
    process = _FakeProcess(
        stdout=io.BytesIO(encode_event(finished_event(job_id, {"run_id": "run-1"})).encode("utf-8"))
    )
    process_tree = _FakeProcessTree()
    bound_processes: list[_FakeProcess] = []
    completions: list[LocalProcessCompletion] = []

    def bind_process_tree(selected_process):
        bound_processes.append(selected_process)
        return process_tree

    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=bind_process_tree,
    )

    adapter.start_job(_job(paths, job_id), on_complete=completions.append)
    _wait_until(lambda: not adapter.is_running(job_id))

    assert bound_processes == [process]
    assert process_tree.close_calls == 1
    assert completions == [
        LocalProcessCompletion(
            job_id=job_id,
            task_type="traffic_local_test",
            exit_code=0,
            payload=finished_event(job_id, {"run_id": "run-1"}),
            cancelled=False,
            forced=False,
        )
    ]


def test_windows_job_object_enables_kill_on_close_and_closes_idempotently() -> None:
    kernel32 = _FakeKernel32()

    process_tree = _WindowsJobObject.bind(202, kernel32)

    assert len(kernel32.set_calls) == 1
    _, info_class, information, _ = kernel32.set_calls[0]
    assert info_class == 9
    assert information._obj.BasicLimitInformation.LimitFlags == 0x00002000
    assert kernel32.assign_calls == [(101, 202)]
    process_tree.close()
    process_tree.close()
    assert kernel32.close_calls == [101]


def test_windows_job_object_assignment_failure_closes_handle() -> None:
    kernel32 = _FakeKernel32(assign_result=False)

    with pytest.raises(OSError, match="绑定 Worker"):
        _WindowsJobObject.bind(202, kernel32)

    assert kernel32.close_calls == [101]


def test_local_process_adapter_process_tree_failure_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-process-tree-fallback"
    process = _FakeProcess(
        stdout=io.BytesIO(encode_event(finished_event(job_id, {"ok": True})).encode("utf-8"))
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "netconsole.services.job_center.local_process_adapter.app_logger.log_warning",
        lambda event, detail="": warnings.append((event, detail)),
    )

    def fail_binding(_process):
        raise OSError("job object unavailable")

    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=fail_binding,
    )

    assert adapter.start_job(_job(paths, job_id)) == job_id
    _wait_until(lambda: not adapter.is_running(job_id))

    assert service.get_task(job_id).status is TaskState.COMPLETED
    assert warnings and warnings[0][0] == "LOCAL_WORKER_PROCESS_TREE_UNAVAILABLE"


def test_local_process_adapter_records_start_failure_and_cleans_job_file(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-start-failed"

    def fail_start(*_args, **_kwargs):
        raise OSError("cannot start worker")

    adapter = LocalProcessAdapter(service, popen_factory=fail_start)

    with pytest.raises(OSError, match="cannot start worker"):
        adapter.start_job(_job(paths, job_id))

    snapshot = service.get_task(job_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.FAILED
    assert "cannot start worker" in snapshot.error_message
    job_dir = paths.runtime_cache_dir / "background_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()


def test_local_process_adapter_uses_one_shot_sensitive_bootstrap_pipe(
    tmp_path: Path,
) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-sensitive-bootstrap"
    secret = "secret-must-not-be-serialized"
    stdin = _RecordingPipe()
    process = _FakeProcess(auto_finish=False, stdin=stdin)
    adapter = LocalProcessAdapter(service, popen_factory=_PopenFactory(process))

    adapter.start_job(
        _job(paths, job_id),
        sensitive_bootstrap={"password": secret},
    )

    job_path = paths.runtime_cache_dir / "background_jobs" / f"{job_id}.json"
    assert secret not in job_path.read_text(encoding="utf-8")
    assert read_sensitive_bootstrap(io.BytesIO(stdin.data)).consume() == {
        "password": secret
    }
    assert stdin.closed is True
    assert secret.encode() not in paths.site_tasks_db_path("demo").read_bytes()

    process.finish(1)
    _wait_until(lambda: not adapter.is_running(job_id))


def test_local_process_adapter_cancel_uses_grace_then_terminate_and_kill(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-cancel"
    process = _FakeProcess(auto_finish=False, terminate_exits=False)
    process_tree = _FakeProcessTree()
    completions: list[LocalProcessCompletion] = []
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: process_tree,
        terminate_timeout_seconds=0.03,
    )
    adapter.start_job(_job(paths, job_id, cancel_grace_ms=30), on_complete=completions.append)

    assert adapter.cancel_job(job_id) is True
    assert adapter.cancel_job(job_id) is True
    _wait_until(
        lambda: service.get_task(job_id).status is TaskState.CANCELLED
        and not adapter.is_running(job_id)
    )

    assert process.terminate_called is True
    assert process.kill_called is True
    assert process_tree.close_calls == 1
    assert len(completions) == 1
    assert completions[0].cancelled is True
    assert completions[0].forced is True
    assert completions[0].exit_code == -9
    assert not adapter.is_running(job_id)
    job_dir = paths.runtime_cache_dir / "background_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()


def test_local_process_adapter_force_stop_is_immediate_and_bounded(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-force-stop"
    process = _FakeProcess(auto_finish=False, terminate_exits=False)
    process_tree = _FakeProcessTree()
    completions: list[LocalProcessCompletion] = []
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: process_tree,
        terminate_timeout_seconds=0.03,
    )
    adapter.start_job(_job(paths, job_id, cancel_grace_ms=60000), on_complete=completions.append)

    assert adapter.force_stop_job(job_id, timeout_seconds=0.01) is True
    _wait_until(lambda: not adapter.is_running(job_id))

    assert process.terminate_called is True
    assert process.kill_called is True
    assert process_tree.close_calls == 1
    assert service.get_task(job_id).status is TaskState.CANCELLED
    assert len(completions) == 1
    assert completions[0].forced is True


def test_local_process_adapter_cooperative_cancel_calls_completion_once(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-cooperative-cancel"
    process = _FakeProcess(
        stdout=io.BytesIO(encode_event(cancelled_event(job_id)).encode("utf-8")),
        auto_finish=False,
    )
    completions: list[LocalProcessCompletion] = []
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: None,
    )
    adapter.start_job(_job(paths, job_id, cancel_grace_ms=1000), on_complete=completions.append)

    assert adapter.cancel_job(job_id) is True
    process.finish(1)
    _wait_until(lambda: not adapter.is_running(job_id))

    assert len(completions) == 1
    assert completions[0].cancelled is True
    assert completions[0].forced is False
    assert completions[0].exit_code == 1


def test_local_process_adapter_abandon_calls_completion_once(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-abandon"
    process = _UnstoppableProcess(auto_finish=False, terminate_exits=False)
    completions: list[LocalProcessCompletion] = []
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: _FakeProcessTree(),
        terminate_timeout_seconds=0.01,
    )
    adapter.start_job(_job(paths, job_id, cancel_grace_ms=60000), on_complete=completions.append)

    adapter.shutdown(timeout_seconds=0.01)

    _wait_until(lambda: len(completions) == 1)
    assert len(completions) == 1
    assert completions[0].cancelled is True
    assert completions[0].forced is True
    assert completions[0].exit_code is None
    assert service.get_task(job_id).status is TaskState.CANCELLED
    process.finish(-9)


def test_local_process_adapter_shutdown_uses_one_total_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, service = _service(tmp_path)
    process = _UnstoppableProcess(auto_finish=False, terminate_exits=False)
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: _FakeProcessTree(),
    )
    adapter.start_job(_job(paths, "local-total-deadline", cancel_grace_ms=60000))
    deadlines: list[float] = []
    started = time.monotonic()

    monkeypatch.setattr(adapter, "_wait_states", lambda _states, deadline: deadlines.append(deadline))
    adapter.shutdown(timeout_seconds=0.1)

    assert len(deadlines) == 3
    assert max(deadlines) <= started + 0.11
    assert process.terminate_called is True
    assert process.kill_called is True


def test_local_process_adapter_shutdown_does_not_block_on_cancel_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, service = _service(tmp_path)
    process = _UnstoppableProcess(auto_finish=False, terminate_exits=False)
    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: _FakeProcessTree(),
    )
    adapter.start_job(_job(paths, "local-blocked-cancel", cancel_grace_ms=60000))
    cancel_entered = threading.Event()
    release_cancel = threading.Event()

    def blocked_cancel(_job_id: str) -> bool:
        cancel_entered.set()
        release_cancel.wait(2)
        return True

    monkeypatch.setattr(adapter, "cancel_job", blocked_cancel)
    started = time.monotonic()
    adapter.shutdown(timeout_seconds=0.05)
    elapsed = time.monotonic() - started

    assert cancel_entered.is_set()
    assert elapsed < 0.2
    assert process.terminate_called is True
    assert process.kill_called is True
    release_cancel.set()


def test_local_process_adapter_shutdown_does_not_wait_for_blocked_process_start(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-blocked-start"
    process = _FakeProcess(auto_finish=False, terminate_exits=True)
    factory = _BlockingPopenFactory(process)
    adapter = LocalProcessAdapter(service, popen_factory=factory, process_tree_factory=lambda _process: None)
    errors: list[Exception] = []

    def start() -> None:
        try:
            adapter.start_job(_job(paths, job_id))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=start)
    thread.start()
    assert factory.entered.wait(1)
    started = time.monotonic()
    adapter.shutdown(timeout_seconds=0.05)
    elapsed = time.monotonic() - started
    factory.release.set()
    thread.join(timeout=2)

    assert elapsed < 0.2
    assert not thread.is_alive()
    assert errors and "正在关闭" in str(errors[0])
    assert process.terminate_called is True
    assert process.poll() is not None
    assert adapter.active_job_ids() == ()
    assert service.get_task(job_id).status is TaskState.CANCELLED


def test_local_process_adapter_callback_failure_does_not_change_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-callback-failure"
    process = _FakeProcess(
        stdout=io.BytesIO(encode_event(finished_event(job_id, {"ok": True})).encode("utf-8"))
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "netconsole.services.job_center.local_process_adapter.app_logger.log_error",
        lambda event, detail="": errors.append((event, detail)),
    )

    def fail_callback(_completion: LocalProcessCompletion) -> None:
        raise RuntimeError("callback failed")

    adapter = LocalProcessAdapter(
        service,
        popen_factory=_PopenFactory(process),
        process_tree_factory=lambda _process: None,
    )
    adapter.start_job(_job(paths, job_id), on_complete=fail_callback)
    _wait_until(lambda: not adapter.is_running(job_id))

    assert service.get_task(job_id).status is TaskState.COMPLETED
    assert errors == [
        (
            "LOCAL_WORKER_COMPLETION_CALLBACK_FAILED",
            f"job_id={job_id} error=callback failed",
        )
    ]


def test_local_process_adapter_shutdown_cleans_active_process_and_closes_host(tmp_path: Path) -> None:
    paths, service = _service(tmp_path)
    job_id = "local-shutdown"
    process = _FakeProcess(auto_finish=False, terminate_exits=True)
    adapter = LocalProcessAdapter(service, popen_factory=_PopenFactory(process))
    adapter.start_job(_job(paths, job_id, cancel_grace_ms=60000))

    adapter.shutdown(timeout_seconds=0.01)

    _wait_until(lambda: service.get_task(job_id).status is TaskState.CANCELLED)
    snapshot = service.get_task(job_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.CANCELLED
    assert process.terminate_called is True
    assert process.kill_called is False
    assert adapter.active_job_ids() == ()
    with pytest.raises(RuntimeError, match="正在关闭"):
        adapter.start_job(_job(paths, "after-shutdown"))
