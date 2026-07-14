from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.config_collection_router import router
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.config_collection_web_service import ConfigCollectionApplicationService
from netconsole.services.config_lifecycle_service import ConfigLifecycleService
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.job_registry import dispatch_job, registered_task_types
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeProcessAdapter:
    def __init__(self, task_service: TaskApplicationService) -> None:
        self.task_service = task_service
        self.jobs: list[JobSpec] = []

    def start_job(self, job: JobSpec, **_kwargs) -> str:
        self.jobs.append(job)
        launch = self.task_service.prepare(job)
        self.task_service.mark_running(launch.job.job_id)
        return launch.job.job_id

    def shutdown(self) -> None:
        return None


def _fixture(tmp_path: Path):
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = Device(
        name="SW-01",
        device_uuid=Device.new_uuid(),
        device_vendor="H3C",
        device_type="SW",
        ip_address="192.0.2.10",
        ssh_username="operator",
        ssh_password="secret-password",
    )
    device = DeviceRepository(database).create(device)
    lifecycle = ConfigLifecycleService("demo", database, paths)
    running = lifecycle._write_snapshot(device, "running", "20260715_101500", "#\nsysname SW-01\nreturn")
    saved = lifecycle._write_snapshot(device, "saved", "20260715_101500", "#\nsysname SW-01\nvlan 10\nreturn")
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    process_adapter = _FakeProcessAdapter(task_service)
    web_service = ConfigCollectionApplicationService(paths, task_service, process_adapter)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=task_service,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    app.include_router(router, prefix="/api")
    app.state.config_collection_service = web_service
    return app, paths, device, running, saved, process_adapter


def test_config_collection_reads_redacted_devices_and_controlled_snapshot_artifacts(tmp_path: Path) -> None:
    app, _paths, device, running, _saved, _adapter = _fixture(tmp_path)

    with TestClient(app) as client:
        devices = client.get("/api/config-collection/devices")
        snapshots = client.get(f"/api/config-collection/devices/{device.id}/snapshots")
        artifact = client.get(f"/api/config-collection/artifacts/snapshot-{running.id}")
        invalid = client.get("/api/config-collection/artifacts/../secrets.txt")

    assert devices.status_code == 200
    assert devices.json()["items"][0]["name"] == "SW-01"
    assert "secret-password" not in devices.text
    assert "192.0.2.10" not in devices.text
    assert snapshots.status_code == 200
    assert snapshots.json()[0]["artifact_id"].startswith("snapshot-")
    assert "file_path" not in snapshots.text
    assert artifact.status_code == 200
    assert "sysname SW-01" in artifact.text
    assert invalid.status_code in {404, 405}


def test_config_collection_submits_only_readonly_job_and_persists_task_reference(tmp_path: Path) -> None:
    app, _paths, device, _running, _saved, adapter = _fixture(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/config-collection/actions",
            json={"action": "fetch", "device_ids": [device.id]},
        )
        tasks = client.get("/api/config-collection/tasks")
        save = client.post(
            "/api/config-collection/actions",
            json={"action": "save", "device_ids": [device.id]},
        )

    assert response.status_code == 202
    assert response.json()[0]["type"] == "config_web_snapshot_fetch"
    assert adapter.jobs[0].params["device_uuid"] == device.device_uuid
    assert "password" not in json.dumps(response.json())
    assert tasks.status_code == 200
    assert tasks.json()[0]["status"] == TaskState.RUNNING.value
    assert save.status_code == 422
    assert "config_web_snapshot_save" not in registered_task_types()


def test_config_task_status_redacts_paths_and_secrets_inside_messages_and_nested_results(tmp_path: Path) -> None:
    app, _paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    service.task_service.repository("demo").save(
        TaskSnapshot(
            task_id="config-web-redaction",
            task_type="config_snapshot_load_content",
            task_name="配置采集",
            status=TaskState.FAILED,
            created_time="2026-07-15T10:00:00Z",
            updated_time="2026-07-15T10:00:01Z",
            message=r"读取 C:\Users\operator\secret.txt 失败，token=abc123",
            error_message=r"credential: top-secret \\server\share\result.txt",
            result={"note": r"file=C:\data\raw.log token:xyz789", "auth": "Authorization: Bearer abc.def", "nested": [{"text": "password=hidden"}]},
            source="web",
            site_name="demo",
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/config-collection/tasks/config-web-redaction")

    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert response.status_code == 200
    assert "C:\\Users\\operator" not in serialized
    assert "\\\\server\\share" not in serialized
    assert "abc123" not in serialized
    assert "top-secret" not in serialized
    assert "xyz789" not in serialized
    assert "abc.def" not in serialized
    assert "<redacted-path>" in serialized
    assert "<redacted>" in serialized


def test_config_web_compare_adapter_reuses_lifecycle_service_and_hides_absolute_artifact_path(tmp_path: Path) -> None:
    app, paths, _device, running, saved, _adapter = _fixture(tmp_path)
    result = dispatch_job(
        JobSpec(
            job_id="config-web-test-diff",
            task_type="config_compare_snapshot_pair",
            params={
                "site_name": "demo",
                "db_path": str(paths.site_db_path("demo")),
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "left_snapshot_id": running.id,
                "right_snapshot_id": saved.id,
            },
        )
    )

    assert result["kind"] == "snapshot_pair"
    assert result["raw_diff"]
    assert "diff_file" in result
    assert str(paths.data_root).replace("\\", "\\\\") in json.dumps(result)
    task = TaskSnapshot(
        task_id="config-web-test-diff",
        task_type="config_compare_snapshot_pair",
        task_name="比较配置快照",
        status=TaskState.COMPLETED,
        created_time="2026-07-15T10:00:00Z",
        updated_time="2026-07-15T10:00:01Z",
        result=result,
        source="web",
        site_name="demo",
    )
    app.state.config_collection_service.task_service.repository("demo").save(task)
    with TestClient(app) as client:
        status = client.get("/api/config-collection/tasks/config-web-test-diff")
        artifact = client.get("/api/config-collection/artifacts/diff-config-web-test-diff")

    assert status.status_code == 200
    assert status.json()["result"]["artifact_id"] == "diff-config-web-test-diff"
    assert "diff_file" not in status.text
    assert str(paths.data_root) not in status.text
    assert artifact.status_code == 200
    assert "vlan 10" in artifact.text
