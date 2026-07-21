from __future__ import annotations

import os
from pathlib import Path
from time import monotonic, sleep, time

import pytest
from fastapi.testclient import TestClient

from netconsole import background_worker
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
from netconsole.services.job_center.worker_protocol import encode_event
from netconsole.services.open_source_notice_service import OpenSourceComponent, OpenSourceNoticeService
from netconsole.services.system_maintenance_redaction import redact_system_maintenance_text

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
    old_log = paths.logs_dir / "app_20260701.log"
    old_cache = paths.runtime_cache_dir / "chart_cache" / "old.cache"
    protected = paths.site_files_dir("demo") / "protected.raw"
    for path in (old_log, old_cache, protected):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "2026-07-01 10:00:00 | INFO | OLD_EVENT | old\n" if path == old_log else "content",
            encoding="utf-8",
        )
        os.utime(path, (time() - 10 * 86400, time() - 10 * 86400))

    context = JobContext(
        "cleanup-1",
        "system_maintenance_cleanup",
        {
            "retention_days": 3,
            "dry_run": False,
            "selected_item_ids": ["runtime_logs", "runtime_cache"],
            "confirmed": True,
        },
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
        {
            "retention_days": 3,
            "dry_run": False,
            "selected_item_ids": ["runtime_logs"],
            "confirmed": True,
        },
        None,
        lambda: True,
        paths,
    )
    with pytest.raises(BackgroundTaskCancelled):
        system_maintenance_cleanup(cancelled)


@pytest.mark.parametrize(
    "params",
    [
        {"retention_days": 0, "dry_run": True, "selected_item_ids": [], "confirmed": False},
        {"retention_days": 3, "dry_run": False, "selected_item_ids": [], "confirmed": True},
        {"retention_days": 3, "dry_run": False, "selected_item_ids": ["unknown"], "confirmed": True},
        {
            "retention_days": 3,
            "dry_run": False,
            "selected_item_ids": ["runtime_logs", "runtime_logs"],
            "confirmed": True,
        },
        {
            "retention_days": 3,
            "dry_run": False,
            "selected_item_ids": ["runtime_logs"],
            "confirmed": False,
        },
    ],
)
def test_cleanup_worker_rejects_untrusted_contract(tmp_path: Path, params: dict[str, object]) -> None:
    context = JobContext(
        "cleanup-invalid",
        "system_maintenance_cleanup",
        params,
        None,
        lambda: False,
        _paths(tmp_path),
    )

    with pytest.raises(ValueError):
        system_maintenance_cleanup(context)


def test_cleanup_worker_rejects_automatic_cache_cleanup(tmp_path: Path) -> None:
    context = JobContext(
        "cleanup-invalid-auto",
        "system_maintenance_cleanup",
        {
            "retention_days": 3,
            "dry_run": False,
            "selected_item_ids": ["runtime_cache"],
            "confirmed": True,
            "automatic": True,
        },
        None,
        lambda: False,
        _paths(tmp_path),
    )

    with pytest.raises(ValueError, match="软件运行日志"):
        system_maintenance_cleanup(context)


