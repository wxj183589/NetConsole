from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from netconsole.backend.api.device_management_router import router
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.device_management import DeviceImportConfirmRequestDTO
from netconsole.models.device import Device
from netconsole.models.snmp_models import DeviceSnmpProfileResult
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_management_web_service import (
    DEVICE_CONNECTION_TEST_TASK_TYPE,
    MAX_DEVICE_IMPORT_BYTES,
    WEB_TASK_OWNER,
    DeviceManagementWebService,
    run_device_connection_test,
    run_device_detail_collect,
    run_device_diagnostic_download,
)
from netconsole.services.device_import_export import TEMPLATE_FIELDS
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _CapturingProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []
        self.completions = []
        self.block_start = False
        self.start_entered = Event()
        self.second_start_entered = Event()
        self.release_start = Event()
        self.cancelled: list[str] = []

    def start_job(self, job, **kwargs) -> str:
        self.jobs.append(job)
        self.completions.append(kwargs.get("on_complete"))
        if len(self.jobs) > 1:
            self.second_start_entered.set()
        if self.block_start:
            self.start_entered.set()
            assert self.release_start.wait(2)
        return self.tasks.prepare(job).job.job_id

    def shutdown(self) -> None:
        return None

    def cancel_job(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return any(job.job_id == task_id for job in self.jobs)


def _write_import_csv(
    path: Path, *, name: str = "导入设备", address: str = "192.0.2.40"
) -> None:
    row = [""] * len(TEMPLATE_FIELDS)
    for index, value in {
        0: name,
        1: address,
        3: "SSH",
        4: "22",
        5: "admin",
        7: "H3C",
        8: "SW",
        11: "否",
        20: "导入测试",
    }.items():
        row[index] = value
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows((TEMPLATE_FIELDS, row))


def _fixture(tmp_path: Path):
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "local")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    devices = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    onboard = groups.create("车载-MR")
    mr = devices.create(
        Device(
            name="MR2",
            primary_address="192.0.2.12",
            group_id=onboard.id,
            device_type="AC",
            ssh_password="secret-password",
            telnet_enabled=1,
            telnet_password="telnet-secret",
            snmp_enabled=1,
            snmp_v2c_enabled=1,
            snmp_ro_community="private-community",
        )
    )
    sw = devices.create(Device(name="SW10", primary_address="192.0.2.20", device_type="SW"))
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    adapter = _CapturingProcessAdapter(tasks)
    service = DeviceManagementWebService(paths, tasks, site_name="demo", process_adapter=adapter)  # type: ignore[arg-type]
    app = FastAPI()
    app.state.device_management_service = service
    app.state.feature_gate = FeatureGate(paths.app_root)
    for feature_id in (
        "web.device_management_write",
        "web.device_management_collect",
        "web.device_management_import",
        "web.device_management_export",
        "web.device_management_desktop",
    ):
        state = dict(app.state.feature_gate.features[feature_id])
        app.state.feature_gate.features[feature_id] = {
            **state,
            "visible": True,
            "enabled": True,
            "client_package": True,
        }
    app.include_router(router, prefix="/api")
    return TestClient(app), service, adapter, devices, DeviceFactRepository(database), mr, sw


def _task(task_id: str, device_uuid: str, *, success: bool) -> TaskSnapshot:
    now = datetime.now(UTC).isoformat()
    return TaskSnapshot(
        task_id=task_id,
        task_type=DEVICE_CONNECTION_TEST_TASK_TYPE,
        task_name="设备连接测试",
        status=TaskState.COMPLETED,
        created_time=now,
        updated_time=now,
        finished_time=now,
        device=device_uuid,
        site_name="demo",
        result={"device_uuid": device_uuid, "protocol": "SSH", "success": success, "status": "ok" if success else "timeout"},
    )


