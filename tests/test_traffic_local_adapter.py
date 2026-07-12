from __future__ import annotations

import asyncio
import io
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_models import FpingV5CheckResult, FpingV5Sample
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficEvent,
    TrafficEventType,
    TrafficRun,
    TrafficTestType,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.iperf_runner import (
    IperfClientConfig,
    IperfPreflightResult,
    IperfServerConfig,
)
from netconsole.services.traffic.errors import TrafficTestError
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.event_hub import TrafficEventHub
from netconsole.services.traffic.event_store import TrafficEventStore
from netconsole.services.traffic.local_adapter import (
    LocalTrafficAdapter,
    TASK_FPING,
    TASK_IPERF_CLIENT,
    TASK_IPERF_SERVER,
    _ping_config,
)


class _FakeProcessAdapter:
    def __init__(self) -> None:
        self.jobs = []
        self.cancelled: list[str] = []
        self.shutdown_timeout: float | None = None

    def start_job(self, job, *, on_complete=None):
        self.jobs.append(job)
        return job.job_id

    def cancel_job(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        return True

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self.shutdown_timeout = timeout_seconds


class _ForcedProcess:
    def __init__(self) -> None:
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self._done = threading.Event()
        self._exit_code = -9
        self.terminate_called = False
        self.kill_called = False

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("forced-worker", timeout)
        return self._exit_code

    def poll(self) -> int | None:
        return self._exit_code if self._done.is_set() else None

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True
        self._done.set()


def _infrastructure(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repository = TrafficRunRepository(paths.traffic_runs_db_path("demo"))
    store = TrafficEventStore(paths, repository, "demo")
    return paths, repository, store


def _create_run(
    repository: TrafficRunRepository,
    test_type: TrafficTestType,
    *,
    suffix: str,
    config: dict[str, object],
) -> TrafficRun:
    now = utc_now_iso()
    run = TrafficRun(
        traffic_run_id=f"run-{suffix}",
        controller_task_id=f"task-{suffix}",
        test_type=test_type,
        role="server" if test_type is TrafficTestType.IPERF_SERVER else "client",
        executor_kind=ExecutionTargetKind.LOCAL,
        normalized_config=config,
        status=TaskState.PENDING,
        created_at=now,
        updated_at=now,
    )
    return repository.create(run)


def _context(paths: PathResolver, run: TrafficRun, task_type: str, config: dict[str, object], *, cancel=False):
    progress: list[tuple[str, int, int, str]] = []
    job = JobSpec(
        job_id=run.controller_task_id,
        task_type=task_type,
        params={
            "traffic_run_id": run.traffic_run_id,
            "controller_task_id": run.controller_task_id,
            "site_name": "demo",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "config": config,
        },
    )
    return JobContext.from_job(
        job,
        progress_callback=lambda *values: progress.append(values),
        should_cancel=lambda: bool(cancel),
    ), progress


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_local_traffic_controller_submits_safe_job_and_tails_events(tmp_path: Path) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    process = _FakeProcessAdapter()
    hub = TrafficEventHub()
    subscription = hub.open_stream(max_events=20)
    config = IperfServerConfig(bind_ip="127.0.0.1", port=5201, interval_seconds=1)
    run = _create_run(repository, TrafficTestType.IPERF_SERVER, suffix="controller", config={})
    adapter = LocalTrafficAdapter(
        paths,
        process_adapter=process,  # type: ignore[arg-type]
        repository=repository,
        event_store=store,
        event_hub=hub,
        tail_interval_seconds=0.02,
    )

    assert adapter.start_iperf_server(run, config) == run.controller_task_id
    job = process.jobs[0]
    assert job.task_type == TASK_IPERF_SERVER
    assert job.params["traffic_run_id"] == run.traffic_run_id
    assert not ({"token", "tool_path", "output_path", "command", "extra_args"} & job.params.keys())
    stored = store.append(
        TrafficEvent(
            traffic_run_id=run.traffic_run_id,
            controller_task_id=run.controller_task_id,
            source="local",
            type=TrafficEventType.STATE,
            payload={"state": "RUNNING"},
        )
    )
    assert stored is not None
    assert subscription.get(timeout=1.0).sequence == stored.sequence
    assert adapter.cancel(run.controller_task_id) is True
    adapter.shutdown(timeout_seconds=0.1)
    assert process.cancelled == [run.controller_task_id]
    assert process.shutdown_timeout == 0.1
    subscription.close()


def test_local_iperf_client_reuses_runner_store_and_persists_samples(tmp_path: Path, monkeypatch) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    config = IperfClientConfig(server_ip="127.0.0.1", duration_seconds=2)
    run = _create_run(
        repository,
        TrafficTestType.IPERF_CLIENT,
        suffix="iperf-client",
        config=config.as_dict(),
    )
    context, progress = _context(paths, run, TASK_IPERF_CLIENT, config.as_dict())
    tool = tmp_path / "iperf3.exe"
    tool.write_bytes(b"fake")
    monkeypatch.setattr("netconsole.services.traffic.local_adapter.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr(
        "netconsole.services.traffic.local_adapter.run_iperf_client_preflight",
        lambda *_args, **_kwargs: IperfPreflightResult(True, message="ok"),
    )

    class FakeRunner:
        def __init__(self, _tool, command, log_file, result_store, **kwargs) -> None:
            self.command = command
            self.log_file = log_file
            self.store = result_store
            self.run_id = kwargs["run_id"]
            self.callback = kwargs["line_callback"]
            self.config = kwargs["config"]
            self.mode = kwargs["mode"]
            self.process = None
            self.last_status = "CREATED"
            self.last_error_code = ""

        def start(self) -> None:
            started = datetime.now()
            self.store.start_run(
                self.run_id,
                mode=self.mode,
                command=self.command,
                log_file=self.log_file,
                started_at=started,
                config=self.config,
            )
            row = {
                "collector_time": started.isoformat(),
                "interval_start_sec": 0.0,
                "interval_end_sec": 1.0,
                "interval_center_time": started.isoformat(),
                "transfer_bytes": 40_000_000.0,
                "bitrate_mbps": 320.0,
                "retransmits": 1,
                "raw_line": "[  5] 0.00-1.00 sec 38.1 MBytes 320 Mbits/sec",
            }
            self.store.append_interval(self.run_id, row)
            self.callback(row["raw_line"], row, None)
            self.store.finish_run(self.run_id, "DONE")
            self.last_status = "DONE"

        def stop(self, status: str = "CANCELLED") -> None:
            self.last_status = status

    monkeypatch.setattr("netconsole.services.traffic.local_adapter.IperfProcessRunner", FakeRunner)
    adapter = LocalTrafficAdapter(paths, repository=repository, event_store=store)

    result = adapter.execute_iperf_client(context)

    updated = repository.get(run.traffic_run_id)
    assert updated is not None and updated.status is TaskState.COMPLETED
    assert result["summary"]["average_bitrate_mbps"] == 320.0
    assert result["local_iperf_run_id"] == run.traffic_run_id
    with sqlite3.connect(paths.iperf_db_path("demo")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals WHERE run_id = ?", (run.traffic_run_id,)).fetchone()[0] == 1
    events = store.list_events(run.traffic_run_id, limit=100)
    assert any(event.type is TrafficEventType.SAMPLE for event in events)
    assert [item[0] for item in progress] == ["running", "completed"]


def test_local_iperf_nonzero_status_fails_instead_of_returning_success(tmp_path: Path, monkeypatch) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    run = _create_run(repository, TrafficTestType.IPERF_SERVER, suffix="iperf-failed", config={})
    context, _progress = _context(paths, run, TASK_IPERF_SERVER, {"port": 5201})
    tool = tmp_path / "iperf3.exe"
    tool.write_bytes(b"fake")
    monkeypatch.setattr("netconsole.services.traffic.local_adapter.find_iperf_tool", lambda _paths: tool)

    class FailedRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            self.process = None
            self.last_status = "FAILED:1"
            self.last_error_code = "connection_refused"

        def start(self) -> None:
            return None

        def stop(self, status: str = "CANCELLED") -> None:
            return None

    monkeypatch.setattr("netconsole.services.traffic.local_adapter.IperfProcessRunner", FailedRunner)
    adapter = LocalTrafficAdapter(paths, repository=repository, event_store=store)

    with pytest.raises(TrafficTestError):
        adapter.execute_iperf_server(context)

    updated = repository.get(run.traffic_run_id)
    assert updated is not None and updated.status is TaskState.FAILED
    assert updated.error_code == "TRAFFIC_CONNECTION_REFUSED"


def test_local_fping_runs_all_targets_batches_samples_and_keeps_timeout_null(tmp_path: Path, monkeypatch) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    config = HighFrequencyPingConfig(
        targets=("192.0.2.1", "192.0.2.2"),
        interval_ms=10,
        timeout_ms=100,
        packet_size=1256,
        count=2,
    )
    run = _create_run(
        repository,
        TrafficTestType.HIGH_FREQUENCY_PING,
        suffix="fping",
        config=config.to_dict(),
    )
    context, progress = _context(paths, run, TASK_FPING, config.to_dict())
    monkeypatch.setattr(
        "netconsole.services.traffic.local_adapter.check_fping_v5_available",
        lambda **_kwargs: FpingV5CheckResult(True, "fping.exe", "fping 5.5", True, ""),
    )
    calls: list[dict[str, object]] = []

    def fake_fping(**kwargs):
        calls.append(kwargs)
        target = str(kwargs["target"])
        packet_size = int(kwargs["packet_size"])
        yield FpingV5Sample(
            "2026-07-12T10:00:00.000",
            target,
            1,
            True,
            2.5,
            100,
            packet_size,
            "",
            "fping_v5_json",
            "resp",
            {"resp": {"host": target, "seq": 1, "rtt": 2.5, "size": packet_size}},
        )
        yield FpingV5Sample(
            "2026-07-12T10:00:00.100",
            target,
            2,
            False,
            None,
            100,
            None,
            "timeout",
            "fping_v5_json",
            "timeout",
            {"timeout": {"host": target, "seq": 2}},
        )

    monkeypatch.setattr("netconsole.services.traffic.local_adapter.run_fping_v5_json", fake_fping)
    adapter = LocalTrafficAdapter(paths, repository=repository, event_store=store)

    result = adapter.execute_high_frequency_ping(context)

    assert result["summary"]["target_count"] == 2
    assert {call["target"] for call in calls} == set(config.targets)
    assert all(call["packet_size"] == 1256 for call in calls)
    assert len({str(call["output_raw_log_path"]) for call in calls}) == 2
    rows = repository.list_ping_samples(run.traffic_run_id, limit=100)
    assert len(rows) == 4
    timeout_rows = [row for row in rows if row.timeout]
    assert len(timeout_rows) == 2
    assert all(row.rtt_ms is None and not row.ok for row in timeout_rows)
    assert [item[0] for item in progress] == ["running", "completed"]


def test_local_fping_continuous_zero_count_is_not_replaced_with_default() -> None:
    config = _ping_config({"targets": ["192.0.2.1"], "continuous": True, "count": 0})

    assert config.continuous is True
    assert config.count == 0


def test_local_fping_without_effective_samples_fails_parse(tmp_path: Path, monkeypatch) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    config = HighFrequencyPingConfig(targets=("192.0.2.1",), count=1)
    run = _create_run(
        repository,
        TrafficTestType.HIGH_FREQUENCY_PING,
        suffix="fping-empty",
        config=config.to_dict(),
    )
    context, _progress = _context(paths, run, TASK_FPING, config.to_dict())
    monkeypatch.setattr(
        "netconsole.services.traffic.local_adapter.check_fping_v5_available",
        lambda **_kwargs: FpingV5CheckResult(True, "fping.exe", "fping 5.5", True, ""),
    )

    def empty_fping(**_kwargs):
        if False:
            yield None

    monkeypatch.setattr("netconsole.services.traffic.local_adapter.run_fping_v5_json", empty_fping)
    adapter = LocalTrafficAdapter(paths, repository=repository, event_store=store)

    with pytest.raises(TrafficTestError) as captured:
        adapter.execute_high_frequency_ping(context)

    assert captured.value.code == "TRAFFIC_PARSE_FAILED"
    updated = repository.get(run.traffic_run_id)
    assert updated is not None and updated.status is TaskState.FAILED
    assert updated.summary == {}


def test_local_traffic_cancel_is_single_cancelled_terminal_and_handlers_are_registered(tmp_path: Path) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    run = _create_run(repository, TrafficTestType.IPERF_SERVER, suffix="cancelled", config={})
    context, _progress = _context(paths, run, TASK_IPERF_SERVER, {"port": 5201}, cancel=True)
    adapter = LocalTrafficAdapter(paths, repository=repository, event_store=store)

    with pytest.raises(BackgroundTaskCancelled):
        adapter.execute_iperf_server(context)

    updated = repository.get(run.traffic_run_id)
    assert updated is not None and updated.status is TaskState.CANCELLED
    terminal_states = [
        event.payload.get("state")
        for event in store.list_events(run.traffic_run_id, limit=100)
        if event.type is TrafficEventType.STATE and event.payload.get("state") in {"COMPLETED", "FAILED", "CANCELLED"}
    ]
    assert terminal_states == ["CANCELLED"]
    assert {TASK_IPERF_SERVER, TASK_IPERF_CLIENT, TASK_FPING} <= set(registered_task_types())


def test_forced_worker_exit_closes_task_center_and_traffic_run(tmp_path: Path, monkeypatch) -> None:
    paths, repository, store = _infrastructure(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    process = _ForcedProcess()
    process_adapter = LocalProcessAdapter(
        task_service,
        popen_factory=lambda *_args, **_kwargs: process,  # type: ignore[arg-type]
        process_tree_factory=lambda _process: None,
        terminate_timeout_seconds=0.02,
    )
    original_request_cancel = task_service.request_cancel

    def immediate_cancel(job_id: str) -> int:
        original_request_cancel(job_id)
        return 0

    monkeypatch.setattr(task_service, "request_cancel", immediate_cancel)
    run = _create_run(repository, TrafficTestType.IPERF_SERVER, suffix="forced", config={})
    adapter = LocalTrafficAdapter(
        paths,
        process_adapter=process_adapter,
        repository=repository,
        event_store=store,
    )
    adapter.start_iperf_server(run, IperfServerConfig())
    application = TrafficTestApplicationService(
        paths=paths,
        site_name="demo",
        task_service=task_service,
        repository=repository,
        local_adapter=adapter,
    )

    stopping = asyncio.run(application.cancel(run.controller_task_id))
    assert stopping.status in {TaskState.STOPPING, TaskState.CANCELLED}
    _wait_until(
        lambda: task_service.get_task(run.controller_task_id).status is TaskState.CANCELLED
        and repository.get(run.traffic_run_id).status is TaskState.CANCELLED
    )

    updated = repository.get(run.traffic_run_id)
    snapshot = task_service.get_task(run.controller_task_id)
    assert updated is not None and updated.status is TaskState.CANCELLED
    assert updated.sync_state.value == "COMPLETED"
    assert snapshot is not None and snapshot.status is TaskState.CANCELLED
    assert process.terminate_called is True and process.kill_called is True
    events = store.list_events(run.traffic_run_id, limit=100)
    assert any(
        event.type is TrafficEventType.SYSTEM and event.payload.get("action") == "worker_forced_stop"
        for event in events
    )