def test_cleanup_cancel_persists_partial_progress_and_one_terminal_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    candidates = [paths.runtime_cache_dir / "chart_cache" / f"old-{index}.tmp" for index in range(3)]
    for candidate in candidates:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("cache", encoding="utf-8")
        os.utime(candidate, (time() - 10 * 86400, time() - 10 * 86400))
    tasks = TaskApplicationService(paths, site_name="demo")
    launch = tasks.prepare(
        background_worker.BackgroundJob(
            job_id="cleanup-cancel-after-one",
            task_type="system_maintenance_cleanup",
            params={
                "site_name": "demo",
                "task_name": "安全清理日志与缓存",
                "owner": "web_system_maintenance",
                "retention_days": 3,
                "dry_run": False,
                "selected_item_ids": ["runtime_cache"],
                "confirmed": True,
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )
    tasks.mark_running(launch.job.job_id)
    emitted: list[dict[str, object]] = []

    def capture(event: dict[str, object]) -> None:
        emitted.append(event)
        details = event.get("details")
        if event.get("type") == "progress" and isinstance(details, dict) and details.get("processed_files") == 1:
            launch.cancel_path.write_text("cancelled", encoding="utf-8")

    monkeypatch.setattr(background_worker, "_emit", capture)
    exit_code = background_worker.run_job(launch.job)
    for event in emitted:
        tasks.feed_stdout(launch.job.job_id, encode_event(event).encode("utf-8"))
    tasks.complete(launch.job.job_id, exit_code)

    terminal = [event for event in emitted if event.get("type") in {"finished", "error", "cancelled"}]
    persisted = tasks.repository("demo").list_events(launch.job.job_id)
    progress = [event for event in persisted if event["type"] == "progress" and event["payload"].get("details")]
    snapshot = tasks.repository("demo").get(launch.job.job_id)
    assert exit_code == 2
    assert [event["type"] for event in terminal] == ["cancelled"]
    assert snapshot is not None and snapshot.status.value == "CANCELLED"
    assert progress[-1]["payload"]["details"]["processed_files"] == 1
    assert sum(path.exists() for path in candidates) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "scan", "retention_days": 0},
        {"mode": "scan", "retention_days": 366},
        {"mode": "scan", "retention_days": 3, "selected_item_ids": ["runtime_logs"]},
        {"mode": "scan", "retention_days": 3, "confirmed": True},
        {"mode": "clean", "retention_days": 3, "selected_item_ids": [], "confirmed": True},
        {"mode": "clean", "retention_days": 3, "selected_item_ids": ["runtime_logs"], "confirmed": False},
        {
            "mode": "clean",
            "retention_days": 3,
            "selected_item_ids": ["runtime_logs", "runtime_logs"],
            "confirmed": True,
        },
        {"mode": "clean", "retention_days": 3, "selected_item_ids": ["unknown"], "confirmed": True},
    ],
)
def test_cleanup_api_rejects_invalid_requests(tmp_path: Path, payload: dict[str, object]) -> None:
    app = create_app(RuntimeMode.SERVER, paths=_paths(tmp_path), frontend_dist=tmp_path / "missing")
    with TestClient(app) as client:
        response = client.post("/api/system-maintenance/cleanup/tasks", json=payload)
    assert response.status_code == 422


def test_cleanup_application_rejects_invalid_selection_before_start(tmp_path: Path) -> None:
    service, process, _export = _service(_paths(tmp_path))
    with pytest.raises(SystemMaintenanceError) as duplicate:
        service.start_cleanup(
            "demo",
            dry_run=False,
            selected_item_ids=["runtime_logs", "runtime_logs"],
            confirmed=True,
        )
    with pytest.raises(SystemMaintenanceError) as unknown:
        service.start_cleanup(
            "demo",
            dry_run=False,
            selected_item_ids=["unknown"],
            confirmed=True,
        )
    assert duplicate.value.code == "CLEANUP_ITEMS_INVALID"
    assert unknown.value.code == "CLEANUP_ITEMS_INVALID"
    assert process.jobs == {}


def test_automatic_cleanup_selects_only_software_runtime_logs(tmp_path: Path) -> None:
    service, process, _export = _service(_paths(tmp_path))
    task = service.start_cleanup("demo", dry_run=False, automatic=True)
    job = process.jobs[task.task_id]
    assert job.params["selected_item_ids"] == ["runtime_logs"]
    assert job.params["confirmed"] is True


def test_tasks_reuse_shared_service_and_real_artifact_store(tmp_path: Path) -> None:
    service, process, export = _service(_paths(tmp_path))

    task = service.start_cleanup("demo", dry_run=True)
    assert task.status == "RUNNING"
    assert task.action == "cleanup_scan"
    assert process.jobs[task.task_id].task_type == "system_maintenance_cleanup"

    process.complete(task.task_id, {"cleanup_items": []})
    assert service.get_task("demo", task.task_id).status == "COMPLETED"

    exported = service.start_log_export(
        "demo",
        scope="all",
        keyword="",
        level="",
        page=1,
        page_size=200,
    )
    assert exported.status == "RUNNING"
    assert exported.artifact_name == "app_log_all.csv"
    assert exported.artifact_id
    assert exported.artifact_id not in exported.artifact_name
    export.complete(exported.task_id, b"time,level\n")
    completed = service.get_task("demo", exported.task_id)
    assert completed.status == "COMPLETED"
    assert completed.available is True
    path, name = service.open_artifact("demo", completed.artifact_kind, completed.artifact_id)
    assert path.read_bytes() == b"time,level\n"
    assert name == "app_log_all.csv"