def test_list_supports_filter_sort_pagination_and_never_returns_credentials(tmp_path: Path) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    service.task_service.repository("demo").save(_task("device-test-ssh-complete", str(mr.device_uuid), success=True))

    response = client.get(
        "/api/device-management/devices",
        params={
            "search": "MR",
            "group_id": mr.group_id,
            "device_type": "AC",
            "connection_status": "REACHABLE",
            "sort_by": "primary_address",
            "sort_order": "desc",
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["device_uuid"] == mr.device_uuid
    assert response.json()["items"][0]["connection_status"] == "REACHABLE"
    assert "password" not in response.text.lower()
    assert "community" not in response.text.lower()


def test_detail_returns_only_existing_fact_task_collection_and_sanitized_errors(tmp_path: Path) -> None:
    client, service, _adapter, _devices, facts, mr, _sw = _fixture(tmp_path)
    collect = facts.create_collect_run(
        {
            "collect_type": "device_detail",
            "status": "FAILED",
            "error_message": "login secret-password failed",
        }
    )
    facts.upsert_device_fact(
        {
            "device_uuid": mr.device_uuid,
            "sysname": "MR-02",
            "model": "WA6320",
            "software_version": "V9",
            "collect_run_uuid": collect["collect_run_uuid"],
        }
    )
    failed = _task("device-test-ssh-failed", str(mr.device_uuid), success=False)
    service.task_service.repository("demo").save(
        TaskSnapshot(**{**failed.__dict__, "status": TaskState.FAILED, "error_message": "auth telnet-secret failed"})
    )

    response = client.get(f"/api/device-management/devices/{mr.device_uuid}")

    assert response.status_code == 200
    body = response.json()
    assert body["fact"]["model"] == "WA6320"
    assert body["recent_collection"]["collect_type"] == "device_detail"
    assert body["recent_tasks"][0]["task_id"] == "device-test-ssh-failed"
    assert body["connection_commands"][0]["command"] == "ssh -p 22 192.0.2.12"
    assert "***" in response.text
    assert "secret-password" not in response.text
    assert "telnet-secret" not in response.text
    assert "raw_log" not in response.text


def test_edit_preview_is_whitelisted_validated_and_never_persists(tmp_path: Path) -> None:
    client, _service, _adapter, devices, _facts, mr, _sw = _fixture(tmp_path)
    payload = {
        "name": "  MR-NEW  ",
        "primary_address": "192.0.2.99",
        "backup_address": "192.0.2.99",
        "device_vendor": "H3C",
        "device_type": "AC",
        "ssh_enabled": True,
        "telnet_enabled": False,
    }

    response = client.post(f"/api/device-management/devices/{mr.device_uuid}/edit-preview", json=payload)
    rejected = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/edit-preview",
        json={**payload, "password": "must-not-be-accepted"},
    )

    assert response.status_code == 200
    assert response.json()["normalized"]["name"] == "MR-NEW"
    assert response.json()["warnings"] == ["备用地址与主地址相同"]
    assert response.json()["persistence"] == "preview_only"
    assert rejected.status_code == 422
    assert devices.get_by_uuid(str(mr.device_uuid)).name == "MR2"


def test_connection_test_submits_safe_job_and_recovers_by_task_id(tmp_path: Path) -> None:
    client, _service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    response = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/connection-tests",
        json={"protocol": "SSH"},
    )
    task_id = response.json()["task_id"]
    restored = client.get(f"/api/device-management/connection-tests/{task_id}")
    rejected = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/connection-tests",
        json={"protocol": "SSH", "password": "secret-password"},
    )

    assert response.status_code == 202
    assert restored.status_code == 200
    assert restored.json()["task_id"] == task_id
    assert restored.json()["protocol"] == "SSH"
    assert restored.json()["task_status"] == "STARTING"
    assert rejected.status_code == 422
    assert set(adapter.jobs[0].params) == {
        "site_name",
        "device_uuid",
        "protocol",
        "task_name",
        "owner",
        "task_source",
        "device",
        "app_root",
        "data_root",
        "_emit_log_events",
        "_cancel_grace_ms",
    }
    assert "secret-password" not in str(adapter.jobs[0].to_dict())
    assert "private-community" not in str(adapter.jobs[0].to_dict())


def test_connection_test_reuses_active_task(tmp_path: Path) -> None:
    client, _service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    first = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/connection-tests",
        json={"protocol": "SSH"},
    )
    second = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/connection-tests",
        json={"protocol": "SSH"},
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    assert len(adapter.jobs) == 1


def test_connection_test_reuses_active_task_under_concurrent_requests(tmp_path: Path) -> None:
    _client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    adapter.block_start = True
    barrier = Barrier(3)

    def submit():
        barrier.wait()
        return service.start_connection_test(str(mr.device_uuid), "SSH")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        barrier.wait()
        assert adapter.start_entered.wait(1)
        assert not adapter.second_start_entered.wait(0.1)
        adapter.release_start.set()
        results = [future.result(timeout=2) for future in futures]

    assert results[0].task_id == results[1].task_id
    assert len(adapter.jobs) == 1


def test_production_service_follows_runtime_site_switch(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "local")
    sites = SiteManager(paths)
    sites.ensure_demo_site()
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    adapter = _CapturingProcessAdapter(tasks)
    service = DeviceManagementWebService(paths, tasks, process_adapter=adapter)  # type: ignore[arg-type]

    assert service.current_site_id() == "demo"
    sites.create_site("line-b")
    assert service.current_site_id() == "line-b"
    sites.switch_site("demo")
    assert service.current_site_id() == "demo"


