from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication

from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.background_tasks import BackgroundTaskCancelled, run_background_task
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_process_manager import ExportProcessManager
from netconsole.services.export.export_progress import error_event as export_error_event
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_events import (
    cancelled_event,
    error_event,
    finished_event,
    log_event,
    progress_event,
)
from netconsole.services.job_center.job_registry import register_handler, registered_task_types
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.job_center.task_manager import BackgroundProcessManager as JobCenterProcessManager
from netconsole.services.job_center.worker_protocol import encode_event, feed_jsonl, parse_event_line

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _wait_for(predicate, timeout: float = 8.0) -> None:
    application = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert predicate()


def _jsonl_events(result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines
    return [json.loads(line) for line in lines]


def test_registry_contains_all_existing_task_types() -> None:
    tasks = set(registered_task_types())

    assert {
        "ac_command_action_execute",
        "device_csv_import",
        "device_connection_test",
        "file_management_download",
        "mesh_mr_profiles_refresh",
        "snmp_center_data_action",
        "traffic_local_iperf_server",
        "traffic_local_iperf_client",
        "traffic_local_fping",
        "online_mr_agent_packages_sync",
        "online_mr_agent_package_import",
        "wifi_survey_heatmap_render",
    } <= tasks


def test_legacy_process_manager_import_points_to_job_center() -> None:
    assert BackgroundProcessManager is JobCenterProcessManager
    assert hasattr(BackgroundProcessManager, "is_running")


def test_legacy_run_background_task_dispatches_registry(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)

    result = run_background_task(
        BackgroundJob(
            task_type="online_mr_mark_stale_sessions",
            params={
                "site_name": "demo",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )

    assert result == {"changed_count": 0}


def test_legacy_process_manager_runs_worker_and_cleans_files(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    manager = BackgroundProcessManager(paths=paths)
    finished: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    manager.finished.connect(finished.append)
    manager.failed.connect(failed.append)
    job_id = "compat-manager-job"

    assert manager.start_job(
        BackgroundJob(
            job_id=job_id,
            task_type="online_mr_mark_stale_sessions",
            params={
                "site_name": "demo",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    ) == job_id
    assert manager.is_running(job_id)

    _wait_for(lambda: bool(finished or failed))

    assert not failed
    assert finished[0]["result"] == {"changed_count": 0}
    assert not manager.is_running(job_id)
    job_dir = paths.runtime_cache_dir / "background_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()
    application.processEvents()


def test_background_process_manager_emits_single_cancelled_event(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    manager = BackgroundProcessManager(paths=paths)
    cancelled: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    manager.cancelled.connect(cancelled.append)
    manager.failed.connect(failed.append)
    job_id = "cancel-manager-job"

    manager.start_job(BackgroundJob(job_id=job_id, task_type="unsupported_cancel_task"))
    manager.cancel_job(job_id)
    _wait_for(lambda: bool(cancelled or failed))

    assert len(cancelled) == 1
    assert not failed
    assert cancelled[0]["type"] == "cancelled"
    assert cancelled[0]["cancelled"] is True
    job_dir = paths.runtime_cache_dir / "background_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()
    application.processEvents()


def test_export_process_manager_emits_single_cancelled_event_and_cleans_files(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    manager = ExportProcessManager(paths=paths)
    cancelled: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    manager.cancelled.connect(cancelled.append)
    manager.failed.connect(failed.append)
    job_id = "cancel-export-job"
    output_path = tmp_path / "cancelled.txt"
    tmp_output = tmp_path / "cancelled.txt.tmp"
    tmp_output.write_text("partial", encoding="utf-8")

    manager.start_export(
        ExportJob(
            job_id=job_id,
            job_type="unsupported_cancel_export",
            output_path=str(output_path),
            tmp_path=str(tmp_output),
        )
    )
    manager.cancel_export(job_id)
    _wait_for(lambda: bool(cancelled or failed))

    assert len(cancelled) == 1
    assert not failed
    assert cancelled[0]["type"] == "cancelled"
    assert not tmp_output.exists()
    job_dir = paths.runtime_cache_dir / "export_jobs"
    assert not (job_dir / f"{job_id}.json").exists()
    assert not (job_dir / f"{job_id}.cancel").exists()
    application.processEvents()


def test_background_process_manager_stops_worker_when_parent_is_destroyed(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    parent = QObject()
    manager = BackgroundProcessManager(parent, paths=PathResolver(tmp_path))
    manager._worker_command = lambda _job_path: (sys.executable, ["-c", "import time; time.sleep(30)"])
    job_id = manager.start_job(BackgroundJob(task_type="parent_destroy_test"))
    process = manager._jobs[job_id].process
    assert process.waitForStarted(3000)
    cleaned: list[bool] = []
    parent.destroyed.connect(lambda: cleaned.append(not manager._jobs))

    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    assert cleaned == [True]
    assert not (tmp_path / "runtime" / "cache" / "background_jobs" / f"{job_id}.json").exists()
    application.processEvents()


def test_export_process_manager_stops_worker_when_parent_is_destroyed(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    parent = QObject()
    manager = ExportProcessManager(parent, paths=PathResolver(tmp_path))
    manager._export_worker_command = lambda _job_path: (sys.executable, ["-c", "import time; time.sleep(30)"])
    output_path = tmp_path / "parent-destroy.txt"
    job_id = manager.start_export(ExportJob(job_id="parent-destroy-export", job_type="parent_destroy_test", output_path=str(output_path)))
    process = manager._jobs[job_id].process
    assert process.waitForStarted(3000)
    cleaned: list[bool] = []
    parent.destroyed.connect(lambda: cleaned.append(not manager._jobs))

    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    assert cleaned == [True]
    assert not (tmp_path / "runtime" / "cache" / "export_jobs" / f"{job_id}.json").exists()
    application.processEvents()


def test_job_events_use_complete_common_fields() -> None:
    events = [
        progress_event("job-1", "query", 1, 2, "查询中"),
        log_event("job-1", "日志"),
        finished_event("job-1", {"count": 2}),
        error_event("job-1", "失败", traceback_text="trace"),
        cancelled_event("job-1"),
    ]
    required = {
        "type",
        "job_id",
        "stage",
        "current",
        "total",
        "message",
        "result",
        "error",
        "traceback",
        "cancelled",
    }

    assert all(required <= event.keys() for event in events)
    assert events[-1]["type"] == "cancelled"
    assert events[-1]["cancelled"] is True


def test_worker_protocol_handles_partial_jsonl_and_diagnostics() -> None:
    first = encode_event(progress_event("job-1", "query", 1, 2, "查询中"))
    second = encode_event(finished_event("job-1", {"count": 2}))
    split_at = len(first) // 2

    events, diagnostics, remainder = feed_jsonl("", first[:split_at])
    assert not events
    assert not diagnostics
    events, diagnostics, remainder = feed_jsonl(remainder, first[split_at:] + "普通诊断\n" + second)

    assert [event["type"] for event in events] == ["progress", "finished"]
    assert diagnostics == ["普通诊断"]
    assert remainder == ""
    assert parse_event_line('{"event":"cancelled","job_id":"job-1"}')["cancelled"] is True


def test_job_runner_returns_structured_cancelled_result() -> None:
    task_type = "test_job_center_cancelled"

    def cancel_handler(_context: JobContext) -> dict[str, object]:
        raise BackgroundTaskCancelled("测试取消")

    register_handler(task_type, cancel_handler)
    result = run_job(BackgroundJob(job_id="job-cancel", task_type=task_type))

    assert result.ok is False
    assert result.cancelled is True
    assert result.to_event()["type"] == "cancelled"


def test_export_events_reuse_common_protocol() -> None:
    event = export_error_event("export-1", "已取消", output_path="report.xlsx", cancelled=True)

    assert event["type"] == "cancelled"
    assert event["event"] == "cancelled"
    assert event["output_path"] == "report.xlsx"
    assert event["cancelled"] is True


@pytest.mark.parametrize(
    "entry",
    [
        [sys.executable, "-m", "netconsole.background_worker"],
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--background-worker"],
        [sys.executable, str(PROJECT_ROOT / "src" / "netconsole" / "entrypoint.py"), "--background-worker"],
    ],
    ids=["module", "main-entry", "frozen-entry"],
)
def test_background_worker_stdout_is_jsonl_only(tmp_path: Path, entry: list[str]) -> None:
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "unsupported-job",
                "task_type": "unsupported_test_task",
                "params": {},
                "cancel_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [*entry, "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    events = _jsonl_events(result)
    assert events[-1]["type"] == "error"
    assert events[-1]["job_id"] == "unsupported-job"


def test_background_worker_emits_cancelled_jsonl(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    cancel_path = tmp_path / "cancel.flag"
    cancel_path.write_text("cancelled", encoding="utf-8")
    job_path = tmp_path / "cancel-job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="cancelled-job",
                task_type="online_mr_mark_stale_sessions",
                cancel_path=str(cancel_path),
                params={
                    "site_name": "demo",
                    "app_root": str(paths.app_root),
                    "data_root": str(paths.data_root),
                },
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 2
    events = _jsonl_events(result)
    assert events[-1]["type"] == "cancelled"
    assert events[-1]["cancelled"] is True


@pytest.mark.parametrize(
    "entry",
    [
        [sys.executable, "-m", "netconsole.export_worker"],
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--export-worker"],
        [sys.executable, str(PROJECT_ROOT / "src" / "netconsole" / "entrypoint.py"), "--export-worker"],
    ],
    ids=["module", "main-entry", "frozen-entry"],
)
def test_export_worker_stdout_is_jsonl_only(tmp_path: Path, entry: list[str]) -> None:
    output_path = tmp_path / "worker-output.txt"
    tmp_output = tmp_path / "worker-output.txt.tmp"
    job_path = tmp_path / "export-job.json"
    job_path.write_text(
        json.dumps(
            ExportJob(
                job_id="export-worker-job",
                job_type="markdown_text",
                output_path=str(output_path),
                tmp_path=str(tmp_output),
                params={"payload": {"text": "中文导出内容"}},
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [*entry, "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    events = _jsonl_events(result)
    assert events[-1]["type"] == "finished"
    assert output_path.read_text(encoding="utf-8") == "中文导出内容"
    assert not tmp_output.exists()


def test_export_worker_error_event_cleans_tmp_file(tmp_path: Path) -> None:
    output_path = tmp_path / "failed.txt"
    tmp_output = tmp_path / "failed.txt.tmp"
    tmp_output.write_text("partial", encoding="utf-8")
    job_path = tmp_path / "failed-export-job.json"
    job_path.write_text(
        json.dumps(
            ExportJob(
                job_id="failed-export-job",
                job_type="unsupported_export_task",
                output_path=str(output_path),
                tmp_path=str(tmp_output),
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    events = _jsonl_events(result)
    assert events[-1]["type"] == "error"
    assert events[-1]["job_id"] == "failed-export-job"
    assert not tmp_output.exists()


def test_frozen_worker_commands_do_not_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    job_path = tmp_path / "job.json"

    background_command = BackgroundProcessManager(paths=PathResolver(tmp_path))._worker_command(job_path)
    export_command = ExportProcessManager(paths=PathResolver(tmp_path))._export_worker_command(job_path)

    assert background_command == (sys.executable, ["--background-worker", "--job", str(job_path)])
    assert export_command == (sys.executable, ["--export-worker", "--job", str(job_path)])
