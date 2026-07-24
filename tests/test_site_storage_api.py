from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.services.site_lifecycle import SiteAuditService
from netconsole.services.site_storage import SiteRecord, SiteRegistryRepository


TOKEN = "site-storage-session-token-123456"


def _client(tmp_path: Path) -> TestClient:
    app_root = tmp_path / "app"
    paths = PathResolver(app_root=app_root, data_root=tmp_path / "data")
    app = create_app(RuntimeMode.DESKTOP, paths=paths, desktop_session_token=TOKEN, api_documentation_enabled=True)
    return TestClient(app, base_url="http://127.0.0.1", headers={"X-NetConsole-Session": TOKEN})


def test_site_registry_create_list_and_activate(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post(
        "/api/v1/sites",
        json={"site_id": "line-12", "display_name": "宁波地铁12号线", "activate": False},
    )
    assert created.status_code == 201, created.text
    assert created.json()["site_id"] == "line-12"
    assert any(item["site_id"] == "line-12" for item in client.get("/api/v1/sites").json())

    preflight = client.post("/api/v1/sites/line-12/activate/preflight")
    assert preflight.status_code == 200, preflight.text
    assert preflight.json() == {
        "ready": True,
        "target_site_id": "line-12",
        "previous_site_id": "demo",
    }
    assert client.get("/api/v1/sites/active").json()["site_id"] == "demo"

    activated = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})
    assert activated.status_code == 200, activated.text
    assert activated.json()["restart_required"] is True


def test_legacy_chinese_site_is_listed_and_activated_by_stable_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    paths = client.app.state.paths
    legacy_name = "宁波地铁12号线"
    paths.ensure_site_dirs(legacy_name)
    Database(paths.site_db_path(legacy_name)).initialize()

    listed = client.get("/api/v1/sites")

    assert listed.status_code == 200, listed.text
    legacy = next(item for item in listed.json() if item["display_name"] == legacy_name)
    assert legacy["site_id"].startswith("legacy-")

    activated = client.post(f"/api/v1/sites/{legacy['site_id']}/activate", json={"confirmed": True})

    assert activated.status_code == 200, activated.text
    assert activated.json()["site_id"] == legacy["site_id"]


def test_site_switch_is_blocked_by_active_task(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/v1/sites", json={"site_id": "line-12", "display_name": "十二号线"})
    client.app.state.task_service.create_external_task(
        task_id="running-task",
        task_type="test",
        task_name="运行任务",
        source="external",
        site_name="line-12",
    )

    response = client.post("/api/v1/sites/line-12/activate/preflight")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SITE_HAS_ACTIVE_TASKS"
    blocking = response.json()["detail"]["details"]["blocking_tasks"]
    assert blocking[0] == {
        "task_id": "running-task",
        "task_type": "test",
        "task_name": "运行任务",
        "status": "PENDING",
        "created_at": blocking[0]["created_at"],
        "updated_at": blocking[0]["updated_at"],
        "blocking_reason": "任务状态为 PENDING，任务宿主仍可能继续执行",
        "recoverable": False,
        "stale": False,
    }

    activation = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})
    assert activation.status_code == 409
    assert activation.json()["detail"]["code"] == "SITE_HAS_ACTIVE_TASKS"


def test_terminal_task_history_does_not_block_site_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/v1/sites", json={"site_id": "line-12", "display_name": "十二号线"})
    repository = client.app.state.task_service.repository("line-12")
    now = utc_now_iso()
    for status in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
        repository.save(
            TaskSnapshot(
                task_id=f"history-{status.value.lower()}",
                task_type="test",
                task_name="历史任务",
                status=status,
                created_time=now,
                updated_time=now,
                source="local",
                site_name="line-12",
            )
        )

    response = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})

    assert response.status_code == 200, response.text
    assert client.get("/api/v1/sites/active").json()["site_id"] == "line-12"


