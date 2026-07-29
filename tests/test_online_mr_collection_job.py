from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest


from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
)
from netconsole.models.online_mr_models import (
    FpingConfig,
    OnlineMrConnectionConfig,
    OnlineMrTaskToggles,
)
from netconsole.models.task_state import TaskState
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.runtime.task_event_hub import TaskEventHub
from netconsole.services.online_mr.collection_commands import (
    INIT_COMMANDS,
    TASK_COMMANDS,
    TERMINAL_MONITOR_INIT_COMMANDS,
    stream_prepare_commands,
)
from netconsole.services.online_mr.collection_packager import OnlineMrCollectionPackager
from netconsole.services.online_mr.collection_paths import OnlineMrCollectionPaths
from netconsole.services.online_mr.collection_service import OnlineMrCollectionService
from netconsole.services.online_mr_session_store import OnlineMrSessionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeConnection:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False

    def send_command(self, command: str, timeout: int) -> str:
        del timeout
        self.commands.append(command)
        return f"ok:{command}"

    def close(self) -> None:
        self.closed = True


def _config() -> OnlineMrConnectionConfig:
    return OnlineMrConnectionConfig(
        site="demo",
        mr_id="1",
        mr_name="MR-Test",
        safe_mr_name="MR-Test__1",
        device_id=1,
        device_name="MR-Test",
        host="192.0.2.1",
        username="tester",
        password="secret",
        fping=FpingConfig(enabled=False),
        tasks=OnlineMrTaskToggles(
            mesh_link=False,
            channel_busy=False,
            ap_radio_statistics=False,
            switch_history=False,
            interface_rate=False,
            wireless_status=False,
        ),
    )


def _operation(
    *,
    phase: OnlineMrPhase = OnlineMrPhase.COLLECTING,
    task_status: TaskState = TaskState.RUNNING,
    force_stopped: bool = False,
) -> OnlineMrOperationSnapshotDTO:
    return OnlineMrOperationSnapshotDTO(
        controller_task_id="application-task-1",
        site_id="demo",
        device_id=1,
        device_name="MR-Test",
        mr_id="1",
        mr_name="MR-Test",
        executor_kind=OnlineMrExecutorKind.LOCAL,
        task_status=task_status,
        phase=phase,
        created_at="2026-07-13T10:00:00",
        updated_at="2026-07-13T10:00:00",
        force_stopped=force_stopped,
        mapping_state=(
            OnlineMrMappingState.TERMINAL
            if phase is OnlineMrPhase.TERMINAL
            else OnlineMrMappingState.PENDING_SESSION
        ),
    )


class FakeApplicationService:
    def __init__(self) -> None:
        self.task_service = type("TaskService", (), {"events": TaskEventHub()})()
        self.operation = _operation()
        self.started: list[OnlineMrStartRequest] = []
        self.stop_calls: list[dict[str, object]] = []
        self.force_stop_calls: list[dict[str, object]] = []

    def start_local_collection(
        self, request: OnlineMrStartRequest
    ) -> OnlineMrOperationSnapshotDTO:
        self.started.append(request)
        return self.operation

    def get_operation(
        self, controller_task_id: str, *, site_id: str | None = None
    ) -> OnlineMrOperationSnapshotDTO:
        assert controller_task_id == self.operation.controller_task_id
        assert site_id == "demo"
        return self.operation

    def stop_operation(
        self, controller_task_id: str, **kwargs
    ) -> OnlineMrOperationSnapshotDTO:
        self.stop_calls.append({"controller_task_id": controller_task_id, **kwargs})
        self.operation = self.operation.model_copy(
            update={
                "phase": OnlineMrPhase.STOPPING_TRAFFIC,
                "task_status": TaskState.STOPPING,
            }
        )
        return self.operation

    def force_stop_operation(
        self, controller_task_id: str, **kwargs
    ) -> OnlineMrOperationSnapshotDTO:
        self.force_stop_calls.append(
            {"controller_task_id": controller_task_id, **kwargs}
        )
        self.operation = _operation(
            phase=OnlineMrPhase.TERMINAL,
            task_status=TaskState.CANCELLED,
            force_stopped=True,
        )
        return self.operation


def test_online_mr_command_sequences_preserve_business_rules() -> None:
    assert TERMINAL_MONITOR_INIT_COMMANDS == (
        "screen-length disable",
        "terminal monitor",
        "terminal logging level 7",
    )
    assert INIT_COMMANDS[:3] == (
        "screen-length disable",
        "terminal logging level 7",
        "terminal monitor",
    )
    assert stream_prepare_commands("ap_radio_statistics") == (
        "screen-length disable",
        "system-view",
        "probe",
    )
    assert stream_prepare_commands("channel_busy") == (
        "screen-length disable",
        "system-view",
        "probe",
    )
    assert "display ar5drv 1 client all rssi" in TASK_COMMANDS["wireless_status"]
    assert "display ar5drv 1 client all status" in TASK_COMMANDS["wireless_status"]


