from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshApplicationService,
)
from netconsole.services.ac.mesh_link_resident_polling_service import (
    AcMeshLinkResidentPollingApplicationService,
    AcMeshLinkResidentPollingWorkerService,
    MESH_LINK_RESIDENT_TASK_TYPE,
    resident_poller_directory,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_events import progress_event
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)


MESH_OUTPUT = """<AC-TEST>display wlan mesh-link ap
AP name: AP-Online
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 列车12-MR-CT           1000-0000-0012 0000-0001-0001 Forwarding 52   120/100
<AC-TEST>
"""


class _Connection:
    def __init__(
        self,
        *,
        fail_mesh_call: int = 0,
        invalid_mesh_call: int = 0,
    ) -> None:
        self.commands: list[str] = []
        self.closed_count = 0
        self.mesh_calls = 0
        self.fail_mesh_call = fail_mesh_call
        self.invalid_mesh_call = invalid_mesh_call

    def send_command(self, command: str, timeout: int) -> str:
        assert timeout == 20
        self.commands.append(command)
        if command == "screen-length disable":
            return "<AC-TEST>"
        if command == "display clock":
            return "12:00:00 Beijing Tue 07/14/2026"
        if command == "display wlan mesh-link ap":
            self.mesh_calls += 1
            if self.mesh_calls == self.fail_mesh_call:
                raise EOFError("session closed")
            if self.mesh_calls == self.invalid_mesh_call:
                return "unexpected text"
            return MESH_OUTPUT
        return "Total records: 0"

    def is_alive(self) -> bool:
        return self.closed_count == 0

    def close(self) -> None:
        self.closed_count += 1


class _PreparedAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []
        self.running: set[str] = set()

    def start_job(self, job, *, on_complete=None) -> str:
        self.jobs.append(job)
        self.tasks.prepare(job)
        self.tasks.mark_running(job.job_id)
        self.running.add(job.job_id)
        return job.job_id

    def is_running(self, job_id: str) -> bool:
        return job_id in self.running

    def shutdown(self) -> None:
        return None


def _paths(tmp_path: Path, *, two_controllers: bool = False) -> PathResolver:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.ensure_site_dirs("site-a")
    database = Database(paths.site_db_path("site-a"))
    database.initialize()
    now = "2026-07-14T12:00:00"
    controllers = [
        (
            "ac-1",
            "测试 AC 1",
            "AC-TEST-1",
            "10.0.0.1",
            "admin",
            "secret-one",
            now,
            now,
        )
    ]
    if two_controllers:
        controllers.append(
            (
                "ac-2",
                "测试 AC 2",
                "AC-TEST-2",
                "10.0.0.2",
                "admin",
                "secret-two",
                now,
                now,
            )
        )
    with database.connect() as conn:
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, device_vendor, device_type,
                primary_address, ssh_enabled, ssh_port, ssh_username,
                ssh_password, created_at, updated_at
            ) VALUES (?, ?, ?, 'H3C', 'AC', ?, 1, 22, ?, ?, ?, ?)
            """,
            controllers,
        )
        conn.execute(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, mac_address, device_vendor,
                device_type, primary_address, ssh_enabled, created_at, updated_at
            ) VALUES (
                'mr-12', '列车12-MR-CT', '列车12-MR-CT',
                '1000-0000-0012', 'H3C', 'MR', '10.0.1.12', 1, ?, ?
            )
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, state,
                state_display, site, rid1_bbssid, collected_at, updated_at
            ) VALUES (
                'ac-1', 'ap-1', 'AP-Online', '0000-0000-0001',
                'R/M', '运行(主)', '车站A', '0000-0001-0001', ?, ?
            )
            """,
            (now, now),
        )
        conn.commit()
    return paths


def _control(
    paths: PathResolver,
    *,
    interval: float = 0.05,
) -> tuple[Path, Path]:
    runtime = resident_poller_directory(
        paths, "site-a", "run-1", "ac-1"
    )
    control = runtime / "control.json"
    status = runtime / "status.json"
    AcMeshLinkResidentPollingApplicationService._write_json_atomic(
        control,
        {
            "poll_interval_seconds": interval,
            "include_switch_history": False,
            "immediate_request_id": "",
            "stop_requested": False,
        },
    )
    return control, status


def _context(paths: PathResolver) -> JobContext:
    return JobContext(
        job_id="resident-task-1",
        task_type=MESH_LINK_RESIDENT_TASK_TYPE,
        params={
            "site_name": "site-a",
            "controller_id": "ac-1",
            "controller_name": "测试 AC 1",
            "run_id": "run-1",
            "poll_session_id": "poll-session-1",
            "poll_interval_seconds": 0.05,
        },
        progress_callback=None,
        should_cancel=lambda: False,
        paths=paths,
    )