def test_dead_local_task_is_reconciled_before_site_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/v1/sites", json={"site_id": "line-12", "display_name": "十二号线"})
    repository = client.app.state.task_service.repository("line-12")
    now = utc_now_iso()
    repository.save(
        TaskSnapshot(
            task_id="stale-running",
            task_type="test",
            task_name="残留任务",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=999999,
            site_name="line-12",
        )
    )

    response = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})

    assert response.status_code == 200, response.text
    restored = repository.get("stale-running")
    assert restored is not None and restored.status is TaskState.FAILED


def test_unhosted_pending_task_is_reconciled_before_site_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/v1/sites", json={"site_id": "line-12", "display_name": "十二号线"})
    repository = client.app.state.task_service.repository("line-12")
    now = utc_now_iso()
    repository.save(
        TaskSnapshot(
            task_id="stale-pending",
            task_type="test",
            task_name="未启动残留任务",
            status=TaskState.PENDING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=0,
            site_name="line-12",
        )
    )

    response = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})

    assert response.status_code == 200, response.text
    restored = repository.get("stale-pending")
    assert restored is not None and restored.status is TaskState.FAILED


def test_active_task_in_current_site_blocks_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/v1/sites", json={"site_id": "line-12", "display_name": "十二号线"})
    client.app.state.task_service.create_external_task(
        task_id="current-site-task",
        task_type="test",
        task_name="当前局点任务",
        source="external",
        site_name="demo",
    )

    response = client.post("/api/v1/sites/line-12/activate", json={"confirmed": True})

    assert response.status_code == 409
    tasks = response.json()["detail"]["details"]["blocking_tasks"]
    assert [item["task_id"] for item in tasks] == ["current-site-task"]


def test_data_root_validation_returns_safe_error_and_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    snapshot = client.get("/api/v1/storage/data-root")
    assert snapshot.status_code == 200
    assert snapshot.json()["active_site_id"]

    unsafe = client.post("/api/v1/storage/data-root/validate", json={"path": str(tmp_path / "app" / "nested")})
    assert unsafe.status_code == 422
    assert unsafe.json()["detail"]["code"] == "DATA_ROOT_UNSAFE_LOCATION"


def test_site_package_inspect_does_not_write_on_invalid_package(tmp_path: Path) -> None:
    client = _client(tmp_path)
    package = tmp_path / "invalid.ncsite"
    package.write_bytes(b"not a zip")

    response = client.post("/api/v1/sites/import/inspect", json={"package_path": str(package)})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SITE_IMPORT_INVALID_PACKAGE"


def test_site_storage_contract_is_in_openapi(tmp_path: Path) -> None:
    client = _client(tmp_path)
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/v1/sites" in paths
    assert "/api/v1/storage/data-root/migrate" in paths
    assert "/api/v1/sites/{site_id}/audit" in paths
    assert "/api/v1/sites/{site_id}/cleanup/prepare" in paths
    assert "/api/v1/sites/recycle/{cleanup_token}/restore" in paths
    assert "site-and-storage" in paths["/api/v1/sites"]["get"]["tags"]


def test_site_audit_and_cleanup_prepare_are_redacted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    paths = client.app.state.paths
    SiteAuditService(paths).audit_all(site_id="demo")

    audit = client.get("/api/v1/sites/demo/audit/latest")
    plan = client.post("/api/v1/sites/demo/cleanup/prepare")

    assert audit.status_code == 200, audit.text
    assert "physical_path" not in audit.json()
    assert "file_manifest" not in audit.json()
    assert "manifest_path" not in audit.json()
    assert str(paths.data_root) not in audit.text
    assert plan.status_code == 200, plan.text
    assert set(plan.json()) == {"cleanup_token", "site_id", "classification", "blocking_reasons", "recoverable", "can_delete"}


