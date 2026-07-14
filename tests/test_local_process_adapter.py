from __future__ import annotations

import io
import queue
import subprocess
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
    ) -> None:
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
    assert not adapter.is_running(job_id)
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