def test_connection_worker_reuses_existing_ssh_and_snmp_services_without_real_network(tmp_path: Path, monkeypatch) -> None:
    _client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    progress = []
    monkeypatch.setattr(
        "netconsole.services.netmiko_connection.test_device_connection",
        lambda _device: SimpleNamespace(
            success=True,
            status="ok",
            message="connected",
            method="primary_direct",
            host="192.0.2.12",
            port=22,
            elapsed_ms=3,
            prompt="<MR-02>",
            error_type=None,
            suggestion=None,
        ),
    )
    ssh = run_device_connection_test(
        JobContext(
            "job-ssh",
            DEVICE_CONNECTION_TEST_TASK_TYPE,
            {"site_name": "demo", "device_uuid": mr.device_uuid, "protocol": "SSH"},
            lambda *values: progress.append(values),
            lambda: False,
            service.paths,
        )
    )
    monkeypatch.setattr(
        "netconsole.services.device_snmp_detect_service.DeviceSnmpDetectService.detect",
        lambda _self, _device, **_kwargs: DeviceSnmpProfileResult(
            status="success",
            sys_name="MR-02",
            model="WA6320",
            os_family="Comware",
            interface_count=4,
            latency_ms=5,
        ),
    )
    snmp = run_device_connection_test(
        JobContext(
            "job-snmp",
            DEVICE_CONNECTION_TEST_TASK_TYPE,
            {"site_name": "demo", "device_uuid": mr.device_uuid, "protocol": "SNMP"},
            None,
            lambda: False,
            service.paths,
        )
    )

    assert ssh["system_name"] == "MR-02"
    assert ssh["success"] is True
    assert snmp["model"] == "WA6320"
    assert snmp["success"] is True
    assert progress[-1][1:3] == (1, 1)
    assert "secret-password" not in str(ssh)
    assert "private-community" not in str(snmp)


def test_router_exposes_device_management_parity_endpoints_without_arbitrary_terminal_or_secret_routes(tmp_path: Path) -> None:
    client, *_rest = _fixture(tmp_path)
    paths = client.app.openapi()["paths"]
    device_paths = {path: methods for path, methods in paths.items() if path.startswith("/api/device-management")}

    posts = {path for path, methods in device_paths.items() if "post" in methods}
    assert {
        "/api/device-management/devices/{device_uuid}/edit-preview",
        "/api/device-management/devices/{device_uuid}/connection-tests",
        "/api/device-management/devices",
        "/api/device-management/devices/{device_uuid}/duplicate",
        "/api/device-management/devices/delete-confirmation",
        "/api/device-management/devices/batch-delete",
        "/api/device-management/imports/preview",
        "/api/device-management/imports/confirm",
        "/api/device-management/exports/csv",
        "/api/device-management/exports/template",
        "/api/device-management/exports/securecrt",
        "/api/device-management/exports/omnipeek",
        "/api/device-management/diagnostic-download",
        "/api/device-management/devices/{device_uuid}/external-terminal",
    }.issubset(posts)
    assert not any("password" in path or "secret" in path or path.endswith("/shell") for path in device_paths)