def test_cleanup_api_requires_audit_and_explicit_confirmation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    paths = client.app.state.paths
    shell = paths.ensure_site_dirs("legacy-shell")
    Database(shell / "db" / "devices.db").initialize()
    SiteRegistryRepository(paths).register(SiteRecord("legacy-shell-id", "Legacy 空壳", shell))

    missing = client.post("/api/v1/sites/legacy-shell-id/cleanup/prepare")
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "SITE_AUDIT_REQUIRED"

    SiteAuditService(paths).audit_all(site_id="legacy-shell-id")
    prepared = client.post("/api/v1/sites/legacy-shell-id/cleanup/prepare")
    assert prepared.status_code == 200, prepared.text
    token = prepared.json()["cleanup_token"]
    rejected = client.post(
        "/api/v1/sites/legacy-shell-id/cleanup/apply",
        json={"cleanup_token": token, "confirmed": False},
    )
    assert rejected.status_code == 422


def test_demo_rebuild_rejects_user_data_bypass(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/v1/sites/demo/rebuild", json={"confirmed": True, "allow_user_data": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEMO_USER_DATA_EXPORT_REQUIRED"


def test_isolated_storage_is_read_only_and_redacted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NETCONSOLE_STORAGE_MODE", "isolated_test")
    client = _client(tmp_path)

    listed = client.get("/api/v1/sites")
    active = client.get("/api/v1/sites/active")
    snapshot = client.get("/api/v1/storage/data-root")

    assert listed.status_code == 200
    assert all("path" not in item for item in listed.json())
    assert active.status_code == 200
    assert "path" not in active.json()
    assert snapshot.status_code == 200
    assert snapshot.json() == {
        "data_root": "<temporary>",
        "default_data_root": "<unavailable>",
        "site_count": 1,
        "active_site_id": "demo",
        "storage_mode": "isolated_test",
        "data_root_kind": "temporary",
        "persistent": False,
    }

    writes = (
        ("/api/v1/sites", {"site_id": "line-12", "display_name": "十二号线"}),
        ("/api/v1/sites/demo/activate", {"confirmed": True}),
        ("/api/v1/sites/demo/migrate", {"path": str(tmp_path / "target")}),
        ("/api/v1/sites/demo/export", {"destination_path": str(tmp_path / "site.ncsite")}),
        ("/api/v1/sites/import/inspect", {"package_path": str(tmp_path / "site.ncsite")}),
        ("/api/v1/sites/import", {"package_path": str(tmp_path / "site.ncsite")}),
        ("/api/v1/sites/demo/audit", {}),
        ("/api/v1/sites/demo/cleanup/prepare", {}),
        ("/api/v1/sites/demo/rebuild", {"confirmed": True}),
        ("/api/v1/sites/recycle/1234567890abcdef/restore", {"confirmed": True}),
        ("/api/v1/storage/data-root/validate", {"path": str(tmp_path / "target")}),
        ("/api/v1/storage/data-root/migration-plan", {"path": str(tmp_path / "target")}),
        ("/api/v1/storage/data-root/migrate", {"path": str(tmp_path / "target")}),
    )
    for path, payload in writes:
        response = client.post(path, json=payload)
        assert response.status_code == 403, (path, response.text)


def test_site_storage_tasks_are_visible_as_cancellable_in_job_center(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.task_service.create_external_task(
        task_id="site-export-task",
        task_type="site_export",
        task_name="导出局点",
        source="local",
        owner="site-storage",
        site_name="demo",
    )

    task = client.get("/api/job-center/tasks/site-export-task")

    assert task.status_code == 200
    assert task.json()["cancellable"] is True


def test_site_cleanup_commit_tasks_are_not_cancellable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.task_service.create_external_task(
        task_id="site-cleanup-task",
        task_type="site_cleanup_apply",
        task_name="安全清理局点",
        source="local",
        owner="site-storage",
        site_name="demo",
    )

    task = client.get("/api/job-center/tasks/site-cleanup-task")

    assert task.status_code == 200
    assert task.json()["cancellable"] is False
    assert "不可停止" in task.json()["cancel_reason"]