def _run_until(
    service: AcMeshLinkResidentPollingWorkerService,
    context: JobContext,
    status_path: Path,
    predicate,
) -> tuple[threading.Thread, dict[str, object], list[BaseException]]:
    errors: list[BaseException] = []
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result.update(service.execute(context))
        except BaseException as exc:  # pragma: no cover - assertion reports it.
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            status = {}
        if predicate(status):
            return thread, result, errors
        time.sleep(0.02)
    raise AssertionError(f"resident poller did not reach expected state: {status}")


def _request_stop(control_path: Path) -> None:
    payload = json.loads(control_path.read_text(encoding="utf-8"))
    payload["stop_requested"] = True
    AcMeshLinkResidentPollingApplicationService._write_json_atomic(
        control_path, payload
    )


def test_resident_worker_reuses_one_connection_for_multiple_polls(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    control, status = _control(paths)
    connection = _Connection()
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return connection

    service = AcMeshLinkResidentPollingWorkerService(
        paths,
        connection_factory=factory,
        jitter_ratio=0,
        wait_slice_seconds=0.02,
    )
    thread, result, errors = _run_until(
        service,
        _context(paths),
        status,
        lambda row: int(row.get("success_count") or 0) >= 3,
    )
    _request_stop(control)
    thread.join(timeout=2)

    assert errors == []
    assert not thread.is_alive()
    assert factory_calls == 1
    assert connection.commands.count("screen-length disable") == 1
    assert connection.commands.count("display clock") >= 3
    assert connection.commands.count("display wlan mesh-link ap") >= 3
    assert connection.closed_count == 1
    assert result["connection_state"] == "STOPPED"
    assert result["poll_count"] >= 3


def test_connection_failure_reconnects_inside_same_task(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    control, status = _control(paths)
    connections = [_Connection(fail_mesh_call=2), _Connection()]

    def factory(_config):
        return connections.pop(0)

    service = AcMeshLinkResidentPollingWorkerService(
        paths,
        connection_factory=factory,
        backoff_seconds=(0.01,),
        jitter_ratio=0,
        wait_slice_seconds=0.01,
    )
    thread, result, errors = _run_until(
        service,
        _context(paths),
        status,
        lambda row: int(row.get("success_count") or 0) >= 2
        and int(row.get("reconnect_count") or 0) >= 1,
    )
    _request_stop(control)
    thread.join(timeout=2)

    assert errors == []
    assert result["task_id"] == "resident-task-1"
    assert result["reconnect_count"] == 1
    assert result["success_count"] >= 2
    assert len(connections) == 0


def test_parse_failure_does_not_reconnect(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    control, status = _control(paths)
    connection = _Connection(invalid_mesh_call=2)
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return connection

    service = AcMeshLinkResidentPollingWorkerService(
        paths,
        connection_factory=factory,
        jitter_ratio=0,
        wait_slice_seconds=0.01,
    )
    thread, result, errors = _run_until(
        service,
        _context(paths),
        status,
        lambda row: int(row.get("success_count") or 0) >= 2
        and int(row.get("failure_count") or 0) >= 1,
    )
    _request_stop(control)
    thread.join(timeout=2)

    assert errors == []
    assert factory_calls == 1
    assert result["reconnect_count"] == 0
    assert result["failure_count"] >= 1


def test_interval_update_and_immediate_refresh_do_not_reconnect(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    control, status = _control(paths, interval=5.0)
    connection = _Connection()
    factory_calls = 0

    def factory(_config):
        nonlocal factory_calls
        factory_calls += 1
        return connection

    service = AcMeshLinkResidentPollingWorkerService(
        paths,
        connection_factory=factory,
        jitter_ratio=0,
        wait_slice_seconds=0.02,
    )
    thread, result, errors = _run_until(
        service,
        _context(paths),
        status,
        lambda row: int(row.get("success_count") or 0) >= 1,
    )
    payload = json.loads(control.read_text(encoding="utf-8"))
    payload["poll_interval_seconds"] = 0.05
    payload["immediate_request_id"] = "request-now"
    AcMeshLinkResidentPollingApplicationService._write_json_atomic(
        control, payload
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        row = json.loads(status.read_text(encoding="utf-8"))
        if (
            int(row.get("success_count") or 0) >= 2
            and row.get("completed_request_id") == "request-now"
        ):
            break
        time.sleep(0.02)
    else:
        raise AssertionError("updated interval/immediate request did not run")
    _request_stop(control)
    thread.join(timeout=2)

    assert errors == []
    assert factory_calls == 1
    assert result["poll_interval_seconds"] == 0.05
    assert result["completed_request_id"] == "request-now"


def test_stop_request_interrupts_reconnect_backoff_within_one_second(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    control, status = _control(paths)
    service = AcMeshLinkResidentPollingWorkerService(
        paths,
        connection_factory=lambda _config: (_ for _ in ()).throw(
            OSError("offline")
        ),
        backoff_seconds=(5.0,),
        jitter_ratio=0,
        wait_slice_seconds=0.02,
    )
    thread, result, errors = _run_until(
        service,
        _context(paths),
        status,
        lambda row: row.get("connection_state") == "BACKOFF",
    )
    started = time.monotonic()
    _request_stop(control)
    thread.join(timeout=1)

    assert errors == []
    assert not thread.is_alive()
    assert time.monotonic() - started < 1
    assert result["connection_state"] == "STOPPED"


def test_application_service_creates_one_task_per_run_controller_and_immediate_refresh_reuses_it(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path, two_controllers=True)
    tasks = TaskApplicationService(paths=paths, site_name="site-a")
    adapter = _PreparedAdapter(tasks)
    resident = AcMeshLinkResidentPollingApplicationService(
        paths, tasks, process_adapter=adapter  # type: ignore[arg-type]
    )
    refresh = AcMeshLinkRefreshApplicationService(
        paths, tasks, process_adapter=adapter  # type: ignore[arg-type]
    )
    refresh.bind_resident_service(resident)

    starts = [
        resident.ensure_poller(
            site_name="site-a",
            run_id="run-1",
            controller_id="ac-1",
            controller_name="测试 AC 1",
            poll_interval_seconds=10,
        )
        for _ in range(10)
    ]
    second = resident.ensure_poller(
        site_name="site-a",
        run_id="run-1",
        controller_id="ac-2",
        controller_name="测试 AC 2",
        poll_interval_seconds=10,
    )
    immediate = refresh.start_refresh(
        site_name="site-a", controller_id="ac-1"
    )

    assert len(adapter.jobs) == 2
    assert all(item.task.task_id == starts[0].task.task_id for item in starts)
    assert sum(not item.already_running for item in starts) == 1
    assert second.task.task_id != starts[0].task.task_id
    assert immediate.resident is True
    assert immediate.task.task_id == starts[0].task.task_id
    assert immediate.request_id.startswith("acpollreq_")
    payload = adapter.jobs[0].params
    assert payload["task_mode"] == "resident"
    assert payload["progress_mode"] == "indeterminate"
    assert not (
        {"username", "password", "command", "commands"} & payload.keys()
    )
    assert "secret-one" not in str(payload)

    tasks.events.publish(
        progress_event(
            starts[0].task.task_id,
            "waiting",
            63,
            0,
            "连接正常，下一轮 8 秒后",
            details={
                "task_mode": "resident",
                "connection_state": "WAITING",
                "poll_count": 63,
                "success_count": 62,
                "failure_count": 1,
            },
        )
    )
    detail = JobCenterQueryService(paths).get_task(
        "site-a", starts[0].task.task_id
    )
    assert detail is not None
    assert detail.task_mode == "resident"
    assert detail.progress_mode == "indeterminate"
    assert detail.current == 63
    assert detail.progress == 0
    assert detail.details["connection_state"] == "WAITING"


def test_recovery_creates_new_task_with_same_logical_poll_session(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    tasks = TaskApplicationService(paths=paths, site_name="site-a")
    first_adapter = _PreparedAdapter(tasks)
    first_service = AcMeshLinkResidentPollingApplicationService(
        paths, tasks, process_adapter=first_adapter  # type: ignore[arg-type]
    )
    first = first_service.ensure_poller(
        site_name="site-a",
        run_id="run-1",
        controller_id="ac-1",
        controller_name="测试 AC 1",
        poll_interval_seconds=10,
    )
    repository = tasks.repository("site-a")
    repository.save(
        replace(
            first.task,
            status=TaskState.FAILED,
            error_message="任务宿主已退出",
        )
    )
    second_adapter = _PreparedAdapter(tasks)
    second_service = AcMeshLinkResidentPollingApplicationService(
        paths, tasks, process_adapter=second_adapter  # type: ignore[arg-type]
    )
    recovered = second_service.ensure_poller(
        site_name="site-a",
        run_id="run-1",
        controller_id="ac-1",
        controller_name="测试 AC 1",
        poll_interval_seconds=10,
    )

    assert recovered.recovered is True
    assert recovered.task.task_id != first.task.task_id
    assert recovered.poll_session_id == first.poll_session_id
    assert len(second_adapter.jobs) == 1