def test_cancel_reports_when_no_adapter_owns_active_task(tmp_path: Path) -> None:
    service, process, _export = _service(_paths(tmp_path))
    task = service.start_cleanup("demo", dry_run=True)
    process.jobs.pop(task.task_id)

    with pytest.raises(SystemMaintenanceError) as captured:
        service.cancel_task("demo", task.task_id)

    assert captured.value.code == "TASK_NOT_CANCELLABLE"
    assert service.get_task("demo", task.task_id).status == "RUNNING"


def test_external_link_indices_reject_negative_or_zero_values(tmp_path: Path) -> None:
    service, process, _export = _service(_paths(tmp_path))
    for value in ("repository-0", "repository--1", "repository-invalid"):
        with pytest.raises(SystemMaintenanceError) as captured:
            service.about_link(value)
        assert captured.value.code == "LINK_NOT_FOUND"

    task = service.start_open_source_scan("demo")
    process.complete(
        task.task_id,
        {
            "components": [
                {
                    "name": "demo",
                    "version": "1.0",
                    "license": "MIT",
                    "purpose": "test",
                    "homepage": "https://example.com",
                    "note": "",
                }
            ]
        },
    )
    with pytest.raises(SystemMaintenanceError) as captured:
        service.open_source_link("demo", task.task_id, -1)
    assert captured.value.code == "LINK_NOT_FOUND"


def test_task_dto_tolerates_damaged_persisted_progress_details(tmp_path: Path) -> None:
    service, _process, _export = _service(_paths(tmp_path))
    task = service.start_cleanup("demo", dry_run=True)
    service.task_service.record_external_event(
        task.task_id,
        "progress",
        {
            "stage": "clean",
            "current": 1,
            "total": 3,
            "message": "partial",
            "details": {
                "processed_files": "not-an-int",
                "deleted_files": {"invalid": True},
                "failed_count": -5,
                "freed_bytes": None,
            },
        },
        site_name="demo",
    )

    recovered = service.get_task("demo", task.task_id)

    assert recovered.processed_files == 1
    assert recovered.deleted_files == 0
    assert recovered.failed_count == 0
    assert recovered.freed_bytes == 0


def test_system_maintenance_redaction_covers_secrets_private_addresses_and_paths() -> None:
    source = (
        'password="pw-alpha" ssh_password=ssh-beta telnet_password=telnet-gamma '
        'snmpv3_auth_password="auth-delta" snmpv3_priv_password=priv-epsilon '
        'auth_secret=auth-zeta priv_secret="priv-eta" '
        'Authorization: Bearer bearer-theta community=community-iota token=token-kappa '
        'json={"password":"escaped-\\\"lambda"} '
        'ipv4=10.2.3.4 ipv6=fd00::1234 loopback=::1 '
        r'path=C:\Users\operator\secret.txt unc=\\server\share\secret.txt '
        'public_ipv4=8.8.8.8 public_ipv6=2001:4860:4860::8888'
    )

    redacted = redact_system_maintenance_text(source)

    for secret in (
        "pw-alpha",
        "ssh-beta",
        "telnet-gamma",
        "auth-delta",
        "priv-epsilon",
        "auth-zeta",
        "priv-eta",
        "bearer-theta",
        "community-iota",
        "token-kappa",
        "lambda",
        "10.2.3.4",
        "fd00::1234",
        "::1",
        r"C:\Users\operator",
        r"\\server\share",
    ):
        assert secret not in redacted
    assert "8.8.8.8" in redacted
    assert "2001:4860:4860::8888" in redacted


