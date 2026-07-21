from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
from io import BytesIO
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from netconsole.application.desktop import (
    DesktopActionResolver,
    DesktopActionResult,
    DesktopActionService,
    RegisteredLaunch,
)
from netconsole.backend.api.device_management_router import router
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import SiteManager
from netconsole.infrastructure.desktop import LocalDesktopAdapter
from netconsole.models.api.device_management import (
    DeviceExportRequestDTO,
    DeviceImportConfirmRequestDTO,
    DeviceSecureCrtExportRequestDTO,
    DeviceTaskReferenceDTO,
)
from netconsole.models.device import Device
from netconsole.models.device_snmp import DeviceSnmpProfileResult
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_detail_repository import DeviceDetailRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_management_web_service import (
    DEVICE_CONNECTION_TEST_TASK_TYPE,
    DEVICE_OPTICAL_REFRESH_TASK_TYPE,
    DEVICE_OMNIPEEK_PREVIEW_TASK_TYPE,
    DEVICE_IMPORT_CLAIM_GRACE_SECONDS,
    DEVICE_IMPORT_PREVIEW_TTL_SECONDS,
    DEVICE_IMPORT_TASK_TYPE,
    DEVICE_TERMINAL_ACTION_IDS,
    MAX_DEVICE_IMPORT_BYTES,
    WEB_TASK_OWNER,
    DeviceManagementWebService,
    run_device_connection_test,
    run_device_csv_import,
    run_device_detail_collect,
    run_device_diagnostic_download,
    run_device_optical_refresh,
)
from netconsole.services.device_command_profile_service import (
    resolve_device_inventory_profile,
)
from netconsole.services.device_operation_service import (
    DeviceInventoryRefreshFailed,
    DeviceOperationService,
)
from netconsole.services.job_center.job_runner import JobRunner
from netconsole.services.device_import_export import TEMPLATE_FIELDS
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _CapturingProcessAdapter:
    supports_runtime_bootstrap = True

    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []
        self.completions = []
        self.block_start = False
        self.start_entered = Event()
        self.second_start_entered = Event()
        self.release_start = Event()
        self.cancelled: list[str] = []
        self.bootstrap_buffers: list[bytearray] = []
        self.pending_bootstraps: dict[str, bytearray] = {}

    def start_job(self, job, *, runtime_bootstrap=None, **kwargs) -> str:
        self.jobs.append(job)
        self.completions.append(kwargs.get("on_complete"))
        if runtime_bootstrap is not None:
            assert isinstance(runtime_bootstrap, bytearray)
            self.bootstrap_buffers.append(runtime_bootstrap)
            self.pending_bootstraps[job.job_id] = bytearray(runtime_bootstrap)
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
        bootstrap = self.pending_bootstraps.pop(task_id, None)
        if bootstrap is not None:
            bootstrap[:] = b"\x00" * len(bootstrap)
        return any(job.job_id == task_id for job in self.jobs)

    def take_bootstrap(self, task_id: str) -> bytearray:
        return self.pending_bootstraps.pop(task_id)


class _RuntimeBootstrapContext:
    def __init__(self, job, paths: PathResolver, bootstrap: bytearray) -> None:
        self.job_id = job.job_id
        self.task_type = job.task_type
        self.params = job.params
        self.paths = paths
        self._bootstrap: bytearray | None = bootstrap
        self.progress_events: list[tuple[object, ...]] = []

    def consume_runtime_bootstrap(self) -> bytearray:
        if self._bootstrap is None:
            raise RuntimeError("bootstrap 已消费")
        bootstrap = self._bootstrap
        self._bootstrap = None
        return bootstrap

    def should_cancel(self) -> bool:
        return False

    def check_cancelled(self) -> None:
        return None

    def progress(self, *values) -> None:
        self.progress_events.append(values)


class _FakeDesktopAdapter:
    def __init__(self) -> None:
        self.terminal_calls: list[RegisteredLaunch] = []

    def launch_registered_terminal(
        self, launch: RegisteredLaunch
    ) -> DesktopActionResult:
        self.terminal_calls.append(launch)
        return DesktopActionResult(True, "launched", "外部终端已启动")


def _desktop_actions(
    tmp_path: Path, *device_uuids: str
) -> tuple[DesktopActionService, _FakeDesktopAdapter]:
    executable = tmp_path / "SecureCRT.exe"
    executable.write_bytes(b"fake executable")
    adapter = _FakeDesktopAdapter()
    terminals = {
        (action_id, device_uuid): RegisteredLaunch(executable)
        for action_id in DEVICE_TERMINAL_ACTION_IDS.values()
        for device_uuid in device_uuids
    }
    return (
        DesktopActionService(
            RuntimeMode.DESKTOP,
            adapter,
            DesktopActionResolver(terminals=terminals),
            audit=lambda _event, _message: None,
        ),
        adapter,
    )


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