def test_online_mr_collection_paths_cover_existing_raw_log_contract(
    tmp_path: Path,
) -> None:
    paths = OnlineMrCollectionPaths.from_session_dir(tmp_path / "session-1")

    assert paths.init_raw.name == "init_raw.log"
    assert paths.terminal_monitor_raw.name == "terminal_monitor_raw.log"
    assert paths.ap_radio_statistics_raw.name == "ap_radio_statistics_raw.log"
    assert paths.channel_busy_raw.name == "channel_busy_raw.log"
    assert paths.switch_history_latest.name == "switch_history_latest.log"
    assert paths.fping_v5_raw.name == "fping_v5_raw.log"
    assert paths.iperf_client_raw.name == "iperf_client_raw.log"


def test_online_mr_collection_service_stops_packages_and_keeps_raw_logs(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    connection = FakeConnection()
    service = OnlineMrCollectionService(
        OnlineMrSessionStore(paths),
        connection_factory=lambda _config: connection,
    )
    progress: list[tuple[str, str]] = []
    deadline = time.monotonic() + 0.4

    result = service.run(
        _config(),
        progress=lambda stage, _current, _total, message: progress.append(
            (stage, message)
        ),
        should_cancel=lambda: time.monotonic() >= deadline,
        package_on_stop=True,
    )

    session_dir = Path(str(result["session_dir"]))
    package_path = Path(str(result["package_path"]))
    assert result["status"] == "STOPPED"
    assert connection.commands == list(INIT_COMMANDS)
    assert connection.closed is True
    assert (session_dir / "raw" / "terminal_monitor_raw.log").exists()
    assert not (session_dir / "raw" / "init_raw.log").exists()
    assert package_path.exists()
    with zipfile.ZipFile(package_path) as archive:
        assert "session_meta.json" in archive.namelist()
        assert "raw/terminal_monitor_raw.log" in archive.namelist()
    started_event = next(
        json.loads(message)
        for stage, message in progress
        if stage == "online_mr_started"
    )
    assert started_event["session_id"] == result["session_id"]
    assert started_event["enabled_collectors"] == ["terminal_monitor"]


def test_application_collection_flushes_traffic_before_collector_close_and_package(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    order: list[str] = []

    class OrderedConnection(FakeConnection):
        def close(self) -> None:
            order.append("collector-close")
            super().close()

    class TrafficCoordinator:
        def start_for_session(self, _session, _config):
            order.append("traffic-start")
            return {"flush_complete": False}

        def stop_traffic_for_session(self, _session_id):
            order.append("traffic-stop")

        def flush_traffic_outputs(self, _session_id, *, timeout_seconds):
            assert timeout_seconds > 0
            order.append("traffic-flush")
            return []

        def finalize_traffic_outputs(self, _session_id):
            order.append("traffic-finalize")
            return {"flush_complete": True, "warnings": []}

    class Packager:
        def package(self, session_dir):
            order.append("package")
            path = Path(session_dir) / "outputs" / "session.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"zip")
            return path

    connection = OrderedConnection()
    service = OnlineMrCollectionService(
        OnlineMrSessionStore(paths),
        connection_factory=lambda _config: connection,
        traffic_coordinator=TrafficCoordinator(),
        packager=Packager(),
    )
    deadline = time.monotonic() + 0.25

    result = service.run(
        _config(),
        should_cancel=lambda: time.monotonic() >= deadline,
        manage_traffic=True,
    )

    assert result["status"] == "STOPPED"
    assert order.index("traffic-flush") < order.index("collector-close")
    assert order.index("collector-close") < order.index("traffic-finalize")
    assert order[-1] == "package"
    meta = json.loads(
        (Path(result["session_dir"]) / "session_meta.json").read_text(encoding="utf-8")
    )
    assert meta["finalization_complete"] is True
    assert meta["stop_reason"] == "cancel_requested"
    assert meta["duration_minutes"] >= 0


def test_application_collection_duration_limit_uses_same_stop_and_flush_path(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    order: list[str] = []

    def duration_clock() -> float:
        # Startup milestones may read the clock repeatedly; only the monitor tick advances time.
        if threading.current_thread().name == "online-mr-job-cancel-monitor":
            return 61.0
        return 0.0

    class TrafficCoordinator:
        def start_for_session(self, _session, _config):
            return {"flush_complete": False}

        def stop_traffic_for_session(self, _session_id):
            order.append("stop")

        def flush_traffic_outputs(self, _session_id, *, timeout_seconds):
            order.append("flush")
            return []

        def finalize_traffic_outputs(self, _session_id):
            return {"flush_complete": True, "warnings": []}

    config = _config()
    config.duration_minutes = 1
    service = OnlineMrCollectionService(
        OnlineMrSessionStore(paths),
        connection_factory=lambda _config: FakeConnection(),
        traffic_coordinator=TrafficCoordinator(),
        clock=duration_clock,
    )

    result = service.run(config, manage_traffic=True, package_on_stop=False)

    assert result["stop_reason"] == "duration_elapsed"
    assert order[:2] == ["stop", "flush"]


def test_online_mr_collection_service_emits_session_created_before_connection_failure(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    progress: list[tuple[str, str]] = []
    order: list[str] = []

    def fail_connection(_config: OnlineMrConnectionConfig):
        order.append("connect")
        raise RuntimeError("connection refused")

    def record_progress(stage: str, _current: int, _total: int, message: str) -> None:
        order.append(stage)
        progress.append((stage, message))

    store = OnlineMrSessionStore(paths)
    service = OnlineMrCollectionService(
        store,
        connection_factory=fail_connection,
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        service.run(
            _config(),
            controller_task_id="controller-1",
            progress=record_progress,
        )

    stage, message = progress[0]
    payload = json.loads(message)
    session_dirs = store.list_session_dirs("demo")
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert stage == "online_mr_session_created"
    assert set(payload) == {
        "controller_task_id",
        "session_id",
        "site_id",
        "device_id",
        "mr_name",
    }
    assert payload["controller_task_id"] == "controller-1"
    assert payload["session_id"]
    assert order[:2] == ["online_mr_session_created", "connect"]
    assert meta["status"] == "FAILED"
    assert session_dir.is_dir()


def test_application_collection_starts_traffic_before_ssh_initialization(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    order: list[str] = []
    traffic_started = threading.Event()

    class TrafficCoordinator:
        def start_for_session(self, _session, _config):
            order.append("traffic-start")
            traffic_started.set()
            return {"flush_complete": False, "warnings": []}

        def stop_traffic_for_session(self, _session_id):
            order.append("traffic-stop")

        def flush_traffic_outputs(self, _session_id, *, timeout_seconds):
            assert timeout_seconds > 0
            order.append("traffic-flush")
            return []

        def finalize_traffic_outputs(self, _session_id):
            order.append("traffic-finalize")
            return {"flush_complete": True, "warnings": []}

    def connect_after_traffic(_config: OnlineMrConnectionConfig):
        assert traffic_started.wait(1.0)
        order.append("connect")
        return FakeConnection()

    service = OnlineMrCollectionService(
        OnlineMrSessionStore(paths),
        connection_factory=connect_after_traffic,
        traffic_coordinator=TrafficCoordinator(),
    )
    deadline = time.monotonic() + 0.25

    result = service.run(
        _config(),
        should_cancel=lambda: time.monotonic() >= deadline,
        manage_traffic=True,
        package_on_stop=False,
    )

    assert result["status"] == "STOPPED"
    assert order.index("traffic-start") < order.index("connect")
    meta = json.loads((Path(result["session_dir"]) / "session_meta.json").read_text(encoding="utf-8"))
    stages = [item["stage"] for item in meta["startup_timeline"]]
    assert "session_created" in stages
    assert "traffic_start_begin" in stages
    assert "traffic_start_submitted" in stages
    assert "ssh_connect_start" in stages


def test_online_mr_packaging_failure_preserves_raw_and_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_dir = tmp_path / "session-1"
    raw_file = session_dir / "raw" / "terminal_monitor_raw.log"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("设备原始日志\n", encoding="utf-8")

    def fail_write(*_args, **_kwargs):
        raise OSError("package failed")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail_write)
    with pytest.raises(OSError, match="package failed"):
        OnlineMrCollectionPackager().package(session_dir)

    output = session_dir / "outputs" / "session-1.zip"
    assert raw_file.read_text(encoding="utf-8") == "设备原始日志\n"
    assert not output.exists()
    assert not output.with_suffix(".zip.tmp").exists()


def test_online_mr_worker_cancel_stdout_is_jsonl_and_has_one_terminal_event(
    tmp_path: Path,
) -> None:
    cancel_path = tmp_path / "job.cancel"
    cancel_path.write_text("cancelled", encoding="utf-8")
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="online-mr-cancelled",
                task_type="online_mr_collection_start",
                params={
                    "config": {},
                    "app_root": str(PROJECT_ROOT),
                    "data_root": str(tmp_path),
                },
                cancel_path=str(cancel_path),
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    terminal = [
        event for event in events if event["type"] in {"finished", "error", "cancelled"}
    ]
    assert result.returncode == 2
    assert len(terminal) == 1
    assert terminal[0]["type"] == "cancelled"
    assert "设备原始日志" not in result.stdout


def test_online_mr_worker_exception_is_structured_jsonl(tmp_path: Path) -> None:
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="online-mr-error",
                task_type="online_mr_collection_status",
                params={"session_dir": str(tmp_path / "missing")},
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert result.returncode == 1
    assert events[-1]["type"] == "error"
    assert events[-1]["cancelled"] is False
    assert events[-1]["traceback"]


def test_online_mr_job_types_are_registered() -> None:
    tasks = registered_task_types()
    assert "online_mr_collection_start" in tasks
    assert "online_mr_collection_status" in tasks
    assert "online_mr_collection_package" in tasks