def test_export_workers_redact_logs_and_write_txt_xlsx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_text(
        "2026-07-17 10:00:00 | INFO | APP_START | "
        "host=10.0.0.8 token=secret-value ssh_password=ssh-value "
        "Authorization: Bearer bearer-value community=community-value "
        "ipv6=fd00::8 path=C:\\Users\\tester\\secret.txt\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "logs.csv"
    log_job = app_logs_csv_spec(csv_path, log_path=log_path, redact_web=True).to_job("logs-export")
    run_generic_export_handler(
        ExportJob.from_dict({**log_job.to_dict(), "tmp_path": str(tmp_path / "logs.csv.tmp")})
    )
    exported = csv_path.read_text(encoding="utf-8-sig")
    assert "10.0.0.8" not in exported
    assert "secret-value" not in exported
    assert "ssh-value" not in exported
    assert "bearer-value" not in exported
    assert "community-value" not in exported
    assert "fd00::8" not in exported
    assert "C:\\Users\\tester" not in exported
    assert "<redacted-ip>" in exported

    component = OpenSourceComponent("demo-lib", "1.2.3", "MIT", "测试", "https://example.com")
    monkeypatch.setattr(OpenSourceNoticeService, "list_components", lambda _self: [component])
    txt_path = tmp_path / "notices.txt"
    xlsx_path = tmp_path / "notices.xlsx"
    txt_job = open_source_notices_spec(txt_path, base_dir=tmp_path, format="txt").to_job("notices-txt")
    xlsx_job = open_source_notices_spec(xlsx_path, base_dir=tmp_path, format="xlsx").to_job(
        "notices-xlsx"
    )
    run_generic_export_handler(
        ExportJob.from_dict({**txt_job.to_dict(), "tmp_path": str(tmp_path / "notices.txt.tmp")})
    )
    run_generic_export_handler(
        ExportJob.from_dict({**xlsx_job.to_dict(), "tmp_path": str(tmp_path / "notices.xlsx.tmp")})
    )
    assert "demo-lib" in txt_path.read_text(encoding="utf-8")
    assert xlsx_path.read_bytes().startswith(b"PK")


def test_log_export_includes_current_and_rotated_runtime_logs(tmp_path: Path) -> None:
    active = tmp_path / "app.log"
    rotated = tmp_path / "app-20260720-120000-0001.log"
    active.write_text(
        "2026-07-21 10:00:00 | INFO | CURRENT_EVENT | current\n",
        encoding="utf-8",
    )
    rotated.write_text(
        "2026-07-20 10:00:00 | WARNING | ROTATED_EVENT | rotated\n",
        encoding="utf-8",
    )
    output = tmp_path / "logs.csv"
    job = app_logs_csv_spec(
        output,
        log_path=active,
        log_paths=[active, rotated],
    ).to_job("logs-rotated")

    run_generic_export_handler(
        ExportJob.from_dict({**job.to_dict(), "tmp_path": str(tmp_path / "logs.csv.tmp")})
    )

    content = output.read_text(encoding="utf-8-sig")
    assert "CURRENT_EVENT" in content
    assert "ROTATED_EVENT" in content


def test_txt_artifact_download_uses_public_name_extension_and_mime(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service, _process, export = _service(paths)
    app = create_app(RuntimeMode.SERVER, paths=paths, frontend_dist=tmp_path / "missing")

    with TestClient(app) as client:
        app.state.system_maintenance_service = service
        started = service.start_open_source_export("demo", format="txt")
        export.complete(started.task_id, b"Open source notices\n")
        completed = service.get_task("demo", started.task_id)
        response = client.get(
            f"/api/system-maintenance/artifacts/{completed.artifact_kind}/{completed.artifact_id}"
        )

    disposition = response.headers["content-disposition"]
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert completed.artifact_name == "open_source_notices.txt"
    assert "open_source_notices.txt" in disposition
    assert completed.artifact_id not in disposition
    assert response.content == b"Open source notices\n"


def test_router_exposes_strict_module_contract_and_real_artifact_task(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.app_log_path.write_text(
        "2026-07-17 10:00:00 | WARNING | APP_START | host=192.168.1.8\n",
        encoding="utf-8",
    )
    app = create_app(RuntimeMode.SERVER, paths=paths, frontend_dist=tmp_path / "missing")

    with TestClient(app) as client:
        logs = client.get("/api/system-maintenance/logs", params={"page": 1, "page_size": 50})
        about = client.get("/api/system-maintenance/about")
        started = client.post(
            "/api/system-maintenance/exports/logs",
            json={"scope": "all", "keyword": "", "level": "", "page": 1, "page_size": 200},
        )

    assert logs.status_code == 200, logs.text
    assert logs.json()["items"][0]["raw_event"] == "APP_START"
    assert "192.168.1.8" not in logs.text
    assert about.status_code == 200
    assert started.status_code == 200, started.text
    assert started.json()["artifact_name"] == "app_log_all.csv"
    assert started.json()["artifact_id"] not in started.json()["artifact_name"]


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
