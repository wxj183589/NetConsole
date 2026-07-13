from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import FpingConfig, OnlineMrConnectionConfig, OnlineMrTaskToggles
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_registry import registered_task_types
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
from netconsole.ui.online_mr_collector_worker import OnlineMrCollectorWorker

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


def test_online_mr_collection_paths_cover_existing_raw_log_contract(tmp_path: Path) -> None:
    paths = OnlineMrCollectionPaths.from_session_dir(tmp_path / "session-1")

    assert paths.init_raw.name == "init_raw.log"
    assert paths.terminal_monitor_raw.name == "terminal_monitor_raw.log"
    assert paths.ap_radio_statistics_raw.name == "ap_radio_statistics_raw.log"
    assert paths.channel_busy_raw.name == "channel_busy_raw.log"
    assert paths.switch_history_latest.name == "switch_history_latest.log"
    assert paths.fping_v5_raw.name == "fping_v5_raw.log"
    assert paths.iperf_client_raw.name == "iperf_client_raw.log"


def test_online_mr_collection_service_stops_packages_and_keeps_raw_logs(tmp_path: Path) -> None:
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
        progress=lambda stage, _current, _total, message: progress.append((stage, message)),
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
    started_event = next(json.loads(message) for stage, message in progress if stage == "online_mr_started")
    assert started_event["session_id"] == result["session_id"]
    assert started_event["enabled_collectors"] == ["terminal_monitor"]


def test_online_mr_collection_service_emits_session_created_before_connection_failure(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    progress: list[tuple[str, str]] = []

    def fail_connection(_config: OnlineMrConnectionConfig):
        raise RuntimeError("connection refused")

    store = OnlineMrSessionStore(paths)
    service = OnlineMrCollectionService(
        store,
        connection_factory=fail_connection,
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        service.run(
            _config(),
            controller_task_id="controller-1",
            progress=lambda stage, _current, _total, message: progress.append((stage, message)),
        )

    stage, message = progress[0]
    payload = json.loads(message)
    session_dirs = store.list_session_dirs("demo")
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert stage == "online_mr_session_created"
    assert set(payload) == {"controller_task_id", "session_id", "site_id", "device_id", "mr_name"}
    assert payload["controller_task_id"] == "controller-1"
    assert payload["session_id"]
    assert meta["status"] == "FAILED"
    assert session_dir.is_dir()


def test_online_mr_packaging_failure_preserves_raw_and_cleans_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_online_mr_job_handle_submits_long_running_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = QApplication.instance() or QApplication([])
    worker = OnlineMrCollectorWorker(_config(), PathResolver(tmp_path))
    submitted: list[BackgroundJob] = []
    monkeypatch.setattr(worker._manager, "start_job", lambda job: submitted.append(job) or job.job_id)

    worker.start()

    assert len(submitted) == 1
    job = submitted[0]
    assert job.task_type == "online_mr_collection_start"
    assert int(job.params["_cancel_grace_ms"]) >= 30000
    assert "connection_targets" not in dict(job.params["config"])
    application.processEvents()


def test_online_mr_job_handle_cancelled_cleans_interrupted_package_tmp(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    worker = OnlineMrCollectorWorker(_config(), paths)
    session = OnlineMrSessionStore(paths).create_session(_config())
    worker.collector.session = session
    package_tmp = OnlineMrCollectionPaths.from_session_dir(session.session_dir).package_tmp_path
    package_tmp.parent.mkdir(parents=True, exist_ok=True)
    package_tmp.write_bytes(b"partial zip")

    worker._handle_cancelled({"job_id": worker.job_id})

    assert not package_tmp.exists()
    application.processEvents()


def test_online_mr_worker_cancel_stdout_is_jsonl_and_has_one_terminal_event(tmp_path: Path) -> None:
    cancel_path = tmp_path / "job.cancel"
    cancel_path.write_text("cancelled", encoding="utf-8")
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="online-mr-cancelled",
                task_type="online_mr_collection_start",
                params={"config": {}, "app_root": str(PROJECT_ROOT), "data_root": str(tmp_path)},
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
    terminal = [event for event in events if event["type"] in {"finished", "error", "cancelled"}]
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


def test_online_mr_page_has_no_direct_ssh_or_packaging_implementation() -> None:
    source = (PROJECT_ROOT / "src" / "netconsole" / "ui" / "pages" / "online_mr_collection_page.py").read_text(encoding="utf-8")
    assert "netconsole.services.netmiko_connection" not in source
    assert "OnlineMrCollector(" not in source
    assert "OnlineMrParseWorker(" not in source
    assert "OnlineMrReportExportWorker(" not in source
    assert 'task_type="online_mr_parse"' in source
    assert "submit_export_task(" in source
    assert "zipfile" not in source
    assert "shutil.make_archive" not in source
