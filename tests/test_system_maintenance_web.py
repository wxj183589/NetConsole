from __future__ import annotations

import os
from pathlib import Path
from time import monotonic, sleep, time

import pytest
from fastapi.testclient import TestClient

from netconsole.application.desktop import DesktopActionResolver, DesktopActionService
from netconsole.application.system_maintenance import (
    SystemMaintenanceApplicationService,
    SystemMaintenanceError,
)
from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.infrastructure.desktop import UnavailableDesktopAdapter
from netconsole.services.export.export_handlers import run_generic_export_handler
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import app_logs_csv_spec, open_source_notices_spec
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.handlers.system_maintenance_jobs import system_maintenance_cleanup
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.open_source_notice_service import OpenSourceComponent, OpenSourceNoticeService

from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter


def _paths(tmp_path: Path) -> PathResolver:
    app_root = Path(__file__).resolve().parents[1]
    paths = PathResolver(app_root=app_root, data_root=tmp_path)
    paths.ensure_project_dirs()
    paths.ensure_site_dirs("demo")
    return paths


def _service(
    paths: PathResolver,
) -> tuple[SystemMaintenanceApplicationService, FakeLocalProcessAdapter, FakeExportProcessAdapter]:
    tasks = TaskApplicationService(paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    desktop = DesktopActionService(
        RuntimeMode.SERVER,
        UnavailableDesktopAdapter(),
        DesktopActionResolver(
            controlled_roots=(paths.app_root, paths.data_root),
            directories={"system_logs": paths.logs_dir, "system_cache": paths.runtime_cache_dir},
        ),
    )
    return (
        SystemMaintenanceApplicationService(
            paths,
            tasks,
            process_adapter=process,  # type: ignore[arg-type]
            export_adapter=export,  # type: ignore[arg-type]
            artifact_store=WebArtifactStore(paths, tasks),
            desktop_action_service=desktop,
        ),
        process,
        export,
    )


def _wait_task(client: TestClient, task_id: str) -> dict[str, object]:
    deadline = monotonic() + 10
    task: dict[str, object] = {"status": "RUNNING"}
    while task["status"] not in {"COMPLETED", "FAILED", "CANCELLED"} and monotonic() < deadline:
        sleep(0.1)
        response = client.get(f"/api/system-maintenance/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
    return task


def test_application_logs_are_paginated_redacted_and_clearable(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.app_log_path.write_text(
        "2026-07-17 10:00:00 | INFO | APP_START | host=10.0.0.8 password=secret C:\\Users\\tester\\token.txt\n"
        "2026-07-17 10:01:00 | ERROR | BOOT_START | public=8.8.8.8\n",
        encoding="utf-8",
    )
    service, _process, _export = _service(paths)

    page = service.list_logs(page=1, page_size=50, keyword="", level="INFO")

    assert page.total == 1
    assert page.items[0].display_event == "软件启动"
    serialized = page.model_dump_json()
    assert "10.0.0.8" not in serialized
    assert "secret" not in serialized
    assert "C:\\\\Users" not in serialized
    assert "<redacted-ip>" in serialized

    result = service.clear_logs()
    assert result.success is True
    assert "APP_START" not in paths.app_log_path.read_text(encoding="utf-8")
    assert "LOGS_CLEARED" in paths.app_log_path.read_text(encoding="utf-8")


def test_cleanup_job_only_deletes_existing_whitelist_and_honors_cancel(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    old_log = paths.logs_dir / "old.log"
    old_cache = paths.runtime_cache_dir / "old.cache"
    protected = paths.site_files_dir("demo") / "protected.raw"
    for path in (old_log, old_cache, protected):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
        os.utime(path, (time() - 10 * 86400, time() - 10 * 86400))

    context = JobContext(
        "cleanup-1",
        "system_maintenance_cleanup",
        {"retention_days": 3, "dry_run": False},
        None,
        lambda: False,
        paths,
    )
    result = system_maintenance_cleanup(context)

    assert result["deleted_files"] == 2
    assert not old_log.exists()
    assert not old_cache.exists()
    assert protected.exists()

    cancelled = JobContext(
        "cleanup-2",
        "system_maintenance_cleanup",
        {"retention_days": 3, "dry_run": False},
        None,
        lambda: True,
        paths,
    )
    with pytest.raises(BackgroundTaskCancelled):
        system_maintenance_cleanup(cancelled)


def test_tasks_reuse_shared_service_and_artifact_whitelist_block_is_explicit(tmp_path: Path) -> None:
    service, process, export = _service(_paths(tmp_path))

    task = service.start_cleanup("demo", dry_run=True)
    assert task.status == "RUNNING"
    assert task.action == "cleanup_scan"
    assert process.jobs[task.task_id].task_type == "system_maintenance_cleanup"

    process.complete(task.task_id, {"cleanup_items": []})
    assert service.get_task("demo", task.task_id).status == "COMPLETED"

    with pytest.raises(SystemMaintenanceError) as caught:
        service.start_log_export(
            "demo",
            scope="all",
            keyword="",
            level="",
            page=1,
            page_size=200,
        )
    assert caught.value.code == "BLOCKED_ON_TASK_WINDOW"
    assert "BLOCKED_ON_TASK_WINDOW" in str(caught.value)
    assert export.jobs == {}


def test_export_workers_redact_logs_and_write_txt_xlsx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_text(
        "2026-07-17 10:00:00 | INFO | APP_START | host=10.0.0.8 token=secret\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "logs.csv"
    log_job = app_logs_csv_spec(csv_path, log_path=log_path, redact_web=True).to_job("logs-export")
    run_generic_export_handler(
        ExportJob.from_dict({**log_job.to_dict(), "tmp_path": str(tmp_path / "logs.csv.tmp")})
    )
    exported = csv_path.read_text(encoding="utf-8-sig")
    assert "10.0.0.8" not in exported
    assert "secret" not in exported
    assert "<redacted-ip>" in exported

    component = OpenSourceComponent("demo-lib", "1.2.3", "MIT", "测试", "https://example.com")
    monkeypatch.setattr(OpenSourceNoticeService, "list_components", lambda _self: [component])
    txt_path = tmp_path / "notices.md"
    xlsx_path = tmp_path / "notices.xlsx"
    txt_job = open_source_notices_spec(txt_path, base_dir=tmp_path, format="txt").to_job("notices-txt")
    xlsx_job = open_source_notices_spec(xlsx_path, base_dir=tmp_path, format="xlsx").to_job(
        "notices-xlsx"
    )
    run_generic_export_handler(
        ExportJob.from_dict({**txt_job.to_dict(), "tmp_path": str(tmp_path / "notices.md.tmp")})
    )
    run_generic_export_handler(
        ExportJob.from_dict({**xlsx_job.to_dict(), "tmp_path": str(tmp_path / "notices.xlsx.tmp")})
    )
    assert "demo-lib" in txt_path.read_text(encoding="utf-8")
    assert xlsx_path.read_bytes().startswith(b"PK")


def test_router_exposes_strict_module_contract_and_blocker(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.app_log_path.write_text(
        "2026-07-17 10:00:00 | WARNING | APP_START | host=192.168.1.8\n",
        encoding="utf-8",
    )
    app = create_app(RuntimeMode.SERVER, paths=paths, frontend_dist=tmp_path / "missing")

    with TestClient(app) as client:
        logs = client.get("/api/system-maintenance/logs", params={"page": 1, "page_size": 50})
        about = client.get("/api/system-maintenance/about")
        blocked = client.post(
            "/api/system-maintenance/exports/logs",
            json={"scope": "all", "keyword": "", "level": "", "page": 1, "page_size": 200},
        )

    assert logs.status_code == 200, logs.text
    assert logs.json()["items"][0]["raw_event"] == "APP_START"
    assert "192.168.1.8" not in logs.text
    assert about.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "BLOCKED_ON_TASK_WINDOW"
    assert "BLOCKED_ON_TASK_WINDOW" in blocked.json()["detail"]["message"]


def test_cleanup_and_dependency_scan_run_in_real_shared_background_process(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    app = create_app(RuntimeMode.SERVER, paths=paths, frontend_dist=tmp_path / "missing")

    with TestClient(app) as client:
        started = client.post("/api/system-maintenance/cleanup/tasks", json={"mode": "scan"})
        assert started.status_code == 200, started.text
        task = _wait_task(client, started.json()["task_id"])

        scan_started = client.post("/api/system-maintenance/open-source/tasks")
        assert scan_started.status_code == 200, scan_started.text
        scan = _wait_task(client, scan_started.json()["task_id"])

    assert task["status"] == "COMPLETED", task
    assert task["action"] == "cleanup_scan"
    assert len(task["cleanup_items"]) == 3
    assert scan["status"] == "COMPLETED", scan
    assert scan["action"] == "open_source_scan"
    assert scan["components"]
