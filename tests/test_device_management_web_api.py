from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.device_management_router import router
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.snmp_models import DeviceSnmpProfileResult
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_management_web_service import (
    DEVICE_CONNECTION_TEST_TASK_TYPE,
    DeviceManagementWebService,
    run_device_connection_test,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _CapturingProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []

    def start_job(self, job, **_kwargs) -> str:
        self.jobs.append(job)
        return self.tasks.prepare(job).job.job_id

    def shutdown(self) -> None:
        return None


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
        "device",
        "app_root",
        "data_root",
        "_emit_log_events",
        "_cancel_grace_ms",
    }
    assert "secret-password" not in str(adapter.jobs[0].to_dict())
    assert "private-community" not in str(adapter.jobs[0].to_dict())


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


def test_router_exposes_preview_and_task_submission_but_no_write_or_terminal_endpoint(tmp_path: Path) -> None:
    client, *_rest = _fixture(tmp_path)
    paths = client.app.openapi()["paths"]
    device_paths = {path: methods for path, methods in paths.items() if path.startswith("/api/device-management")}

    posts = {path for path, methods in device_paths.items() if "post" in methods}
    assert posts == {
        "/api/device-management/devices/{device_uuid}/edit-preview",
        "/api/device-management/devices/{device_uuid}/connection-tests",
    }
    assert not any(token in path for path in device_paths for token in ("password", "terminal", "save", "delete"))