def _fixture(tmp_path: Path, *, app_root: Path | None = None):
    paths = PathResolver(
        app_root=app_root or tmp_path / "app", data_root=tmp_path / "local"
    )
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
    desktop_actions, _desktop_adapter = _desktop_actions(
        tmp_path, str(mr.device_uuid), str(sw.device_uuid)
    )
    SettingsStore(paths).set_value(
        "external_terminal/securecrt_path", str(tmp_path / "SecureCRT.exe")
    )
    service = DeviceManagementWebService(
        paths,
        tasks,
        desktop_action_service=desktop_actions,
        site_name="demo",
        process_adapter=adapter,  # type: ignore[arg-type]
        device_operation_service=DeviceOperationService(
            PathResolver(
                app_root=Path(__file__).parents[1], data_root=paths.data_root
            ),
            DeviceDetailRepository(paths, site_name="demo"),
            tasks,
            adapter,
        ),
    )
    app = FastAPI()
    app.state.device_management_service = service
    app.state.feature_gate = FeatureGate(paths.app_root)
    for feature_id in (
        "web.device_management_write",
        "web.device_management_collect",
        "web.device_management_import",
        "web.device_management_export",
        "web.device_management_desktop",
        "web.device_form_connection_test",
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
        owner=WEB_TASK_OWNER,
        source="local",
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
    assert body["device"]["web_url"] == "https://192.0.2.12:443"
    assert "***" in response.text
    assert "secret-password" not in response.text
    assert "telnet-secret" not in response.text
    assert "raw_log" not in response.text


def test_device_history_uses_real_fact_repository_and_paginates(tmp_path: Path) -> None:
    client, _service, _adapter, _devices, facts, mr, _sw = _fixture(tmp_path)
    for collected_at, link_status in (
        ("2026-07-16T10:00:00", "DOWN"),
        ("2026-07-16T11:00:00", "UP"),
    ):
        facts.append_interface_history(
            {
                "device_uuid": str(mr.device_uuid),
                "interface_name": "GE1/0/1",
                "collected_at": collected_at,
                "link_status": link_status,
                "last_change": collected_at,
                "raw_log_path": "C:\\private\\device-history.log",
            }
        )

    repository_rows = facts.list_object_history_page(
        "interface",
        str(mr.device_uuid),
        "GE1/0/1",
        limit=1,
        offset=0,
    )
    assert repository_rows[0]["last_change"] == "2026-07-16T11:00:00"
    facts.append_optical_history(
        {
            "device_uuid": str(mr.device_uuid),
            "interface_name": "GE1/0/1",
            "collected_at": "2026-07-16T12:00:00",
            "status": "no_light",
            "rx_power": "-40 dBm",
        }
    )
    optical_repository_rows = facts.list_object_history_page(
        "optical",
        str(mr.device_uuid),
        "GE1/0/1",
        limit=1,
        offset=0,
    )
    assert optical_repository_rows[0]["status"] == "no_light"

    response = client.get(
        f"/api/device-management/devices/{mr.device_uuid}/history",
        params={
            "kind": "interface",
            "object_name": "GE1/0/1",
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["total_pages"] == 2
    assert response.json()["items"][0]["values"]["link_status"] == "UP"
    assert "last_change" not in response.json()["items"][0]["values"]
    assert response.json()["source"]["source"] == "device_management_web_service"
    assert "raw_log_path" not in response.text
    assert "C:\\private" not in response.text

    optical_response = client.get(
        f"/api/device-management/devices/{mr.device_uuid}/history",
        params={"kind": "optical", "object_name": "GE1/0/1"},
    )
    assert optical_response.status_code == 200
    assert optical_response.json()["items"][0]["values"]["rx_power"] == "-40 dBm"
    assert "status" not in optical_response.json()["items"][0]["values"]


def test_real_edit_is_validated_and_persisted(
    tmp_path: Path,
) -> None:
    client, _service, _adapter, devices, _facts, mr, _sw = _fixture(tmp_path)
    payload = {
        "name": "  MR-NEW  ",
        "primary_address": "192.0.2.99",
        "device_vendor": "H3C",
        "device_type": "AC",
        "ssh_enabled": True,
        "telnet_enabled": False,
    }

    response = client.put(
        f"/api/device-management/devices/{mr.device_uuid}", json=payload
    )
    rejected = client.put(
        f"/api/device-management/devices/{mr.device_uuid}",
        json={**payload, "device_vendor": "unsupported"},
    )
    rejected_v3 = client.put(
        f"/api/device-management/devices/{mr.device_uuid}",
        json={**payload, "snmp_v3_enabled": True},
    )
    rejected_rw = client.put(
        f"/api/device-management/devices/{mr.device_uuid}",
        json={**payload, "snmp_rw_community": "write-secret"},
    )
    detail = client.get(f"/api/device-management/devices/{mr.device_uuid}").json()["device"]

    assert response.status_code == 200
    assert response.json()["device"]["name"] == "MR-NEW"
    assert rejected.status_code == 422
    assert rejected_v3.status_code == 422
    assert rejected_rw.status_code == 422
    assert "snmp_v3_enabled" not in detail
    assert "snmp_rw_community" not in detail
    assert devices.get_by_uuid(str(mr.device_uuid)).name == "MR-NEW"


def test_edit_profile_and_write_responses_do_not_build_legacy_full_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    def fail_large_read(*_args, **_kwargs):
        raise AssertionError("编辑资料不得读取设备大快照表")

    monkeypatch.setattr(
        DeviceFactRepository, "list_device_interfaces", fail_large_read
    )
    monkeypatch.setattr(
        DeviceFactRepository, "list_optical_modules", fail_large_read
    )
    monkeypatch.setattr(
        DeviceFactRepository, "list_lldp_neighbors", fail_large_read
    )
    edit = client.get(
        f"/api/device-management/devices/{mr.device_uuid}/edit-profile"
    )
    assert edit.status_code == 200
    assert edit.json()["device_uuid"] == str(mr.device_uuid)
    assert "secret-password" not in edit.text

    monkeypatch.setattr(
        service,
        "get_device_detail",
        lambda *_args, **_kwargs: fail_large_read(),
    )
    created = client.post(
        "/api/device-management/devices",
        json={
            "name": "narrow-write",
            "primary_address": "192.0.2.88",
            "device_vendor": "H3C",
            "device_type": "SW",
        },
    )
    updated = client.put(
        f"/api/device-management/devices/{mr.device_uuid}",
        json={
            "name": "MR-NARROW",
            "primary_address": "192.0.2.12",
            "device_vendor": "H3C",
            "device_type": "AC",
            "ssh_enabled": False,
            "ssh_port": 2222,
            "telnet_enabled": True,
            "telnet_port": 2323,
            "snmp_enabled": False,
            "snmp_port": 1161,
        },
    )
    duplicated = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/duplicate"
    )
    assert created.status_code == 201
    assert updated.status_code == 200
    assert duplicated.status_code == 201
    roundtrip = client.get(
        f"/api/device-management/devices/{mr.device_uuid}/edit-profile"
    ).json()
    assert roundtrip["ssh_enabled"] is False
    assert roundtrip["ssh_port"] == 2222
    assert roundtrip["telnet_enabled"] is True
    assert roundtrip["telnet_port"] == 2323
    assert roundtrip["snmp_enabled"] is False
    assert roundtrip["snmp_port"] == 1161

    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/device-management/devices/{device_uuid}"][
        "get"
    ]["deprecated"] is True
    assert (
        "/api/device-management/devices/{device_uuid}/edit-profile"
        in schema["paths"]
    )


def test_router_redacts_file_not_found_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    def missing(_device_uuid: str):
        raise FileNotFoundError(r"C:\private\device-secret.json")

    monkeypatch.setattr(service, "get_device_edit_profile", missing)
    response = client.get(
        f"/api/device-management/devices/{mr.device_uuid}/edit-profile"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "资源不存在"}
    assert "C:\\private" not in response.text


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


@pytest.mark.parametrize(
    "overrides",
    (
        {"owner": "foreign-owner"},
        {"source": "agent"},
        {"site_name": "foreign-site"},
        {"task_type": "config_collect"},
    ),
    ids=("owner", "source", "site", "task-type"),
)
def test_device_task_views_and_dedupe_ignore_foreign_scope(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    now = datetime.now(UTC).isoformat()
    foreign_task_id = f"device-test-ssh-foreign-{next(iter(overrides))}"
    values: dict[str, object] = {
        "task_type": DEVICE_CONNECTION_TEST_TASK_TYPE,
        "task_name": "异域任务",
        "status": TaskState.RUNNING,
        "created_time": now,
        "updated_time": now,
        "device": str(mr.device_uuid),
        "owner": WEB_TASK_OWNER,
        "source": "local",
        "site_name": "demo",
    }
    service.task_service.repository("demo").save(
        TaskSnapshot(task_id=foreign_task_id, **{**values, **overrides})
    )

    listed = client.get("/api/device-management/devices").json()
    listed_mr = next(
        item for item in listed["items"] if item["device_uuid"] == str(mr.device_uuid)
    )
    assert listed_mr["connection_status"] == "UNKNOWN"
    detail = client.get(
        f"/api/device-management/devices/{mr.device_uuid}"
    ).json()
    assert foreign_task_id not in {
        task["task_id"] for task in detail["recent_tasks"]
    }

    started = client.post(
        f"/api/device-management/devices/{mr.device_uuid}/connection-tests",
        json={"protocol": "SSH"},
    )
    assert started.status_code == 202
    assert started.json()["task_id"] != foreign_task_id
    assert len(adapter.jobs) == 1


def test_production_service_follows_runtime_site_switch(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "local")
    sites = SiteManager(paths)
    sites.ensure_demo_site()
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    adapter = _CapturingProcessAdapter(tasks)
    desktop_actions, _desktop_adapter = _desktop_actions(tmp_path)
    service = DeviceManagementWebService(
        paths,
        tasks,
        desktop_action_service=desktop_actions,
        process_adapter=adapter,  # type: ignore[arg-type]
    )

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


def test_unsaved_form_connection_tests_use_nonserialized_runtime_bootstrap(
    tmp_path: Path, monkeypatch
) -> None:
    client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    ssh_password = "form-ssh-password-must-not-be-persisted"
    telnet_password = "form-telnet-password-must-not-be-persisted"
    community = "form-community-must-not-be-persisted"
    observed: list[tuple[str, str | None]] = []

    def fake_connection(device: Device):
        protocol = "SSH" if device.ssh_enabled else "TELNET"
        observed.append(
            (
                protocol,
                device.ssh_password if protocol == "SSH" else device.telnet_password,
            )
        )
        return SimpleNamespace(
            success=True,
            status="ok",
            message="connected",
            method="primary_direct",
            host=device.primary_address,
            port=device.ssh_port if protocol == "SSH" else device.telnet_port,
            elapsed_ms=3,
            prompt="<FORM-SW>",
            error_type=None,
            suggestion=None,
        )

    def fake_snmp(_self, device: Device, **_kwargs):
        observed.append(("SNMP", device.snmp_ro_community))
        return DeviceSnmpProfileResult(
            status="success",
            error_message=f"response mentioned {community}",
            sys_name="FORM-SW",
            model="S6520",
            os_family="Comware",
            interface_count=48,
            latency_ms=4,
        )

    monkeypatch.setattr(
        "netconsole.services.netmiko_connection.test_device_connection",
        fake_connection,
    )
    monkeypatch.setattr(
        "netconsole.services.device_snmp_detect_service.DeviceSnmpDetectService.detect",
        fake_snmp,
    )
    payload = {
        "name": "未保存表单设备",
        "primary_address": "198.51.100.88",
        "ssh_enabled": True,
        "ssh_password": ssh_password,
        "telnet_enabled": True,
        "telnet_password": telnet_password,
        "snmp_enabled": True,
        "snmp_v2c_enabled": True,
        "snmp_ro_community": community,
    }

    for protocol in ("SSH", "TELNET", "SNMP"):
        started = client.post(
            "/api/device-management/connection-tests/form",
            json={**payload, "protocol": protocol},
        )
        assert started.status_code == 202
        assert ssh_password not in started.text
        assert telnet_password not in started.text
        assert community not in started.text
        job = adapter.jobs[-1]
        serialized_params = json.dumps(job.params, ensure_ascii=False)
        assert ssh_password not in serialized_params
        assert telnet_password not in serialized_params
        assert community not in serialized_params
        assert "token" not in serialized_params.lower()
        assert all(value == 0 for value in adapter.bootstrap_buffers[-1])
        job_file = service.paths.runtime_cache_dir / "background_jobs" / f"{job.job_id}.json"
        disk_job = job_file.read_text(encoding="utf-8")
        assert ssh_password not in disk_job
        assert telnet_password not in disk_job
        assert community not in disk_job
        worker_bootstrap = adapter.take_bootstrap(job.job_id)
        bootstrap_payload = json.loads(bytes(worker_bootstrap).decode("utf-8"))
        if protocol == "SSH":
            assert "telnet_password" not in bootstrap_payload
            assert "snmp_ro_community" not in bootstrap_payload
        elif protocol == "TELNET":
            assert "ssh_password" not in bootstrap_payload
            assert "snmp_ro_community" not in bootstrap_payload
        else:
            assert "ssh_password" not in bootstrap_payload
            assert "telnet_password" not in bootstrap_payload
        context = _RuntimeBootstrapContext(job, service.paths, worker_bootstrap)
        result = run_device_connection_test(context)  # type: ignore[arg-type]
        assert result["success"] is True
        assert result["protocol"] == protocol
        assert ssh_password not in json.dumps(result, ensure_ascii=False)
        assert telnet_password not in json.dumps(result, ensure_ascii=False)
        assert community not in json.dumps(result, ensure_ascii=False)
        assert context._bootstrap is None
        assert all(value == 0 for value in worker_bootstrap)
        with pytest.raises(RuntimeError, match="已消费"):
            context.consume_runtime_bootstrap()

    assert observed == [
        ("SSH", ssh_password),
        ("TELNET", telnet_password),
        ("SNMP", community),
    ]
    for path in service.paths.data_root.rglob("*"):
        if not path.is_file():
            continue
        persisted = path.read_bytes()
        assert ssh_password.encode("utf-8") not in persisted
        assert telnet_password.encode("utf-8") not in persisted
        assert community.encode("utf-8") not in persisted

    forged = client.post(
        "/api/device-management/connection-tests/form",
        json={**payload, "protocol": "SSH", "command": "whoami"},
    )
    assert forged.status_code == 422


def test_unsaved_form_connection_test_cancel_clears_runtime_bootstrap(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    secret = "cancelled-form-secret"
    started = client.post(
        "/api/device-management/connection-tests/form",
        json={
            "name": "待取消表单测试",
            "primary_address": "198.51.100.89",
            "protocol": "SSH",
            "ssh_enabled": True,
            "ssh_password": secret,
            "telnet_enabled": False,
        },
    )
    assert started.status_code == 202
    task_id = started.json()["task_id"]
    assert task_id in adapter.pending_bootstraps
    assert secret not in json.dumps(adapter.jobs[-1].params, ensure_ascii=False)
    pending = adapter.pending_bootstraps[task_id]

    cancelled = client.post(f"/api/device-management/tasks/{task_id}/cancel")

    assert cancelled.status_code == 200
    assert adapter.cancelled == [task_id]
    assert task_id not in adapter.pending_bootstraps
    assert all(value == 0 for value in pending)


def test_unsaved_form_connection_test_clears_worker_secrets_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    secret = "failed-form-secret"
    observed_devices = []

    def fail_connection(device):
        observed_devices.append(device)
        assert device.ssh_password == secret
        raise TimeoutError(f"connection timed out with {secret}")

    monkeypatch.setattr(
        "netconsole.services.netmiko_connection.test_device_connection",
        fail_connection,
    )
    started = client.post(
        "/api/device-management/connection-tests/form",
        json={
            "name": "失败清理设备",
            "primary_address": "198.51.100.91",
            "protocol": "SSH",
            "ssh_enabled": True,
            "ssh_password": secret,
            "telnet_enabled": False,
        },
    )
    assert started.status_code == 202
    job = adapter.jobs[-1]
    worker_bootstrap = adapter.take_bootstrap(job.job_id)

    with pytest.raises(RuntimeError, match="timed out") as captured:
        run_device_connection_test(  # type: ignore[arg-type]
            _RuntimeBootstrapContext(job, service.paths, worker_bootstrap)
        )

    assert secret not in str(captured.value)
    assert all(value == 0 for value in worker_bootstrap)
    assert observed_devices[0].ssh_password is None
    assert observed_devices[0].password is None


def test_unsaved_form_connection_test_is_blocked_without_shared_runtime(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    adapter.supports_runtime_bootstrap = False
    secret = "blocked-form-secret"

    response = client.post(
        "/api/device-management/connection-tests/form",
        json={
            "name": "等待共享运行时",
            "primary_address": "198.51.100.90",
            "protocol": "SSH",
            "ssh_enabled": True,
            "ssh_password": secret,
            "telnet_enabled": False,
        },
    )

    assert response.status_code == 503
    assert "暂时无法创建" in response.text
    assert secret not in response.text
    assert not adapter.jobs
    for path in service.paths.data_root.rglob("*"):
        if path.is_file():
            assert secret.encode("utf-8") not in path.read_bytes()


def test_edit_form_connection_test_preserves_or_clears_existing_secret(
    tmp_path: Path, monkeypatch
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    observed: list[str | None] = []

    def fake_connection(device: Device):
        observed.append(device.ssh_password)
        return SimpleNamespace(
            success=True,
            status="ok",
            message="connected",
            method="primary_direct",
            host=device.primary_address,
            port=device.ssh_port,
            elapsed_ms=2,
            prompt="<MR-EDIT>",
            error_type=None,
            suggestion=None,
        )

    monkeypatch.setattr(
        "netconsole.services.netmiko_connection.test_device_connection",
        fake_connection,
    )
    base = {
        "device_uuid": str(mr.device_uuid),
        "name": mr.name,
        "primary_address": mr.primary_address,
        "protocol": "SSH",
        "ssh_enabled": True,
        "telnet_enabled": False,
    }

    for request_payload in (
        base,
        {**base, "clear_secret_fields": ["ssh_password"]},
    ):
        started = client.post(
            "/api/device-management/connection-tests/form", json=request_payload
        )
        assert started.status_code == 202
        job = adapter.jobs[-1]
        context = _RuntimeBootstrapContext(
            job, service.paths, adapter.take_bootstrap(job.job_id)
        )
        run_device_connection_test(context)  # type: ignore[arg-type]

    assert observed == ["secret-password", None]
    assert _devices.get_by_uuid(str(mr.device_uuid)).ssh_password == "secret-password"


def test_router_exposes_device_management_parity_endpoints_without_arbitrary_terminal_or_secret_routes(tmp_path: Path) -> None:
    client, *_rest = _fixture(tmp_path)
    paths = client.app.openapi()["paths"]
    device_paths = {path: methods for path, methods in paths.items() if path.startswith("/api/device-management")}

    posts = {path for path, methods in device_paths.items() if "post" in methods}
    gets = {path for path, methods in device_paths.items() if "get" in methods}
    assert {
        "/api/device-management/connection-tests/form",
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
        "/api/device-management/exports/securecrt-with-template",
        "/api/device-management/exports/omnipeek",
        "/api/device-management/exports/omnipeek-preview",
        "/api/device-management/diagnostic-download",
        "/api/device-management/devices/{device_uuid}/external-terminal",
    }.issubset(posts)
    assert "/api/device-management/diagnostics/{task_id}/download" in gets
    assert not any("password" in path or "secret" in path or path.endswith("/shell") for path in device_paths)


def test_omnipeek_export_requires_real_background_preview_and_selection(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    started = client.post(
        "/api/device-management/exports/omnipeek-preview",
        json={"device_uuids": [str(mr.device_uuid)]},
    )
    assert started.status_code == 202
    task_id = started.json()["task_id"]
    assert adapter.jobs[-1].task_type == DEVICE_OMNIPEEK_PREVIEW_TASK_TYPE
    assert adapter.jobs[-1].params["owner"] == WEB_TASK_OWNER
    assert adapter.jobs[-1].params["selected_device_uuids"] == [
        str(mr.device_uuid)
    ]

    pending = service.task_service.repository("demo").get(task_id)
    assert pending is not None
    service.task_service.repository("demo").save(
        replace(
            pending,
            status=TaskState.COMPLETED,
            result={
                "items": [
                    {
                        "key": "device-mr2",
                        "role": "onboard_mr",
                        "name": "MR2",
                        "physical_mac": "0011-2233-4455",
                        "selected": True,
                        "force_export": False,
                        "status": "正常",
                        "warnings": [],
                    }
                ],
                "source_counts": {"设备管理": 1},
                "stats": {"total": 1, "selected": 1, "abnormal": 0},
            },
        )
    )
    preview = client.get(
        f"/api/device-management/exports/omnipeek-preview/{task_id}"
    )
    assert preview.status_code == 200
    assert preview.json()["ready"] is True
    assert preview.json()["items"][0]["key"] == "device-mr2"
    assert "secret-password" not in preview.text


def test_securecrt_optional_template_is_uploaded_to_controlled_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    captured: dict[str, object] = {}

    def fake_start_export(site, export_type, extension, payload, action):
        captured.update(
            site=site,
            export_type=export_type,
            extension=extension,
            payload=payload,
            action=action,
        )
        return DeviceTaskReferenceDTO(
            task_id="device-export-securecrt-template",
            task_status="PENDING",
            action="securecrt_sessions",
        )

    monkeypatch.setattr(service, "_start_export", fake_start_export)
    response = client.post(
        "/api/device-management/exports/securecrt-with-template",
        data={"selection": json.dumps({"device_uuids": [str(mr.device_uuid)]})},
        files={"file": ("session.ini", b"S:\\Hostname=%HOST%", "text/plain")},
    )

    assert response.status_code == 202
    template = Path(str(captured["payload"]["template_ini"]))
    assert template.is_relative_to(service._artifact_root("demo"))
    assert template.read_bytes() == b"S:\\Hostname=%HOST%"
    service._remove_controlled_file(template, service._artifact_root("demo"))

    rejected = client.post(
        "/api/device-management/exports/securecrt-with-template",
        data={"selection": "{}"},
        files={"file": ("session.txt", b"unsafe", "text/plain")},
    )
    assert rejected.status_code == 422
    assert not list(service._artifact_root("demo").glob(".securecrt-template-*.ini"))


def test_all_qt_device_export_formats_complete_in_real_export_process(
    tmp_path: Path,
) -> None:
    client, service, _adapter, devices, _facts, mr, _sw = _fixture(
        tmp_path, app_root=Path(__file__).resolve().parents[1]
    )
    mr.device_type = "Cloud-AP"
    mr.mac_address = "74ad-cb9d-3320"
    devices.update(mr)

    def complete(path: str, payload: dict[str, object]) -> tuple[dict[str, object], bytes]:
        started = client.post(path, json=payload)
        assert started.status_code == 202, started.text
        task_id = started.json()["task_id"]
        deadline = monotonic() + 15
        task: dict[str, object] = {}
        while monotonic() < deadline:
            response = client.get(f"/api/device-management/exports/{task_id}")
            assert response.status_code == 200, response.text
            task = response.json()
            if task["task_status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            sleep(0.05)
        assert task["task_status"] == "COMPLETED", task
        assert task["available"] is True
        downloaded = client.get(
            f"/api/device-management/exports/{task_id}/download",
            params={"artifact_id": task["artifact_id"]},
        )
        assert downloaded.status_code == 200, downloaded.text
        return task, downloaded.content

    try:
        _csv_task, csv_without_secrets = complete(
            "/api/device-management/exports/csv",
            {"device_uuids": [str(mr.device_uuid)], "include_credentials": False},
        )
        assert b"secret-password" not in csv_without_secrets
        assert "MR2" in csv_without_secrets.decode("utf-8-sig")

        _secret_csv_task, csv_with_secrets = complete(
            "/api/device-management/exports/csv",
            {"device_uuids": [str(mr.device_uuid)], "include_credentials": True},
        )
        assert "secret-password" in csv_with_secrets.decode("utf-8-sig")

        _template_task, template = complete(
            "/api/device-management/exports/template", {}
        )
        assert "设备名称" in template.decode("utf-8-sig")

        _securecrt_task, securecrt = complete(
            "/api/device-management/exports/securecrt",
            {"device_uuids": [str(mr.device_uuid)]},
        )
        securecrt_path = tmp_path / "securecrt.zip"
        securecrt_path.write_bytes(securecrt)
        with zipfile.ZipFile(securecrt_path) as archive:
            assert "_netconsole_manifest.json" in archive.namelist()
            assert any(name.endswith(".ini") for name in archive.namelist())

        _omnipeek_task, omnipeek = complete(
            "/api/device-management/exports/omnipeek",
            {
                "device_uuids": [str(mr.device_uuid)],
                "line_name": "测试线路",
                "include_device_mr": True,
            },
        )
        omnipeek_text = omnipeek.decode("utf-8")
        assert '<NameTable Version="3.0">' in omnipeek_text
        assert "74:AD:CB:9D:33:20" in omnipeek_text
    finally:
        asyncio.run(service.stop_exports())


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

    secret_value = "must-not-be-echoed"
    accepted_secret = client.post(
        "/api/device-management/devices",
        json={"name": "Web-secret", "primary_address": "192.0.2.32", "ssh_password": secret_value},
    )
    assert accepted_secret.status_code == 201
    secret_uuid = accepted_secret.json()["device"]["device_uuid"]
    assert secret_value not in accepted_secret.text
    assert "password" not in accepted_secret.text.lower()
    assert devices.get_by_uuid(secret_uuid).ssh_password == secret_value

    preserved_secret = client.put(
        f"/api/device-management/devices/{secret_uuid}",
        json={"name": "Web-secret-updated", "primary_address": "192.0.2.33", "ssh_password": ""},
    )
    assert preserved_secret.status_code == 200
    assert secret_value not in preserved_secret.text
    assert "password" not in preserved_secret.text.lower()
    assert devices.get_by_uuid(secret_uuid).ssh_password == secret_value

    detail = client.get(f"/api/device-management/devices/{secret_uuid}")
    assert detail.status_code == 200
    assert detail.json()["device"]["ssh_secret_configured"] is True
    assert secret_value not in detail.text
    assert "password" not in detail.text.lower()

    replacement = "replacement-must-not-be-echoed"
    replaced_secret = client.put(
        f"/api/device-management/devices/{secret_uuid}",
        json={
            "name": "Web-secret-updated",
            "primary_address": "192.0.2.33",
            "ssh_password": replacement,
        },
    )
    assert replaced_secret.status_code == 200
    assert replacement not in replaced_secret.text
    assert devices.get_by_uuid(secret_uuid).ssh_password == replacement

    conflicting_clear = client.put(
        f"/api/device-management/devices/{secret_uuid}",
        json={
            "name": "Web-secret-updated",
            "primary_address": "192.0.2.33",
            "ssh_password": "new-value",
            "clear_secret_fields": ["ssh_password"],
        },
    )
    assert conflicting_clear.status_code == 422
    assert devices.get_by_uuid(secret_uuid).ssh_password == replacement

    forged_clear = client.put(
        f"/api/device-management/devices/{secret_uuid}",
        json={
            "name": "Web-secret-updated",
            "primary_address": "192.0.2.33",
            "clear_secret_fields": ["password"],
        },
    )
    assert forged_clear.status_code == 422
    assert devices.get_by_uuid(secret_uuid).ssh_password == replacement

    cleared_secret = client.put(
        f"/api/device-management/devices/{secret_uuid}",
        json={
            "name": "Web-secret-updated",
            "primary_address": "192.0.2.33",
            "clear_secret_fields": ["ssh_password"],
        },
    )
    assert cleared_secret.status_code == 200
    assert devices.get_by_uuid(secret_uuid).ssh_password is None
    assert devices.get_by_uuid(secret_uuid).password is None
    assert (
        client.get(f"/api/device-management/devices/{secret_uuid}").json()[
            "device"
        ]["ssh_secret_configured"]
        is False
    )

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
    assert body["duplicate_rows"] == []
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
    assert adapter.jobs[-1].params["duplicate_strategy"] == "reject"
    assert adapter.completions[-1] is not None
    adapter.completions[-1](SimpleNamespace(exit_code=0, cancelled=False, payload={"result": {"created": 1, "skipped": 0, "errors": []}}))
    assert not list(service._import_staging_root("demo").glob("*"))
    backups = list(service.paths.site_backups_dir("demo").glob("device-import-*.sqlite"))
    assert backups


def test_import_worker_without_web_strategy_preserves_qt_append_behavior(
    tmp_path: Path,
) -> None:
    _client, service, _adapter, devices, _facts, mr, _sw = _fixture(tmp_path)
    source = tmp_path / "qt-import.csv"
    _write_import_csv(source, name="Qt 重复设备", address=str(mr.primary_address))
    before = len(devices.list())

    result = run_device_csv_import(
        JobContext(
            "qt-device-import",
            DEVICE_IMPORT_TASK_TYPE,
            {
                "site_name": "demo",
                "path": str(source),
                "db_path": str(service.paths.site_db_path("demo")),
            },
            None,
            lambda: False,
            service.paths,
        )
    )

    assert result["created"] == 1
    assert result["skipped"] == 0
    assert len(devices.list()) == before + 1


def test_import_preview_reports_duplicate_rows_and_passes_selected_strategy(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    source = tmp_path / "duplicate.csv"
    _write_import_csv(source, name="重复设备", address=str(mr.primary_address))

    preview = client.post(
        "/api/device-management/imports/preview",
        files={"file": (source.name, source.read_bytes(), "text/csv")},
    )
    assert preview.status_code == 200
    assert preview.json()["duplicate_rows"] == [2]

    rejected_strategy = client.post(
        "/api/device-management/imports/confirm",
        json={
            "preview_token": preview.json()["preview_token"],
            "duplicate_strategy": "overwrite",
        },
    )
    assert rejected_strategy.status_code == 422

    confirmed = client.post(
        "/api/device-management/imports/confirm",
        json={
            "preview_token": preview.json()["preview_token"],
            "duplicate_strategy": "skip",
        },
    )
    assert confirmed.status_code == 202
    assert adapter.jobs[-1].params["duplicate_strategy"] == "skip"
    assert adapter.completions[-1] is not None
    adapter.completions[-1](
        SimpleNamespace(
            exit_code=0,
            cancelled=False,
            payload={"result": {"created": 0, "skipped": 1, "errors": []}},
        )
    )
    assert not list(service._import_staging_root("demo").glob("*"))
    audit_files = list(
        (service.paths.site_imports_dir("demo") / "device_import_audit").glob(
            "device-import-*.json"
        )
    )
    assert len(audit_files) == 1
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["status"] == "APPLIED"
    assert audit["skipped_count"] == 1


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
        desktop_action_service=service.desktop_action_service,
        site_name="demo",
        process_adapter=restarted_adapter,  # type: ignore[arg-type]
    )
    confirmed = restarted.confirm_import(
        DeviceImportConfirmRequestDTO(preview_token=preview.preview_token)
    )

    assert confirmed.action == "import_csv"
    assert restarted_adapter.jobs[-1].task_type == "device_csv_import"


def test_import_claim_publishes_complete_manifest_before_concurrent_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, service, adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    source = tmp_path / "claim-barrier.csv"
    _write_import_csv(source, name="并发认领", address="192.0.2.44")
    with source.open("rb") as handle:
        preview = service.preview_import(source.name, handle)
    staging_root = service._import_staging_root("demo")
    preview_manifest = service._preview_manifest_path(
        "demo", preview.preview_token
    )
    preview_payload = json.loads(preview_manifest.read_text(encoding="utf-8"))
    preview_payload["expires"] = datetime.now(UTC).timestamp() + 300
    service._write_json_atomic(preview_manifest, preview_payload, staging_root)
    staged = staging_root / preview_payload["staged_name"]
    old = (
        datetime.now(UTC).timestamp()
        - DEVICE_IMPORT_PREVIEW_TTL_SECONDS
        - 30
    )
    os.utime(staged, (old, old))

    publish_entered = Event()
    publish_release = Event()
    original_replace = os.replace

    def blocked_replace(source_path: object, target_path: object) -> None:
        if Path(target_path).name.startswith(".claimed-"):
            publish_entered.set()
            assert publish_release.wait(2)
        original_replace(source_path, target_path)

    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.os.replace",
        blocked_replace,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.confirm_import,
            DeviceImportConfirmRequestDTO(preview_token=preview.preview_token),
        )
        try:
            assert publish_entered.wait(2)
            lock = next(staging_root.glob(".claim-*.lock"))
            lock_payload = json.loads(lock.read_text(encoding="utf-8"))
            assert lock_payload["claimed_at"] > 0
            assert lock_payload["task_id"].startswith("device-import-")
            assert lock_payload["operation_id"].startswith("device-import-")

            restarted_tasks = TaskApplicationService(
                paths=service.paths, site_name="demo"
            )
            restarted = DeviceManagementWebService(
                service.paths,
                restarted_tasks,
                desktop_action_service=service.desktop_action_service,
                site_name="demo",
            )
            restarted._cleanup_expired_import_previews("demo")
            assert staged.exists()
            assert lock.exists()
        finally:
            publish_release.set()
        confirmed = future.result(timeout=2)

    claimed = next(staging_root.glob(".claimed-*.preview.json"))
    claimed_payload = json.loads(claimed.read_text(encoding="utf-8"))
    assert claimed_payload["task_id"] == confirmed.task_id
    assert claimed_payload["claimed_at"] == lock_payload["claimed_at"]
    assert not list(staging_root.glob(".claim-*.lock"))
    assert not list(staging_root.glob(".claim-ready-*.preview.json"))
    assert not list(staging_root.glob(".claim-source-*.preview.json"))
    adapter.completions[-1](
        SimpleNamespace(
            exit_code=0,
            cancelled=False,
            payload={"result": {"created": 1, "skipped": 0, "errors": []}},
        )
    )


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
        service.paths,
        restarted_tasks,
        desktop_action_service=service.desktop_action_service,
        site_name="demo",
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
        service.paths,
        restarted_tasks,
        desktop_action_service=service.desktop_action_service,
        site_name="demo",
    )
    restarted.current_site_id()

    assert not claimed.exists()
    assert not staged.exists()
    audit = service._import_audit_path("demo", claimed_payload["operation_id"])
    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_payload["status"] == "APPLIED"
    assert audit_payload["task_id"] == confirmed.task_id


@pytest.mark.parametrize(
    ("suffix", "overrides"),
    (
        ("a", {"owner": "foreign-owner"}),
        ("b", {"source": "agent"}),
        ("c", {"site_name": "foreign-site"}),
        ("d", {"task_type": "config_collect"}),
    ),
    ids=("owner", "source", "site", "task-type"),
)
def test_claim_cleanup_requires_exact_owned_import_task(
    tmp_path: Path, suffix: str, overrides: dict[str, object]
) -> None:
    _client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)
    root = service._import_staging_root("demo")
    task_id = f"device-import-{suffix * 32}"
    operation_id = f"device-import-{suffix * 32}"
    staged = root / f"device-preview-{suffix * 32}.csv"
    claimed = root / f".claimed-{suffix * 32}.preview.json"
    staged.write_text("placeholder", encoding="utf-8")
    service._write_json_atomic(
        claimed,
        {
            "site": "demo",
            "staged_name": staged.name,
            "claimed_at": datetime.now(UTC).timestamp()
            - DEVICE_IMPORT_CLAIM_GRACE_SECONDS
            - 1,
            "task_id": task_id,
            "operation_id": operation_id,
        },
        root,
    )
    now = datetime.now(UTC).isoformat()
    values: dict[str, object] = {
        "task_type": DEVICE_IMPORT_TASK_TYPE,
        "task_name": "异域导入任务",
        "status": TaskState.RUNNING,
        "created_time": now,
        "updated_time": now,
        "owner": WEB_TASK_OWNER,
        "source": "local",
        "site_name": "demo",
    }
    service.task_service.repository("demo").save(
        TaskSnapshot(task_id=task_id, **{**values, **overrides})
    )

    service._cleanup_expired_import_previews("demo")

    assert not claimed.exists()
    assert not staged.exists()
    audit = json.loads(
        service._import_audit_path("demo", operation_id).read_text(
            encoding="utf-8"
        )
    )
    assert audit["status"] == "FAILED"
    assert audit["task_id"] == task_id


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
    artifact_id = f"device-{'a' * 32}"
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
    disposition = unquote(downloaded.headers["content-disposition"])
    assert "设备清单.csv" in disposition
    assert artifact_id not in disposition
    assert int(downloaded.headers["content-length"]) == artifact.stat().st_size
    assert downloaded.headers["content-type"] == "text/csv; charset=utf-8"

    save_task("device-export-duplicate-name")
    duplicate = client.get(
        "/api/device-management/exports/device-export-duplicate-name/download",
        params={"artifact_id": artifact_id},
    )
    assert duplicate.status_code == 200
    assert unquote(duplicate.headers["content-disposition"]) == disposition

    save_task(
        "device-export-sanitized-name",
        result={
            "artifact_id": artifact_id,
            "artifact_name": artifact.name,
            "display_name": "中文:设备?清单.csv",
            "available": True,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
    )
    sanitized = client.get(
        "/api/device-management/exports/device-export-sanitized-name/download",
        params={"artifact_id": artifact_id},
    )
    assert sanitized.status_code == 200
    assert "中文_设备_清单.csv" in unquote(sanitized.headers["content-disposition"])

    save_task(
        "device-export-control-name",
        result={
            "artifact_id": artifact_id,
            "artifact_name": artifact.name,
            "display_name": "设备\u202eexe\x01清单.csv",
            "available": True,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
    )
    control_name = client.get(
        "/api/device-management/exports/device-export-control-name/download",
        params={"artifact_id": artifact_id},
    )
    assert control_name.status_code == 200
    assert "设备_exe_清单.csv" in unquote(control_name.headers["content-disposition"])

    save_task(
        "device-export-deceptive-extension",
        result={
            "artifact_id": artifact_id,
            "artifact_name": artifact.name,
            "display_name": "设备清单.exe",
            "available": True,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
    )
    assert client.get(
        "/api/device-management/exports/device-export-deceptive-extension/download",
        params={"artifact_id": artifact_id},
    ).status_code == 422

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


def test_device_export_production_result_separates_physical_and_display_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service, _adapter, _devices, _facts, _mr, _sw = _fixture(tmp_path)

    class FakeProcess:
        stdout = None
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout=None):
            _ = timeout
            return self.returncode

    class NoopThread:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def start(self) -> None:
            return None

    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.subprocess.Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.threading",
        SimpleNamespace(Thread=NoopThread, Event=Event),
    )
    reference = service.start_csv_export(DeviceExportRequestDTO())
    spec = service._export_artifacts[reference.task_id]
    target = Path(str(spec["target"]))
    target.write_text("name,primary_address\n设备,192.0.2.10\n", encoding="utf-8")
    result = service._finalize_export_artifact(spec, {"path": str(target), "row_count": 1})
    service.task_service.record_external_event(
        reference.task_id,
        "finished",
        {"result": result},
        site_name="demo",
    )

    downloaded = client.get(
        f"/api/device-management/exports/{reference.task_id}/download",
        params={"artifact_id": result["artifact_id"]},
    )

    assert str(result["artifact_name"]) == f"{result['artifact_id']}.csv"
    assert str(result["display_name"]).startswith("设备清单_")
    assert str(result["display_name"]).endswith(".csv")
    assert result["artifact_id"] not in str(result["display_name"])
    assert downloaded.status_code == 200
    assert str(result["display_name"]) in unquote(downloaded.headers["content-disposition"])
    assert int(downloaded.headers["content-length"]) == result["size_bytes"]
    assert downloaded.headers["content-type"] == "text/csv; charset=utf-8"


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


def test_securecrt_spawn_and_sensitive_cleanup_failure_still_marks_task_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    def fail_popen(*_args: object, **_kwargs: object) -> None:
        raise OSError("worker unavailable")

    def fail_cleanup(*_args: object, **_kwargs: object) -> None:
        raise OSError("template locked")

    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.subprocess.Popen",
        fail_popen,
    )
    monkeypatch.setattr(service, "_cleanup_export_files", fail_cleanup)
    reference = service.start_securecrt_export(
        DeviceSecureCrtExportRequestDTO(device_uuids=[str(mr.device_uuid)]),
        template_name="session.ini",
        template_stream=BytesIO(b"S:\\Hostname=%HOST%"),
    )

    assert reference.task_status == TaskState.FAILED.value
    assert reference.task_id not in service._export_artifacts
    snapshot = service.task_service.repository("demo").get(reference.task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.FAILED


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


def test_diagnostic_task_creates_downloadable_controlled_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)

    class FakeDiagnosticDownloadService:
        def __init__(self, site: str, paths: PathResolver) -> None:
            self.site = site
            self.paths = paths

        def download(self, _device: Device) -> SimpleNamespace:
            path = self.paths.config_center_raw_logs_dir(
                self.site, "20260717", "diagnostic"
            ) / "MR-02_diag_20260717_120000.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("display diagnostic-information\nOK\n", encoding="utf-8")
            return SimpleNamespace(
                device_id=mr.id,
                device_name=mr.name,
                timestamp="20260717_120000",
                file_path=path.resolve().relative_to(
                    self.paths.site_dir(self.site).resolve()
                ).as_posix(),
                status="success",
                error_message=None,
                elapsed_ms=2,
                success=True,
            )

    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.DiagnosticDownloadService",
        FakeDiagnosticDownloadService,
    )
    started = client.post(
        "/api/device-management/diagnostic-download",
        json={"device_uuids": [str(mr.device_uuid)]},
    )
    assert started.status_code == 202
    job = adapter.jobs[-1]
    result = run_device_diagnostic_download(
        JobContext(
            job.job_id,
            job.task_type,
            job.params,
            None,
            lambda: False,
            service.paths,
        )
    )
    assert "file_path" not in result["results"][0]
    assert result["available"] is True
    artifact = service._artifact_root("demo") / str(result["artifact_name"])
    assert artifact.is_file()
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        assert "diagnostic_summary.json" in names
        assert "_netconsole_manifest.json" in names
        assert any(name.endswith("MR-02_diag_20260717_120000.txt") for name in names)
        assert json.loads(archive.read("diagnostic_summary.json"))["success"] == 1

    service.task_service.record_external_event(
        job.job_id,
        "finished",
        {"result": result},
        site_name="demo",
    )
    task = client.get(f"/api/device-management/tasks/{job.job_id}")
    assert task.status_code == 200
    assert task.json()["available"] is True
    downloaded = client.get(
        f"/api/device-management/diagnostics/{job.job_id}/download",
        params={"artifact_id": result["artifact_id"]},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == artifact.read_bytes()
    assert client.get(
        f"/api/device-management/exports/{job.job_id}/download",
        params={"artifact_id": result["artifact_id"]},
    ).status_code != 200


def test_restart_cleanup_preserves_active_diagnostic_temp_and_removes_terminal_orphan(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    started = client.post(
        "/api/device-management/diagnostic-download",
        json={"device_uuids": [str(mr.device_uuid)]},
    )
    assert started.status_code == 202
    job = adapter.jobs[-1]
    artifact_id = str(job.params["artifact_id"])
    root = service._artifact_root("demo")
    active_temp = root / f".{artifact_id}.{job.job_id}.tmp"
    orphan_temp = root / (
        ".device-diagnostic-" + "a" * 32 + ".device-diagnostic-orphan.tmp"
    )
    active_temp.write_bytes(b"active")
    orphan_temp.write_bytes(b"orphan")

    service._reconciled_import_sites.clear()
    service.current_site_id()

    assert active_temp.exists()
    assert not orphan_temp.exists()
    service.task_service.record_external_event(
        job.job_id,
        "cancelled",
        {"message": "restart cleanup test", "cancelled": True},
        site_name="demo",
    )
    service._reconciled_import_sites.clear()
    service.current_site_id()
    assert not active_temp.exists()


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
    client, service, adapter, _devices, _facts, mr, sw = _fixture(tmp_path)
    target_uuid = str(sw.device_uuid)
    refreshed = client.post("/api/device-management/devices/batch-refresh-details", json={"device_uuids": [target_uuid]})
    assert refreshed.status_code == 202, refreshed.text
    assert refreshed.json()["action"] == "batch_refresh_details"
    assert adapter.jobs[-1].task_type == "device_detail_collect"
    assert adapter.jobs[-1].params["owner"] == WEB_TASK_OWNER
    assert adapter.jobs[-1].params["task_source"] == "local"
    assert adapter.jobs[-1].params["operation_id"] == "device.inventory.collect"
    assert adapter.jobs[-1].params["profile_id"].startswith("h3c.comware.switch")
    assert adapter.jobs[-1].params["idempotency_key"]
    collect_task_id = refreshed.json()["tasks"][0]["task_id"]
    duplicate_refresh = client.post(
        "/api/device-management/devices/batch-refresh-details",
        json={"device_uuids": [target_uuid]},
    )
    assert duplicate_refresh.status_code == 202
    assert duplicate_refresh.json()["tasks"][0]["task_id"] == collect_task_id
    blocked_optical = client.post(
        f"/api/device-management/devices/{target_uuid}/refresh-optical"
    )
    assert blocked_optical.status_code == 422
    assert "未注册独立光模块刷新" in blocked_optical.text
    service.task_service.record_external_event(
        collect_task_id,
        "cancelled",
        {"message": "测试结束详情采集", "cancelled": True},
        site_name="demo",
    )
    diagnostic = client.post(
        "/api/device-management/diagnostic-download",
        json={"device_uuids": [str(mr.device_uuid)]},
    )
    assert diagnostic.status_code == 202
    detail = client.get(
        f"/api/device-management/devices/{target_uuid}"
    ).json()
    assert {collect_task_id} <= {
        task["task_id"] for task in detail["recent_tasks"]
    }

    terminal = client.post(f"/api/device-management/devices/{mr.device_uuid}/external-terminal", json={"terminal_type": "securecrt"})
    assert terminal.status_code == 200
    assert terminal.json() == {
        "native_action": "launchTerminal",
        "device_uuid": str(mr.device_uuid),
        "terminal_type": "securecrt",
        "success": True,
        "code": "launched",
        "message": "外部终端已启动",
    }
    desktop_adapter = service.desktop_action_service.adapter
    assert isinstance(desktop_adapter, _FakeDesktopAdapter)
    assert [call.executable.name for call in desktop_adapter.terminal_calls] == [
        "SecureCRT.exe"
    ]
    assert "secret-password" not in terminal.text

    for forbidden_field in ("executable", "command", "path"):
        forged = client.post(
            f"/api/device-management/devices/{mr.device_uuid}/external-terminal",
            json={"terminal_type": "securecrt", forbidden_field: "cmd.exe"},
        )
        assert forged.status_code == 422
    assert len(desktop_adapter.terminal_calls) == 1

    batch_terminal = client.post(
        "/api/device-management/external-terminal/launch",
        json={
            "device_uuids": [str(mr.device_uuid), str(sw.device_uuid)],
            "terminal_type": "securecrt",
        },
    )
    assert batch_terminal.status_code == 200
    assert batch_terminal.json()["success"] == 2
    assert batch_terminal.json()["failed"] == 0
    assert len(desktop_adapter.terminal_calls) == 3


def test_batch_refresh_supports_h3c_mobile_router_profile(tmp_path: Path) -> None:
    client, _service, adapter, devices, _facts, _mr, _sw = _fixture(tmp_path)
    mr = devices.create(
        Device(
            name="列车01-MR-CT",
            primary_address="192.0.2.249",
            device_vendor="H3C",
            device_type="MR",
        )
    )

    response = client.post(
        "/api/device-management/devices/batch-refresh-details",
        json={"device_uuids": [str(mr.device_uuid)]},
    )

    assert response.status_code == 202, response.text
    params = adapter.jobs[-1].params
    assert params["operation_id"] == "device.inventory.collect"
    assert params["profile_id"] == "h3c.comware.mobile_router.generic.device-inventory.v1"
    assert params["platform_role"] == "mobile_router"
    assert params["platform"] == "comware"
    assert "commands" not in params


def test_vehicle_mr_legacy_cloud_ap_migration_is_strict_and_backed_up(
    tmp_path: Path,
) -> None:
    client, service, _adapter, devices, _facts, _mr, _sw = _fixture(tmp_path)
    database = Database(service.paths.site_db_path("demo"))
    groups = DeviceGroupRepository(database, "demo")
    onboard = groups.find_by_name("车载-MR")
    assert onboard is not None
    other = groups.create("轨旁-AP")
    eligible_ct = devices.create(
        Device(
            name="列车01-MR-CT",
            primary_address="192.0.2.31",
            group_id=onboard.id,
            device_type="Cloud-AP",
        )
    )
    eligible_cw = devices.create(
        Device(
            name="列车01-MR-CW",
            primary_address="192.0.2.32",
            group_id=onboard.id,
            device_type="Cloud-AP",
        )
    )
    bad_name = devices.create(
        Device(
            name="列车01-MR-TC",
            primary_address="192.0.2.33",
            group_id=onboard.id,
            device_type="Cloud-AP",
        )
    )
    real_ap = devices.create(
        Device(
            name="AP-01",
            primary_address="192.0.2.34",
            group_id=other.id,
            device_type="Cloud-AP",
        )
    )
    already_mr = devices.create(
        Device(
            name="列车02-MR-CT",
            primary_address="192.0.2.35",
            group_id=onboard.id,
            device_type="MR",
        )
    )

    response = client.get("/api/device-management/devices")

    assert response.status_code == 200, response.text
    assert devices.get(int(eligible_ct.id or 0)).device_type == "MR"
    assert devices.get(int(eligible_cw.id or 0)).device_type == "MR"
    assert devices.get(int(bad_name.id or 0)).device_type == "Cloud-AP"
    assert devices.get(int(real_ap.id or 0)).device_type == "Cloud-AP"
    assert devices.get(int(already_mr.id or 0)).device_type == "MR"
    backups = list(
        (
            service.paths.site_backups_dir("demo") / "device-type-migrations"
        ).glob("vehicle-mr-device-type-*.sqlite")
    )
    assert len(backups) == 1

    assert client.get("/api/device-management/devices").status_code == 200
    backups_after_second_scan = list(
        (
            service.paths.site_backups_dir("demo") / "device-type-migrations"
        ).glob("vehicle-mr-device-type-*.sqlite")
    )
    assert backups_after_second_scan == backups


def test_large_external_terminal_batch_requires_scoped_single_use_confirmation(
    tmp_path: Path,
) -> None:
    client, service, _adapter, devices, _facts, mr, _sw = _fixture(tmp_path)
    device_uuids = [str(mr.device_uuid)]
    for index in range(20):
        created = devices.create(
            Device(
                name=f"批量终端-{index + 1}",
                primary_address=f"198.51.100.{index + 1}",
                ssh_enabled=True,
                ssh_username="admin",
                ssh_password="secret",
            )
        )
        device_uuids.append(str(created.device_uuid))

    rejected = client.post(
        "/api/device-management/external-terminal/launch",
        json={"device_uuids": device_uuids, "terminal_type": "securecrt"},
    )
    assert rejected.status_code == 422
    assert "确认 token" in rejected.text

    confirmation = client.post(
        "/api/device-management/external-terminal/confirmation",
        json={"device_uuids": device_uuids, "terminal_type": "securecrt"},
    )
    assert confirmation.status_code == 200
    token = confirmation.json()["confirmation_token"]
    launched = client.post(
        "/api/device-management/external-terminal/launch",
        json={
            "device_uuids": device_uuids,
            "terminal_type": "securecrt",
            "confirmation_token": token,
        },
    )
    assert launched.status_code == 200
    assert launched.json()["success"] == 21
    desktop_adapter = service.desktop_action_service.adapter
    assert isinstance(desktop_adapter, _FakeDesktopAdapter)
    assert len(desktop_adapter.terminal_calls) == 21

    replayed = client.post(
        "/api/device-management/external-terminal/launch",
        json={
            "device_uuids": device_uuids,
            "terminal_type": "securecrt",
            "confirmation_token": token,
        },
    )
    assert replayed.status_code == 422


def test_external_terminal_settings_are_desktop_only_and_reject_arbitrary_executables(
    tmp_path: Path,
) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    settings = client.get("/api/device-management/external-terminal/settings")
    assert settings.status_code == 200
    assert settings.json()["securecrt_path"].endswith("SecureCRT.exe")

    xshell = tmp_path / "Xshell.exe"
    putty = tmp_path / "PuTTY64.exe"
    xshell.write_bytes(b"fake executable")
    putty.write_bytes(b"fake executable")
    updated = client.put(
        "/api/device-management/external-terminal/settings",
        json={
            **settings.json(),
            "terminal_type": "xshell",
            "xshell_path": str(xshell),
            "putty_path": str(putty),
        },
    )
    assert updated.status_code == 200
    assert updated.json()["terminal_type"] == "xshell"
    assert updated.json()["xshell_path"] == str(xshell.resolve())

    desktop_adapter = service.desktop_action_service.adapter
    assert isinstance(desktop_adapter, _FakeDesktopAdapter)
    for terminal_type, expected_name in (
        ("xshell", "Xshell.exe"),
        ("putty", "PuTTY64.exe"),
    ):
        launched = client.post(
            f"/api/device-management/devices/{mr.device_uuid}/external-terminal",
            json={"terminal_type": terminal_type},
        )
        assert launched.status_code == 200
        assert launched.json()["success"] is True
        assert desktop_adapter.terminal_calls[-1].executable.name == expected_name
        assert "secret-password" not in launched.text

    command_interpreter = tmp_path / "cmd.exe"
    command_interpreter.write_bytes(b"not allowed")
    rejected = client.put(
        "/api/device-management/external-terminal/settings",
        json={**updated.json(), "securecrt_path": str(command_interpreter)},
    )
    assert rejected.status_code == 422
    assert "请选择 SecureCRT.exe" in rejected.text

    service.desktop_action_service.runtime_mode = RuntimeMode.SERVER
    assert (
        client.get("/api/device-management/external-terminal/settings").status_code
        == 422
    )


def test_securecrt_xshell_and_putty_use_local_adapter_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    executables = {
        "securecrt": tmp_path / "SecureCRT.exe",
        "xshell": tmp_path / "Xshell.exe",
        "putty": tmp_path / "putty.exe",
    }
    for executable in executables.values():
        executable.write_bytes(b"fake executable")
    configured = client.put(
        "/api/device-management/external-terminal/settings",
        json={
            "terminal_type": "securecrt",
            "securecrt_path": str(executables["securecrt"]),
            "xshell_path": str(executables["xshell"]),
            "putty_path": str(executables["putty"]),
            "pass_password": False,
        },
    )
    assert configured.status_code == 200
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        pass

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(
        "netconsole.infrastructure.desktop.local_adapter.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "netconsole.infrastructure.desktop.local_adapter.shutdown_manager.register_process",
        lambda *_args, **_kwargs: None,
    )
    service.desktop_action_service.adapter = LocalDesktopAdapter()

    for terminal_type in ("securecrt", "xshell", "putty"):
        response = client.post(
            f"/api/device-management/devices/{mr.device_uuid}/external-terminal",
            json={"terminal_type": terminal_type},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True

    assert [Path(args[0]).name for args, _kwargs in calls] == [
        "SecureCRT.exe",
        "Xshell.exe",
        "putty.exe",
    ]
    assert all(kwargs["shell"] is False for _args, kwargs in calls)
    assert all(Path(str(kwargs["cwd"])).is_dir() for _args, kwargs in calls)
    assert "/SSH2" in calls[0][0]
    assert "-url" in calls[1][0]
    assert "-ssh" in calls[2][0]
    assert "secret-password" not in json.dumps(calls, ensure_ascii=False, default=str)


def test_generic_device_task_query_and_cancel_enforce_owner_source_site_and_type(
    tmp_path: Path,
) -> None:
    client, service, adapter, _devices, _facts, _mr, sw = _fixture(tmp_path)
    started = client.post(
        "/api/device-management/devices/batch-refresh-details",
        json={"device_uuids": [str(sw.device_uuid)]},
    )
    assert started.status_code == 202, started.text
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


def test_device_detail_collect_handler_fails_closed_before_formal_collector(
    tmp_path: Path, monkeypatch
) -> None:
    client, service, adapter, _devices, _facts, _mr, sw = _fixture(
        tmp_path, app_root=Path(__file__).parents[1]
    )
    submitted = client.post(
        "/api/device-management/devices/batch-refresh-details",
        json={"device_uuids": [str(sw.device_uuid)]},
    )
    assert submitted.status_code == 202
    params = dict(adapter.jobs[-1].params)
    collected: list[str] = []

    def fake_collect(device: Device, site: str, *, repository, paths):
        collected.append(str(device.device_uuid))
        assert site == "demo"
        assert paths is service.paths
        assert repository is not None
        profile = resolve_device_inventory_profile(device, paths=paths)
        assert profile.profile_id == params["profile_id"]
        assert profile.profile_version == params["profile_version"]
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
            params,
            None,
            lambda: False,
            service.paths,
        )
    )

    assert collected == [str(sw.device_uuid)]
    assert result["total"] == 1
    assert result["success"] == 1
    assert result["failed"] == 0

    with pytest.raises(DeviceInventoryRefreshFailed) as mismatch:
        run_device_detail_collect(
            JobContext(
                "device-detail-profile-mismatch",
                "device_detail_collect",
                {**params, "profile_id": "h3c.comware.switch.unexpected.v99"},
                None,
                lambda: False,
                service.paths,
            )
        )
    assert mismatch.value.summary["success"] == 0
    assert mismatch.value.summary["failed"] == 1
    assert "Profile" in str(mismatch.value)

    def failed_collect(device: Device, site: str, *, repository, paths):
        return SimpleNamespace(
            success=False,
            collect_run_uuid=f"run-{device.name}",
            facts_updated=False,
            interfaces_updated=0,
            optical_modules_updated=0,
            lldp_neighbors_updated=0,
            error_message=r"连接失败 C:\private\secret.log password=hidden",
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_collect_service.collect_h3c_device_details",
        failed_collect,
    )
    job_result = JobRunner().run(adapter.jobs[-1])
    assert job_result.ok is False
    assert job_result.to_event()["type"] == "error"
    assert "failed=1" in job_result.error
    assert "C:\\private" not in job_result.error
    assert "password=hidden" not in job_result.error


def test_device_optical_refresh_handler_uses_formal_service(
    tmp_path: Path, monkeypatch
) -> None:
    _client, service, _adapter, _devices, _facts, mr, _sw = _fixture(tmp_path)
    calls: list[str] = []

    def fake_refresh(device: Device, site: str, *, repository, paths):
        calls.append(str(device.device_uuid))
        assert site == "demo"
        assert repository is not None
        assert paths is service.paths
        return SimpleNamespace(
            success=True,
            device_uuid=str(device.device_uuid),
            collect_run_uuid="optical-run",
            interfaces_updated=1,
            optical_modules_updated=2,
            error_message="",
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_optical_refresh_service.refresh_h3c_device_optical",
        fake_refresh,
    )
    result = run_device_optical_refresh(
        JobContext(
            "device-optical-handler",
            DEVICE_OPTICAL_REFRESH_TASK_TYPE,
            {"site_name": "demo", "device_uuid": str(mr.device_uuid)},
            None,
            lambda: False,
            service.paths,
        )
    )

    assert calls == [str(mr.device_uuid)]
    assert result["success"] is True
    assert result["optical_modules_updated"] == 2