def test_web_crud_group_assignment_and_token_delete_preserve_secret_boundary(tmp_path: Path) -> None:
    client, _service, _adapter, devices, _facts, mr, sw = _fixture(tmp_path)
    created = client.post(
        "/api/device-management/devices",
        json={"name": "Web-1", "primary_address": "192.0.2.30", "device_vendor": "H3C", "device_type": "SW"},
    )
    assert created.status_code == 201
    created_uuid = created.json()["device"]["device_uuid"]
    assert "password" not in created.text.lower()

    updated = client.put(
        f"/api/device-management/devices/{created_uuid}",
        json={"name": "Web-1-updated", "primary_address": "192.0.2.31", "device_vendor": "H3C", "device_type": "SW"},
    )
    assert updated.status_code == 200
    assert devices.get_by_uuid(created_uuid).name == "Web-1-updated"

    group = client.post("/api/device-management/groups", json={"name": "WebGroup"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    assigned = client.post("/api/device-management/groups/assign", json={"device_uuids": [created_uuid, str(sw.device_uuid)], "group_id": group_id})
    assert assigned.status_code == 200
    assert assigned.json()["success"] == 2
    renamed = client.patch(f"/api/device-management/groups/{group_id}", json={"name": "WebGroupRenamed"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "WebGroupRenamed"
    removed_group = client.delete(f"/api/device-management/groups/{group_id}")
    assert removed_group.status_code == 200
    assert removed_group.json() == {"deleted": True}
    assert devices.get_by_uuid(str(sw.device_uuid)).group_id is None

    rejected_secret = client.post(
        "/api/device-management/devices",
        json={"name": "Web-secret", "primary_address": "192.0.2.32", "ssh_password": "must-not-be-accepted"},
    )
    assert rejected_secret.status_code == 422

    token = client.post("/api/device-management/devices/delete-confirmation", json={"device_uuids": [created_uuid]})
    assert token.status_code == 200
    deleted = client.post(
        "/api/device-management/devices/batch-delete",
        json={"device_uuids": [created_uuid], "confirmation_token": token.json()["confirmation_token"]},
    )
    assert deleted.status_code == 200
    assert devices.get_by_uuid(created_uuid) is None
    assert devices.get_by_uuid(str(mr.device_uuid)).ssh_password == "secret-password"


def test_import_preview_confirm_creates_backup_and_uses_task_center(tmp_path: Path) -> None:
    client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    source = tmp_path / "devices.csv"
    _write_import_csv(source)

    preview = client.post("/api/device-management/imports/preview", files={"file": ("devices.csv", source.read_bytes(), "text/csv")})
    assert preview.status_code == 200
    body = preview.json()
    assert body["row_count"] == 1
    assert body["persistence"] == "preview_only"
    assert body["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "password" not in preview.text.lower()
    assert str(tmp_path) not in preview.text
    assert "web_staging" not in preview.text

    confirmed = client.post("/api/device-management/imports/confirm", json={"preview_token": body["preview_token"]})
    assert confirmed.status_code == 202
    assert confirmed.json()["action"] == "import_csv"
    assert "output_path" not in confirmed.text
    assert "path" not in confirmed.json()
    assert adapter.jobs[-1].task_type == "device_csv_import"
    assert adapter.jobs[-1].params["owner"] == WEB_TASK_OWNER
    assert adapter.jobs[-1].params["task_source"] == "local"
    assert adapter.completions[-1] is not None
    adapter.completions[-1](SimpleNamespace(exit_code=0, cancelled=False, payload={"result": {"created": 1, "skipped": 0, "errors": []}}))
    assert not list(service._import_staging_root("demo").glob("*"))
    backups = list(service.paths.site_backups_dir("demo").glob("device-import-*.sqlite"))
    assert backups


def test_import_preview_survives_service_restart_before_confirmation(
    tmp_path: Path,
) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    source = tmp_path / "restart-preview.csv"
    _write_import_csv(source, name="重启预览", address="192.0.2.41")
    with source.open("rb") as handle:
        preview = service.preview_import(source.name, handle)

    restarted_tasks = TaskApplicationService(paths=service.paths, site_name="demo")
    restarted_adapter = _CapturingProcessAdapter(restarted_tasks)
    restarted = DeviceManagementWebService(
        service.paths,
        restarted_tasks,
        site_name="demo",
        process_adapter=restarted_adapter,  # type: ignore[arg-type]
    )
    confirmed = restarted.confirm_import(
        DeviceImportConfirmRequestDTO(preview_token=preview.preview_token)
    )

    assert confirmed.action == "import_csv"
    assert restarted_adapter.jobs[-1].task_type == "device_csv_import"


def test_claimed_import_ignores_preview_expiry_while_owned_task_is_active(
    tmp_path: Path,
) -> None:
    _client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    source = tmp_path / "active-import.csv"
    _write_import_csv(source, name="活动导入", address="192.0.2.42")
    with source.open("rb") as handle:
        preview = service.preview_import(source.name, handle)
    confirmed = service.confirm_import(
        DeviceImportConfirmRequestDTO(preview_token=preview.preview_token)
    )
    staging_root = service._import_staging_root("demo")
    claimed = next(staging_root.glob(".claimed-*.preview.json"))
    payload = json.loads(claimed.read_text(encoding="utf-8"))
    payload["expires"] = 0
    claimed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    staged = staging_root / payload["staged_name"]

    restarted_tasks = TaskApplicationService(paths=service.paths, site_name="demo")
    restarted = DeviceManagementWebService(
        service.paths, restarted_tasks, site_name="demo"
    )
    restarted.current_site_id()

    assert restarted_tasks.repository("demo").get(confirmed.task_id).status in {  # type: ignore[union-attr]
        TaskState.PENDING,
        TaskState.STARTING,
        TaskState.RUNNING,
        TaskState.STOPPING,
    }
    assert claimed.exists()
    assert staged.exists()
    assert payload["task_id"] == confirmed.task_id
    assert payload["operation_id"].startswith("device-import-")
    adapter.completions[-1](
        SimpleNamespace(
            exit_code=0,
            cancelled=False,
            payload={"result": {"created": 1, "skipped": 0, "errors": []}},
        )
    )


def test_restart_reconciles_terminal_import_and_reclaims_claimed_files(
    tmp_path: Path,
) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    source = tmp_path / "terminal-import.csv"
    _write_import_csv(source, name="终态导入", address="192.0.2.43")
    with source.open("rb") as handle:
        preview = service.preview_import(source.name, handle)
    confirmed = service.confirm_import(
        DeviceImportConfirmRequestDTO(preview_token=preview.preview_token)
    )
    staging_root = service._import_staging_root("demo")
    claimed = next(staging_root.glob(".claimed-*.preview.json"))
    claimed_payload = json.loads(claimed.read_text(encoding="utf-8"))
    staged = staging_root / claimed_payload["staged_name"]
    service.task_service.record_external_event(
        confirmed.task_id,
        "finished",
        {"result": {"created": 1, "skipped": 0, "errors": []}},
        site_name="demo",
    )

    restarted_tasks = TaskApplicationService(paths=service.paths, site_name="demo")
    restarted = DeviceManagementWebService(
        service.paths, restarted_tasks, site_name="demo"
    )
    restarted.current_site_id()

    assert not claimed.exists()
    assert not staged.exists()
    audit = service._import_audit_path("demo", claimed_payload["operation_id"])
    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_payload["status"] == "APPLIED"
    assert audit_payload["task_id"] == confirmed.task_id


def test_device_upload_and_export_contracts_reject_browser_paths_and_oversize_files(
    tmp_path: Path,
) -> None:
    client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)

    assert client.post("/api/device-management/imports/preview", json={"path": "C:\\outside\\devices.csv"}).status_code == 422
    csv_bytes = b"name,primary_address\nweb,192.0.2.50\n"
    for filename in ("C:\\outside\\devices.csv", "..\\devices.csv", "\\\\server\\share\\devices.csv"):
        response = client.post(
            "/api/device-management/imports/preview",
            files={"file": (filename, csv_bytes, "text/csv")},
        )
        assert response.status_code == 422

    oversized = client.post(
        "/api/device-management/imports/preview",
        files={"file": ("devices.csv", b"x" * (MAX_DEVICE_IMPORT_BYTES + 1), "text/csv")},
    )
    assert oversized.status_code == 422
    assert not list(service._import_staging_root("demo").glob("*"))

    rejected_payloads = (
        ("/api/device-management/exports/csv", {"output_path": "C:\\outside\\devices.csv"}),
        ("/api/device-management/exports/template", {"output_path": "C:\\outside\\template.csv"}),
        ("/api/device-management/exports/securecrt", {"output_dir": "C:\\outside", "template_ini": "C:\\outside\\template.ini"}),
        ("/api/device-management/exports/omnipeek", {"line_name": "NetConsole", "output_path": "C:\\outside\\devices.nam"}),
    )
    for path, payload in rejected_payloads:
        assert client.post(path, json=payload).status_code == 422


def test_device_export_download_requires_owned_completed_task_and_safe_artifact(tmp_path: Path) -> None:
    client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    artifact_root = service._artifact_root("demo")
    artifact_id = "device-test-artifact"
    artifact = artifact_root / f"{artifact_id}.csv"
    artifact.write_text("name,primary_address\n安全,192.0.2.51\n", encoding="utf-8")
    now = datetime.now(UTC).isoformat()

    def save_task(task_id: str, **overrides: object) -> None:
        values = {
            "task_id": task_id,
            "task_type": "device_export_device_csv",
            "task_name": "设备 CSV 导出",
            "status": TaskState.COMPLETED,
            "created_time": now,
            "updated_time": now,
            "finished_time": now,
            "owner": WEB_TASK_OWNER,
            "source": "local",
            "site_name": "demo",
            "result": {
                "artifact_id": artifact_id,
                "artifact_name": artifact.name,
                "available": True,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": artifact.stat().st_size,
            },
        }
        values.update(overrides)
        service.task_service.repository("demo").save(TaskSnapshot(**values))

    save_task("device-export-owned")
    downloaded = client.get(
        "/api/device-management/exports/device-export-owned/download",
        params={"artifact_id": artifact_id},
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"name,primary_address")
    assert str(tmp_path) not in downloaded.text

    artifact.write_text("tampered", encoding="utf-8")
    tampered = client.get(
        "/api/device-management/exports/device-export-owned/download",
        params={"artifact_id": artifact_id},
    )
    assert tampered.status_code == 422
    artifact.write_text("name,primary_address\n安全,192.0.2.51\n", encoding="utf-8")

    for task_id, overrides in (
        ("device-export-wrong-owner", {"owner": "other"}),
        ("device-export-wrong-source", {"source": "web"}),
        ("device-export-wrong-type", {"task_type": "device_diagnostic_download"}),
        ("device-export-wrong-site", {"site_name": "other"}),
        ("device-export-pending", {"status": TaskState.PENDING}),
    ):
        save_task(task_id, **overrides)
        assert client.get(
            f"/api/device-management/exports/{task_id}/download",
            params={"artifact_id": artifact_id},
        ).status_code != 200

    save_task(
        "device-export-traversal",
        result={"artifact_id": "device-traversal", "artifact_name": "../outside.csv", "available": True},
    )
    assert client.get(
        "/api/device-management/exports/device-export-traversal/download",
        params={"artifact_id": "device-traversal"},
    ).status_code != 200

    outside = tmp_path / "outside.csv"
    outside.write_text("outside", encoding="utf-8")
    link = artifact_root / "link.csv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 测试环境不允许创建符号链接")
    save_task(
        "device-export-symlink",
        result={"artifact_id": "device-symlink", "artifact_name": link.name, "available": True},
    )
    assert client.get(
        "/api/device-management/exports/device-export-symlink/download",
        params={"artifact_id": "device-symlink"},
    ).status_code != 200


def test_device_management_parent_feature_gate_blocks_write_actions(tmp_path: Path) -> None:
    client, _service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    gate = client.app.state.feature_gate
    original = dict(gate.features["web.device_management"])
    gate.features["web.device_management"] = {**original, "enabled": False, "client_package": False}
    try:
        response = client.post(
            "/api/device-management/devices",
            json={"name": "gate-test", "primary_address": "192.0.2.60", "device_type": "SW"},
        )
    finally:
        gate.features["web.device_management"] = original
    assert response.status_code == 404


def test_device_management_action_gates_block_their_own_endpoints(
    tmp_path: Path,
) -> None:
    client, _service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    source = tmp_path / "gated-import.csv"
    _write_import_csv(source)
    cases = (
        (
            "web.device_management_write",
            "post",
            "/api/device-management/devices",
            {"json": {"name": "gate-write", "primary_address": "192.0.2.61"}},
        ),
        (
            "web.device_management_collect",
            "post",
            "/api/device-management/devices/batch-refresh-details",
            {"json": {"device_uuids": [str(mr.device_uuid)]}},
        ),
        (
            "web.device_management_import",
            "post",
            "/api/device-management/imports/preview",
            {"files": {"file": (source.name, source.read_bytes(), "text/csv")}},
        ),
        (
            "web.device_management_export",
            "post",
            "/api/device-management/exports/template",
            {"json": {}},
        ),
        (
            "web.device_management_desktop",
            "post",
            f"/api/device-management/devices/{mr.device_uuid}/external-terminal",
            {"json": {"terminal_type": "securecrt"}},
        ),
    )
    gate = client.app.state.feature_gate

    for feature_id, method, path, kwargs in cases:
        original = dict(gate.features[feature_id])
        gate.features[feature_id] = {
            **original,
            "enabled": False,
            "client_package": False,
        }
        try:
            response = getattr(client, method)(path, **kwargs)
        finally:
            gate.features[feature_id] = original
        assert response.status_code == 404, feature_id


@pytest.mark.parametrize(
    ("frozen", "expected_prefix"),
    (
        (False, [sys.executable, "-m", "netconsole.export_worker"]),
        (True, [sys.executable, "--export-worker"]),
    ),
)
def test_device_export_spawn_failure_uses_fixed_worker_and_cleans_job_files(tmp_path: Path, monkeypatch, frozen: bool, expected_prefix: list[str]) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    captured: dict[str, object] = {}

    def fail_popen(*args: object, **kwargs: object):
        captured["args"] = args
        captured.update(kwargs)
        raise OSError("worker unavailable")

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr("netconsole.services.device_management_web_service.subprocess.Popen", fail_popen)
    reference = service.start_template_export()
    assert reference.task_status == TaskState.FAILED.value
    assert captured["shell"] is False
    command = captured["args"][0]  # type: ignore[index]
    assert command[: len(expected_prefix)] == expected_prefix
    assert not list((service.paths.runtime_cache_dir / "export_jobs").glob(f"{reference.task_id}.*"))
    assert not list(service._artifact_root("demo").glob("*"))
    snapshot = service.task_service.repository("demo").get(reference.task_id)
    assert snapshot is not None
    assert snapshot.owner == WEB_TASK_OWNER
    assert snapshot.source == "local"
    assert snapshot.task_type in {"device_export_device_template_csv"}
    assert "output_path" not in reference.model_dump()


def test_device_export_lifecycle_stop_uses_task_site_and_marks_cancelled(tmp_path: Path) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    now = datetime.now(UTC).isoformat()
    task_id = "device-export-lifecycle"
    service.task_service.repository("demo").save(
        TaskSnapshot(
            task_id=task_id,
            task_type="device_export_device_csv",
            task_name="设备导出生命周期",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            owner=WEB_TASK_OWNER,
            source="local",
            site_name="demo",
        )
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    process = FakeProcess()
    cancel_path = service.paths.runtime_cache_dir / "export_jobs" / f"{task_id}.cancel"
    cancel_path.parent.mkdir(parents=True, exist_ok=True)
    service._export_processes[task_id] = process  # type: ignore[assignment]
    service._export_artifacts[task_id] = {"site": "demo", "cancel_path": cancel_path}

    asyncio.run(service.stop_exports())

    assert process.terminated is True
    assert cancel_path.read_text(encoding="utf-8") == "cancelled"
    assert service.task_service.repository("demo").get(task_id).status is TaskState.CANCELLED  # type: ignore[union-attr]


def test_securecrt_export_is_finalized_as_controlled_zip(tmp_path: Path) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    root = service._artifact_root("demo")
    artifact_id = "device-securecrt-test"
    target = root / f"{artifact_id}.zip"
    staging = root / f".{artifact_id}-sessions"
    staging.mkdir()
    (staging / "Group" / "device.vbs").parent.mkdir()
    (staging / "Group" / "device.vbs").write_text("session", encoding="utf-8")
    result = service._finalize_export_artifact(
        {
            "artifact_id": artifact_id,
            "artifact_root": root,
            "artifact_name": target.name,
            "export_type": "securecrt_sessions",
            "target": target,
            "tmp_path": root / "unused.tmp",
            "zip_tmp": root / f"{target.name}.tmp",
            "staging_dir": staging,
        },
        {"path": str(staging), "row_count": 1},
    )
    assert result["artifact_id"] == artifact_id
    assert result["artifact_name"] == target.name
    assert not staging.exists()
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["Group/device.vbs", "_netconsole_manifest.json"]
        assert archive.read("Group/device.vbs") == b"session"
    staging.mkdir()
    nested = staging / "nested"
    nested.mkdir()
    result = service._finalize_export_artifact(
        {
            "artifact_id": artifact_id,
            "artifact_root": root,
            "artifact_name": target.name,
            "export_type": "securecrt_sessions",
            "target": target,
            "tmp_path": root / "unused.tmp",
            "zip_tmp": root / f"{target.name}.tmp",
            "staging_dir": staging,
        },
        {"path": str(nested), "row_count": 1},
    )
    assert result["available"] is True


def test_device_export_finalizer_rejects_another_artifact_in_controlled_root(tmp_path: Path) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    root = service._artifact_root("demo")
    target = root / "expected.csv"
    other = root / "other.csv"
    other.write_text("other", encoding="utf-8")

    with pytest.raises(ValueError, match="未绑定"):
        service._finalize_export_artifact(
            {
                "artifact_id": "device-bound-output",
                "artifact_root": root,
                "artifact_name": target.name,
                "export_type": "device_csv",
                "target": target,
                "tmp_path": root / "expected.tmp",
            },
            {"output_path": str(other), "row_count": 1},
        )

    assert other.exists()
    assert not target.exists()


def test_diagnostic_task_result_does_not_expose_file_path(tmp_path: Path, monkeypatch) -> None:
    _client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    class FakeDiagnosticDownloadService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def download(self, _device: Device) -> SimpleNamespace:
            return SimpleNamespace(
                device_id=mr.id,
                device_name=mr.name,
                file_path=r"C:\\outside\\diagnostic.txt",
                status="success",
                error_message=None,
                elapsed_ms=2,
                success=True,
            )

    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.DiagnosticDownloadService",
        FakeDiagnosticDownloadService,
    )
    result = run_device_diagnostic_download(
        JobContext(
            "device-diagnostic-safe-result",
            "device_diagnostic_download",
            {"site_name": "demo", "device_uuids": [str(mr.device_uuid)]},
            None,
            lambda: False,
            service.paths,
        )
    )
    assert "file_path" not in result["results"][0]
    assert "outside" not in str(result)


def test_import_completion_never_restores_whole_database_and_preserves_audit(
    tmp_path: Path,
) -> None:
    _client, service, _adapter, devices, _facts, _mr, _sw = _fixture(tmp_path)
    temporary = devices.create(
        Device(name="待回滚设备", primary_address="192.0.2.99", device_type="SW")
    )
    staged = service._import_staging_root("demo") / "fake-failure.csv"
    claimed = service._import_staging_root("demo") / ".claimed-failure.preview.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("placeholder", encoding="utf-8")
    claimed.write_text("{}", encoding="utf-8")
    service._write_import_audit(
        "demo",
        "device-import-failed",
        {
            "status": "PENDING",
            "task_id": "task-failed",
            "source_file": "devices.csv",
            "source_sha256": "a" * 64,
        },
    )
    service._finish_import(
        "demo",
        "device-import-failed",
        staged,
        claimed,
        SimpleNamespace(
            exit_code=1,
            cancelled=False,
            payload={"result": {"errors": ["fake failure"], "skipped": 0}},
        ),
    )
    assert devices.get_by_uuid(str(temporary.device_uuid)) is not None
    failed_audit = (
        service.paths.site_imports_dir("demo")
        / "device_import_audit"
        / "device-import-failed.json"
    )
    failed_payload = json.loads(failed_audit.read_text(encoding="utf-8"))
    assert failed_payload["status"] == "FAILED"
    assert failed_payload["task_id"] == "task-failed"
    assert failed_payload["source_sha256"] == "a" * 64

    staged = service._import_staging_root("demo") / "fake-applied.csv"
    claimed = service._import_staging_root("demo") / ".claimed-applied.preview.json"
    staged.write_text("placeholder", encoding="utf-8")
    claimed.write_text("{}", encoding="utf-8")
    service._finish_import(
        "demo",
        "device-import-applied",
        staged,
        claimed,
        SimpleNamespace(
            exit_code=0,
            cancelled=False,
            payload={"result": {"created": 1, "skipped": 0, "errors": []}},
        ),
    )
    applied_audit = (
        service.paths.site_imports_dir("demo")
        / "device_import_audit"
        / "device-import-applied.json"
    )
    assert '"status": "APPLIED"' in applied_audit.read_text(encoding="utf-8")


def test_batch_refresh_and_external_terminal_are_controlled_contracts(tmp_path: Path) -> None:
    client, _service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    refreshed = client.post("/api/device-management/devices/batch-refresh-details", json={"device_uuids": [str(mr.device_uuid)]})
    assert refreshed.status_code == 202
    assert refreshed.json()["action"] == "batch_refresh_details"
    assert adapter.jobs[-1].task_type == "device_detail_collect"
    assert adapter.jobs[-1].params["owner"] == WEB_TASK_OWNER
    assert adapter.jobs[-1].params["task_source"] == "local"

    terminal = client.post(f"/api/device-management/devices/{mr.device_uuid}/external-terminal", json={"terminal_type": "securecrt"})
    assert terminal.status_code == 200
    assert terminal.json() == {"native_action": "launchTerminal", "device_uuid": str(mr.device_uuid), "terminal_type": "securecrt", "requires_desktop_bridge": True}
    assert "secret-password" not in terminal.text


def test_generic_device_task_query_and_cancel_enforce_owner_source_site_and_type(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    started = client.post(
        "/api/device-management/devices/batch-refresh-details",
        json={"device_uuids": [str(mr.device_uuid)]},
    )
    task_id = started.json()["tasks"][0]["task_id"]

    assert client.get(f"/api/device-management/tasks/{task_id}").status_code == 200
    cancelled = client.post(f"/api/device-management/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert adapter.cancelled == [task_id]

    now = datetime.now(UTC).isoformat()
    base = {
        "task_type": "device_detail_collect",
        "task_name": "隔离测试",
        "status": TaskState.PENDING,
        "created_time": now,
        "updated_time": now,
        "owner": WEB_TASK_OWNER,
        "source": "local",
        "site_name": "demo",
    }
    invalid_tasks = {
        "wrong-owner": {"owner": "other"},
        "wrong-source": {"source": "web"},
        "wrong-site": {"site_name": "other"},
        "wrong-type": {"task_type": "config_collect"},
    }
    for invalid_id, overrides in invalid_tasks.items():
        service.task_service.repository("demo").save(
            TaskSnapshot(task_id=invalid_id, **{**base, **overrides})
        )
        assert (
            client.get(f"/api/device-management/tasks/{invalid_id}").status_code == 404
        )
        assert (
            client.post(f"/api/device-management/tasks/{invalid_id}/cancel").status_code
            == 404
        )


def test_device_detail_collect_handler_uses_formal_collector_without_real_devices(
    tmp_path: Path, monkeypatch
) -> None:
    _client, service, _adapter, _devices, _facts, mr, sw = _fixture(tmp_path)
    collected: list[str] = []

    def fake_collect(device: Device, site: str, *, repository, paths):
        collected.append(str(device.device_uuid))
        assert site == "demo"
        assert paths is service.paths
        assert repository is not None
        return SimpleNamespace(
            success=True,
            collect_run_uuid=f"run-{device.name}",
            facts_updated=True,
            interfaces_updated=1,
            optical_modules_updated=0,
            lldp_neighbors_updated=0,
            error_message="",
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_collect_service.collect_h3c_device_details",
        fake_collect,
    )
    result = run_device_detail_collect(
        JobContext(
            "device-detail-formal-handler",
            "device_detail_collect",
            {
                "site_name": "demo",
                "device_uuids": [str(mr.device_uuid), str(sw.device_uuid)],
            },
            None,
            lambda: False,
            service.paths,
        )
    )

    assert set(collected) == {str(mr.device_uuid), str(sw.device_uuid)}
    assert result["total"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
