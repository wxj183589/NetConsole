from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier, Event
from urllib.parse import unquote
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from netconsole.backend.api.config_collection_router import router
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.config_collection_web_service import CONFIG_WEB_OWNER, ConfigCollectionApplicationService
from netconsole.services import config_collection_job_handlers
from netconsole.services.config_lifecycle_service import ConfigLifecycleService
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.job_events import cancelled_event, error_event, finished_event, progress_event
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.job_registry import dispatch_job, registered_task_types
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.worker_protocol import encode_event


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeProcessAdapter:
    def __init__(self, task_service: TaskApplicationService) -> None:
        self.task_service = task_service
        self.jobs: list[JobSpec] = []
        self.block_start = False
        self.start_entered = Event()
        self.second_start_entered = Event()
        self.release_start = Event()

    def start_job(self, job: JobSpec, **_kwargs) -> str:
        self.jobs.append(job)
        if len(self.jobs) > 1:
            self.second_start_entered.set()
        if self.block_start:
            self.start_entered.set()
            assert self.release_start.wait(2)
        launch = self.task_service.prepare(job)
        self.task_service.mark_running(launch.job.job_id)
        return launch.job.job_id

    def shutdown(self) -> None:
        return None

    def is_running(self, task_id: str) -> bool:
        return self.task_service.is_running(task_id)

    def cancel_job(self, task_id: str) -> bool:
        if not self.is_running(task_id):
            return False
        self.task_service.request_cancel(task_id)
        return True


class _ExecutingFakeProcessAdapter(_FakeProcessAdapter):
    def __init__(self, task_service: TaskApplicationService) -> None:
        super().__init__(task_service)
        self.cancel_next = False

    def start_job(self, job: JobSpec, **kwargs) -> str:
        self.jobs.append(job)
        launch = self.task_service.prepare(job)
        self.task_service.mark_running(job.job_id)
        def progress(stage, current, total, message):
            self._event(job.job_id, progress_event(job.job_id, stage, current, total, message))
        try:
            result = dispatch_job(job, progress, lambda: self.cancel_next)
            self._event(job.job_id, finished_event(job.job_id, result))
            exit_code = 0
        except BackgroundTaskCancelled as exc:
            self._event(job.job_id, cancelled_event(job.job_id, str(exc)))
            exit_code = 2
        except Exception as exc:
            self._event(job.job_id, error_event(job.job_id, str(exc)))
            exit_code = 1
        self.task_service.complete(launch.job.job_id, exit_code)
        callback = kwargs.get("on_complete")
        if callable(callback):
            callback(
                LocalProcessCompletion(
                    job_id=job.job_id,
                    task_type=job.task_type,
                    exit_code=exit_code,
                    payload=None,
                    cancelled=exit_code == 2,
                    forced=False,
                )
            )
        self.cancel_next = False
        return launch.job.job_id

    def _event(self, job_id: str, event: dict[str, object]) -> None:
        self.task_service.feed_stdout(job_id, encode_event(event).encode("utf-8"))


HANDOFF_FEATURES = (
    "web.config_collection_delete",
    "web.config_collection_save_force",
    "web.config_collection_export",
    "web.config_collection_open_directory",
)


def _enable_handoff_features(app) -> None:
    for feature_id in HANDOFF_FEATURES:
        app.state.feature_gate.features[feature_id].update(
            visible=True,
            enabled=True,
            client_package=True,
        )


def _install_fake_connector(monkeypatch, *, fail: bool = False, after_command=None) -> list[str]:
    commands: list[str] = []

    def run_with_retry(_device, operation):
        return operation(object(), SimpleNamespace(protocol="ssh"))

    def send_command(_connection, command: str, **_kwargs):
        commands.append(command)
        if after_command is not None:
            after_command(command)
        if fail:
            raise RuntimeError("fake connector failure")
        if command == "display saved-configuration":
            return "#\nsysname SW-01\nvlan 10\nreturn"
        if command == "display current-configuration":
            return "#\nsysname SW-01\nvlan 20\nreturn"
        return "success"

    monkeypatch.setattr(
        "netconsole.services.config_lifecycle_service.netmiko_connection.run_netmiko_with_retry",
        run_with_retry,
    )
    monkeypatch.setattr("netconsole.services.config_lifecycle_service.safe_send_command", send_command)
    return commands


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
    app.state.job_center_query_service = JobCenterQueryService(
        paths,
        config_cancel_capability=web_service.cancel_capability,
    )
    return app, paths, device, running, saved, process_adapter


def test_config_web_job_handlers_are_available_through_production_registry() -> None:
    assert {
        "config_web_save_force",
        "config_web_export_diff",
        "config_web_export_snapshots",
    } <= set(registered_task_types())
    with pytest.raises(ValueError, match="一次最多保存 50 台设备配置"):
        dispatch_job(JobSpec("registry-dispatch-probe", "config_web_save_force", {"device_uuids": []}))


def test_config_collection_router_returns_503_without_composed_service() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        response = client.get("/api/config-collection/devices")

    assert response.status_code == 503
    assert response.json() == {"detail": "配置采集 Web 服务未接线"}
    assert not hasattr(app.state, "config_collection_service")


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
    assert any(item["id"] == running.id and item["hash"] == running.hash for item in snapshots.json())
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
    snapshot = app.state.config_collection_service.task_service.repository("demo").get(response.json()[0]["id"])
    assert snapshot is not None
    assert snapshot.source == "local"
    assert snapshot.owner == "web_config_collection"
    assert "password" not in json.dumps(response.json())
    assert tasks.status_code == 200
    assert tasks.json()[0]["status"] == TaskState.RUNNING.value
    assert save.status_code == 422
    assert "config_web_snapshot_save" not in registered_task_types()


def test_config_collection_reuses_active_fetch_for_same_device(tmp_path: Path) -> None:
    app, _paths, device, _running, _saved, adapter = _fixture(tmp_path)

    with TestClient(app) as client:
        first = client.post("/api/config-collection/actions", json={"action": "fetch", "device_ids": [device.id]})
        second = client.post("/api/config-collection/actions", json={"action": "fetch", "device_ids": [device.id]})

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()[0]["id"] == first.json()[0]["id"]
    assert len(adapter.jobs) == 1


def test_config_collection_reuses_active_fetch_under_concurrent_requests(tmp_path: Path) -> None:
    app, _paths, device, _running, _saved, adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    adapter.block_start = True
    barrier = Barrier(3)

    def submit():
        barrier.wait()
        return service.submit_collection("demo", "fetch", [int(device.id)])[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        barrier.wait()
        assert adapter.start_entered.wait(1)
        assert not adapter.second_start_entered.wait(0.1)
        adapter.release_start.set()
        results = [future.result(timeout=2) for future in futures]

    assert results[0].id == results[1].id
    assert len(adapter.jobs) == 1


def test_config_collection_foreign_active_task_does_not_block_valid_fetch(tmp_path: Path) -> None:
    app, _paths, device, _running, _saved, adapter = _fixture(tmp_path)
    repository = app.state.config_collection_service.task_service.repository("demo")
    for task_id, site_name, source in (
        ("foreign-site", "other", "local"),
        ("foreign-source", "demo", "agent"),
    ):
        repository.save(
            TaskSnapshot(
                task_id=task_id,
                task_type="config_web_snapshot_fetch",
                task_name="其他来源配置采集",
                status=TaskState.RUNNING,
                created_time="2026-07-15T10:00:00Z",
                updated_time="2026-07-15T10:00:01Z",
                owner="web_config_collection",
                device=str(device.device_uuid),
                source=source,
                site_name=site_name,
            )
        )

    submitted = app.state.config_collection_service.submit_collection("demo", "fetch", [int(device.id)])[0]

    assert submitted.id not in {"foreign-site", "foreign-source"}
    assert len(adapter.jobs) == 1


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
            owner="web_config_collection",
            source="local",
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
    assert result["left_label"] == "SW-01 · 运行配置 · 20260715_101500"
    assert result["right_label"] == "SW-01 · 保存配置 · 20260715_101500"
    assert result["raw_diff"].startswith("--- SW-01 · 运行配置 · 20260715_101500")
    assert any(row["status"] == "+" and row["right_text"] == "vlan 10" for row in result["diff_rows"])
    assert result["diff_summary"] == {"added": 1, "removed": 0, "modified": 0}
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
        owner="web_config_collection",
        source="local",
        site_name="demo",
    )
    app.state.config_collection_service.task_service.repository("demo").save(task)
    pending = replace(task, task_id="config-web-pending-diff", status=TaskState.RUNNING)
    app.state.config_collection_service.task_service.repository("demo").save(pending)
    with TestClient(app) as client:
        status = client.get("/api/config-collection/tasks/config-web-test-diff")
        added = client.get("/api/config-collection/tasks/config-web-test-diff?diff_filter=added")
        modified = client.get("/api/config-collection/tasks/config-web-test-diff?diff_filter=modified")
        invalid_filter = client.get("/api/config-collection/tasks/config-web-test-diff?diff_filter=unknown")
        artifact = client.get("/api/config-collection/artifacts/diff-config-web-test-diff")
        pending_status = client.get("/api/config-collection/tasks/config-web-pending-diff")
        pending_artifact = client.get("/api/config-collection/artifacts/diff-config-web-pending-diff")

    assert status.status_code == 200
    assert status.json()["result"]["artifact_id"] == "diff-config-web-test-diff"
    assert status.json()["result"]["display_name"] == "config_diff_config-web-test-diff.diff"
    assert added.status_code == 200
    assert "+vlan 10" in added.json()["result"]["raw_diff"]
    assert {row["status"] for row in added.json()["result"]["diff_rows"]} == {"+"}
    assert modified.status_code == 200
    assert modified.json()["result"]["diff_rows"] == []
    assert invalid_filter.status_code == 422
    assert "diff_file" not in status.text
    assert str(paths.data_root) not in status.text
    assert artifact.status_code == 200
    assert "vlan 10" in artifact.text
    assert "artifact_id" not in pending_status.json()["result"]
    assert pending_artifact.status_code == 404


def test_config_collection_delete_requires_scoped_one_time_confirmation(
    tmp_path: Path,
) -> None:
    app, _paths, device, running, _saved, adapter = _fixture(tmp_path)
    _enable_handoff_features(app)

    with TestClient(app) as client:
        issued = client.post(
            "/api/config-collection/snapshots/delete/issue",
            json={"snapshot_ids": [running.id, running.id]},
        )
        tampered = client.post(
            "/api/config-collection/snapshots/delete/confirm",
            json={"confirmation_token": issued.json()["confirmation_token"] + "x", "digest": issued.json()["digest"]},
        )
        deleted = client.post(
            "/api/config-collection/snapshots/delete/confirm",
            json={"confirmation_token": issued.json()["confirmation_token"], "digest": issued.json()["digest"]},
        )
        replay = client.post(
            "/api/config-collection/snapshots/delete/confirm",
            json={"confirmation_token": issued.json()["confirmation_token"], "digest": issued.json()["digest"]},
        )
        cancelled = client.post(f"/api/config-collection/tasks/{deleted.json()['id']}/cancel")
        foreign = client.post("/api/config-collection/tasks/not-a-config-task/cancel")
        directory = client.post("/api/config-collection/desktop-actions/open-directory?directory_kind=config_exports")

    assert issued.status_code == 200
    assert issued.json()["snapshot_ids"] == [running.id]
    assert "删除 1 个" in issued.json()["summary"]
    assert tampered.status_code == 422
    assert deleted.status_code == 202
    assert deleted.json()["type"] == "config_snapshot_delete_many"
    assert adapter.jobs[-1].params["snapshot_ids"] == [running.id]
    assert replay.status_code == 422
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == TaskState.STOPPING.value
    assert foreign.status_code == 404
    assert directory.status_code == 200
    assert directory.json()["target_id"] == "config_exports:demo"
    assert directory.json()["success"] is False
    assert "DesktopActionService" in directory.json()["message"]


def test_config_confirmation_rejects_expiry_site_change_and_digest_tamper(tmp_path: Path) -> None:
    app, _paths, _device, running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service

    issued = service.issue_snapshot_delete("demo", [int(running.id)])
    service._confirmations[issued.confirmation_token] = replace(
        service._confirmations[issued.confirmation_token], expires_at=0
    )
    with pytest.raises(ValueError, match="过期"):
        service.confirm_snapshot_delete("demo", issued.confirmation_token, issued.digest)

    issued = service.issue_snapshot_delete("demo", [int(running.id)])
    with pytest.raises(ValueError, match="内容已变化"):
        service.confirm_snapshot_delete("other", issued.confirmation_token, issued.digest)
    with pytest.raises(ValueError, match="内容已变化"):
        service.confirm_snapshot_delete("demo", issued.confirmation_token, "0" * 64)


def test_config_router_exposes_fixed_save_export_and_desktop_action_contracts(
    tmp_path: Path,
) -> None:
    app, paths, device, running, saved, adapter = _fixture(tmp_path)
    _enable_handoff_features(app)
    opened: list[str] = []

    class DesktopActions:
        def open_controlled_directory(self, target_id: str):
            opened.append(target_id)
            return SimpleNamespace(success=True, code="opened", message="已打开")

    app.state.config_collection_service.desktop_action_service = DesktopActions()
    with TestClient(app) as client:
        preview = client.post(
            "/api/config-collection/actions/save-force/preview",
            json={"device_ids": [device.id]},
        )
        saved_task = client.post(
            "/api/config-collection/actions/save-force/confirm",
            json={
                "confirmation_token": preview.json()["confirmation_token"],
                "digest": preview.json()["digest"],
            },
        )
        diff_export = client.post(
            "/api/config-collection/exports/diff",
            json={"left_snapshot_id": running.id, "right_snapshot_id": saved.id},
        )
        zip_export = client.post(
            "/api/config-collection/exports/snapshots",
            json={"snapshot_ids": [running.id, saved.id]},
        )
        directory = client.post(
            "/api/config-collection/desktop-actions/open-directory?directory_kind=config_exports"
        )

    assert preview.status_code == 200
    assert preview.json()["action_plan"][0] == "固定执行 save force"
    assert saved_task.status_code == 202
    assert saved_task.json()["type"] == "config_web_save_force"
    assert diff_export.json()["type"] == "config_web_export_diff"
    assert zip_export.json()["type"] == "config_web_export_snapshots"
    assert all("output_path" not in json.dumps(job.params) for job in adapter.jobs)
    assert directory.json() == {
        "directory_kind": "config_exports",
        "action": "open_controlled_directory",
        "target_id": "config_exports:demo",
        "success": True,
        "code": "opened",
        "message": "已打开",
    }
    assert opened == ["config_exports:demo"]
    assert paths.config_center_outputs_dir("demo").is_dir()


def test_config_task_recovery_scans_past_other_modules_and_keeps_all_active(tmp_path: Path) -> None:
    app, _paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    repository = app.state.config_collection_service.task_service.repository("demo")
    for index in range(450):
        repository.save(
            TaskSnapshot(
                task_id=f"foreign-{index:04d}",
                task_type="other_module_task",
                task_name="其他模块",
                status=TaskState.COMPLETED,
                created_time=f"2026-07-15T12:{index // 60:02d}:{index % 60:02d}Z",
                updated_time=f"2026-07-15T12:{index // 60:02d}:{index % 60:02d}Z",
                owner="other_module",
                source="local",
                site_name="demo",
            )
        )
    for task_id, status in (("config-history", TaskState.COMPLETED), ("config-active-a", TaskState.RUNNING), ("config-active-b", TaskState.STOPPING)):
        repository.save(
            TaskSnapshot(
                task_id=task_id,
                task_type="config_web_snapshot_fetch",
                task_name="配置任务",
                status=status,
                created_time="2026-07-14T00:00:00Z",
                updated_time="2026-07-14T00:00:00Z",
                owner="web_config_collection",
                source="local",
                site_name="demo",
            )
        )

    tasks = app.state.config_collection_service.list_tasks("demo", limit=2)

    assert {task.id for task in tasks} == {"config-active-a", "config-active-b"}
    tasks = app.state.config_collection_service.list_tasks("demo", limit=3)
    assert {task.id for task in tasks} == {"config-active-a", "config-active-b", "config-history"}


def test_config_task_recovery_keeps_more_than_one_thousand_active_tasks(tmp_path: Path) -> None:
    app, _paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    repository = app.state.config_collection_service.task_service.repository("demo")
    now = utc_now_iso()
    for index in range(1001):
        repository.save(
            TaskSnapshot(
                task_id=f"config-active-{index}",
                task_type="config_web_snapshot_fetch",
                task_name="配置采集",
                created_time=now,
                started_time=now,
                status=TaskState.RUNNING,
                progress=50,
                owner=CONFIG_WEB_OWNER,
                source="local",
                site_name="demo",
                updated_time=now,
            )
        )

    tasks = app.state.config_collection_service.list_tasks("demo", limit=1)

    assert len([task for task in tasks if task.status == TaskState.RUNNING.value]) == 1001


def test_config_get_and_cancel_reject_site_owner_source_and_type_mismatches(tmp_path: Path) -> None:
    app, _paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    repository = service.task_service.repository("demo")
    mismatches = (
        ("wrong-site", "other", "web_config_collection", "local", "config_web_snapshot_fetch"),
        ("wrong-owner", "demo", "other", "local", "config_web_snapshot_fetch"),
        ("wrong-source", "demo", "web_config_collection", "agent", "config_web_snapshot_fetch"),
        ("wrong-type", "demo", "web_config_collection", "local", "other_module_task"),
    )
    for task_id, site_name, owner, source, task_type in mismatches:
        repository.save(
            TaskSnapshot(
                task_id=task_id,
                task_type=task_type,
                task_name="边界测试",
                status=TaskState.RUNNING,
                created_time="2026-07-15T00:00:00Z",
                updated_time="2026-07-15T00:00:00Z",
                owner=owner,
                source=source,
                site_name=site_name,
            )
        )
        assert service.get_task("demo", task_id) is None
        assert service.cancel_task("demo", task_id) is None


@pytest.mark.parametrize("receiver", ["missing", "false", "error", "no-process"])
def test_config_cancel_fails_closed_without_live_owner_receiver(
    tmp_path: Path,
    receiver: str,
) -> None:
    app, paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    task_id = f"config-cancel-{receiver}"
    service.task_service.repository("demo").save(
        TaskSnapshot(
            task_id=task_id,
            task_type="config_web_snapshot_fetch",
            task_name="配置采集",
            status=TaskState.RUNNING,
            created_time="2026-07-17T01:00:00Z",
            updated_time="2026-07-17T01:00:01Z",
            owner="web_config_collection",
            source="local",
            site_name="demo",
        )
    )

    def fail(_task_id: str) -> bool:
        raise RuntimeError("receiver failed")

    service.process_adapter = {
        "missing": None,
        "false": SimpleNamespace(cancel_job=lambda _task_id: False),
        "error": SimpleNamespace(cancel_job=fail),
        "no-process": LocalProcessAdapter(service.task_service),
    }[receiver]

    with pytest.raises(ValueError, match="取消接收端"):
        service.cancel_task("demo", task_id)

    persisted = service.task_service.repository("demo").get(task_id)
    assert persisted is not None and persisted.status is TaskState.RUNNING
    assert not (paths.runtime_cache_dir / "background_jobs" / f"{task_id}.cancel").exists()


def test_config_fake_handlers_complete_save_delete_export_recovery_failure_and_cancel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, paths, device, running, saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    executing = _ExecutingFakeProcessAdapter(service.task_service)
    service.process_adapter = executing
    commands = _install_fake_connector(monkeypatch)

    fetched = service.submit_collection("demo", "fetch", [int(device.id)])[0]
    fetched_status = service.get_task("demo", fetched.id)
    assert fetched_status is not None and fetched_status.status == TaskState.COMPLETED.value
    assert {item.type for item in service.list_snapshots("demo", int(device.id))} >= {"running", "saved", "diff"}
    event_types = {event["type"] for event in service.task_service.repository("demo").list_events(fetched.id)}
    assert {"state", "progress", "finished"} <= event_types
    snapshot_ids_before_save = {item.id for item in service.list_snapshots("demo", int(device.id))}

    save_preview = service.preview_save_force("demo", [int(device.id), int(device.id)])
    assert save_preview.device_ids == [device.id]
    assert save_preview.action_plan == ["固定执行 save force", "仅写入命令审计，不采集或伪造 saved-configuration 快照"]
    saved_task = service.confirm_save_force(
        "demo", save_preview.confirmation_token, save_preview.digest
    )
    saved_status = service.get_task("demo", saved_task.id)
    assert saved_status is not None and saved_status.status == TaskState.COMPLETED.value
    assert commands.count("save force") == 1
    assert all(command in {"screen-length disable", "display current-configuration", "display saved-configuration", "save force"} for command in commands)
    assert "snapshot_ids" not in saved_status.result
    assert {item.id for item in service.list_snapshots("demo", int(device.id))} == snapshot_ids_before_save

    diff_task = service.submit_diff_export("demo", int(running.id), int(saved.id))
    diff_status = service.get_task("demo", diff_task.id)
    assert diff_status is not None and diff_status.status == TaskState.COMPLETED.value
    diff_artifact_id = str(diff_status.result["artifact_id"])
    diff_path, diff_name = service.open_artifact("demo", diff_artifact_id)
    assert diff_name.endswith(".diff")
    diff_text = diff_path.read_text(encoding="utf-8")
    assert "--- SW-01 · 运行配置 · 20260715_101500" in diff_text
    assert "+++ SW-01 · 保存配置 · 20260715_101500" in diff_text
    assert "+vlan 10" in diff_text
    assert diff_status.result["hash"] == hashlib.sha256(diff_path.read_bytes()).hexdigest()
    assert diff_status.result["size"] == diff_path.stat().st_size
    assert str(paths.data_root) not in json.dumps(diff_status.model_dump(), ensure_ascii=False)

    zip_task = service.submit_snapshots_export("demo", [int(running.id), int(saved.id), int(running.id)])
    zip_status = service.get_task("demo", zip_task.id)
    assert zip_status is not None and zip_status.status == TaskState.COMPLETED.value
    zip_path, zip_name = service.open_artifact("demo", str(zip_status.result["artifact_id"]))
    with zipfile.ZipFile(zip_path) as archive:
        assert any(name.endswith("running_20260715_101500.txt") for name in archive.namelist())
        assert "_netconsole_manifest.json" in archive.namelist()
    with TestClient(app) as client:
        diff_download = client.get(f"/api/config-collection/artifacts/{diff_artifact_id}")
        zip_download = client.get(
            f"/api/config-collection/artifacts/{zip_status.result['artifact_id']}"
        )
    assert diff_download.status_code == 200
    assert diff_name in unquote(diff_download.headers["content-disposition"])
    assert int(diff_download.headers["content-length"]) == diff_path.stat().st_size
    assert diff_download.headers["content-type"] == "text/plain; charset=utf-8"
    assert zip_download.status_code == 200
    assert zip_name in unquote(zip_download.headers["content-disposition"])
    assert str(zip_status.result["artifact_id"]) not in unquote(
        zip_download.headers["content-disposition"]
    )
    assert int(zip_download.headers["content-length"]) == zip_path.stat().st_size
    assert zip_download.headers["content-type"] == "application/zip"

    refreshed = ConfigCollectionApplicationService(paths, service.task_service, _FakeProcessAdapter(service.task_service))
    recovered = refreshed.get_task("demo", zip_task.id)
    assert recovered is not None and recovered.id == zip_task.id
    assert recovered.result["artifact_id"] == zip_status.result["artifact_id"]
    repository = service.task_service.repository("demo")
    persisted_zip_task = repository.get(zip_task.id)
    assert persisted_zip_task is not None
    repository.save(replace(persisted_zip_task, status=TaskState.RUNNING))
    with pytest.raises(FileNotFoundError):
        service.open_artifact("demo", str(zip_status.result["artifact_id"]))
    repository.save(persisted_zip_task)

    manifest_path = zip_path.parent / f"{zip_status.result['artifact_id']}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["display_name"] = "伪造配置快照.zip"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        service.open_artifact("demo", str(zip_status.result["artifact_id"]))

    forged_content = b"synchronized-file-and-manifest-tamper"
    zip_path.write_bytes(forged_content)
    manifest["display_name"] = zip_status.result["display_name"]
    manifest["size_bytes"] = len(forged_content)
    manifest["sha256"] = hashlib.sha256(forged_content).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        service.open_artifact("demo", str(zip_status.result["artifact_id"]))

    delete_preview = service.issue_snapshot_delete("demo", [int(running.id), int(saved.id)])
    ConfigLifecycleService("demo", Database(paths.site_db_path("demo")), paths).delete_snapshot(
        ConfigSnapshotRepository(Database(paths.site_db_path("demo")), ensure_schema=False).get(int(running.id))
    )
    delete_task = service.confirm_snapshot_delete(
        "demo", delete_preview.confirmation_token, delete_preview.digest
    )
    delete_status = service.get_task("demo", delete_task.id)
    assert delete_status is not None and delete_status.status == TaskState.COMPLETED.value
    assert delete_status.result["deleted"] == 1
    assert delete_status.result["failed"] == 1
    assert delete_status.result["partial_success"] is True
    assert delete_status.result["failed_items"][0]["snapshot_id"] == running.id

    _install_fake_connector(monkeypatch, fail=True)
    failed = service.submit_collection("demo", "fetch", [int(device.id)])[0]
    failed_status = service.get_task("demo", failed.id)
    assert failed_status is not None and failed_status.status == TaskState.FAILED.value

    _install_fake_connector(monkeypatch)
    executing.cancel_next = True
    cancelled = service.submit_collection("demo", "fetch", [int(device.id)])[0]
    cancelled_status = service.get_task("demo", cancelled.id)
    assert cancelled_status is not None and cancelled_status.status == TaskState.CANCELLED.value


def test_config_snapshot_delete_all_failures_end_as_failed_task(tmp_path: Path) -> None:
    app, paths, _device, running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    service.process_adapter = _ExecutingFakeProcessAdapter(service.task_service)
    preview = service.issue_snapshot_delete("demo", [int(running.id)])
    database = Database(paths.site_db_path("demo"))
    lifecycle = ConfigLifecycleService("demo", database, paths)
    lifecycle.delete_snapshot(ConfigSnapshotRepository(database, ensure_schema=False).get(int(running.id)))

    task = service.confirm_snapshot_delete("demo", preview.confirmation_token, preview.digest)
    status = service.get_task("demo", task.id)

    assert status is not None
    assert status.status == TaskState.FAILED.value
    assert "删除全部失败" in status.error_message


def test_config_delete_batch_cancels_between_items_and_recovers_completed_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, paths, _device, running, saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    executing = _ExecutingFakeProcessAdapter(service.task_service)
    service.process_adapter = executing
    original_delete = ConfigLifecycleService.delete_snapshot
    deleted_calls = 0

    def delete_then_cancel(self, snapshot):
        nonlocal deleted_calls
        result = original_delete(self, snapshot)
        deleted_calls += 1
        if deleted_calls == 1:
            executing.cancel_next = True
            service.task_service.request_cancel(executing.jobs[-1].job_id)
        return result

    monkeypatch.setattr(ConfigLifecycleService, "delete_snapshot", delete_then_cancel)
    preview = service.issue_snapshot_delete("demo", [int(running.id), int(saved.id)])

    task = service.confirm_snapshot_delete("demo", preview.confirmation_token, preview.digest)
    status = service.get_task("demo", task.id)
    refreshed = ConfigCollectionApplicationService(paths, service.task_service, _FakeProcessAdapter(service.task_service))
    recovered = refreshed.get_task("demo", task.id)

    assert status is not None and status.status == TaskState.CANCELLED.value
    assert status.result["deleted"] == 1
    assert status.result["failed"] == 0
    assert status.result["not_started_items"] == [saved.id]
    assert status.result["cancel_policy"] == "checkpointed_between_items"
    assert recovered is not None and recovered.result["deleted"] == 1


def test_config_save_force_batch_cancels_between_devices_and_recovers_audit_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, paths, device, _running, _saved, _adapter = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    second = DeviceRepository(database).create(
        Device(
            name="SW-02",
            device_uuid=Device.new_uuid(),
            device_vendor="H3C",
            device_type="SW",
            ip_address="192.0.2.11",
            ssh_username="operator",
            ssh_password="secret-password",
        )
    )
    service = app.state.config_collection_service
    executing = _ExecutingFakeProcessAdapter(service.task_service)
    service.process_adapter = executing
    save_count = 0

    def request_cancel_after_first_save(command: str) -> None:
        nonlocal save_count
        if command != "save force":
            return
        save_count += 1
        if save_count == 1:
            executing.cancel_next = True
            service.task_service.request_cancel(executing.jobs[-1].job_id)

    _install_fake_connector(monkeypatch, after_command=request_cancel_after_first_save)
    preview = service.preview_save_force("demo", [int(device.id), int(second.id)])

    task = service.confirm_save_force("demo", preview.confirmation_token, preview.digest)
    status = service.get_task("demo", task.id)
    refreshed = ConfigCollectionApplicationService(paths, service.task_service, _FakeProcessAdapter(service.task_service))
    recovered = refreshed.get_task("demo", task.id)

    assert status is not None and status.status == TaskState.CANCELLED.value
    assert status.result["saved"] == 1
    assert "snapshot_ids" not in status.result
    assert status.result["not_started_items"] == [str(second.device_uuid)]
    assert status.result["cancel_policy"] == "checkpointed_between_items"
    assert recovered is not None and recovered.result["saved"] == 1


def test_config_running_irreversible_task_accepts_checkpointed_cancel(tmp_path: Path) -> None:
    app, paths, device, _running, _saved, _adapter = _fixture(tmp_path)
    service = app.state.config_collection_service
    preview = service.preview_save_force("demo", [int(device.id)])
    task = service.confirm_save_force("demo", preview.confirmation_token, preview.digest)
    context = JobContext.from_job(
        JobSpec(
            job_id=task.id,
            task_type="config_web_save_force",
            params={
                "site_name": "demo",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "save_force",
            "status": "running",
            "total": 1,
            "completed_items": [],
            "failed_items": [],
            "current_item": {"device_uuid": device.device_uuid},
            "pending_items": [],
        },
    )

    assert service.cancel_capability("demo", task.id) == (True, "")
    with TestClient(app) as client:
        detail = client.get(f"/api/job-center/tasks/{task.id}")
        response = client.post(f"/api/job-center/tasks/{task.id}/cancel")

    assert detail.status_code == 200
    assert detail.json()["cancellable"] is True
    assert response.status_code == 200
    cancelled = service.get_task("demo", task.id)
    assert cancelled is not None
    assert cancelled.status == TaskState.STOPPING.value

    status = service.get_task("demo", task.id)
    assert status is not None and status.status == TaskState.STOPPING.value


def test_config_forced_stop_recovers_irreversible_checkpoint_as_structured_partial(tmp_path: Path) -> None:
    _app, paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    task_id = "config-web-" + "a" * 32
    job = JobSpec(
        job_id=task_id,
        task_type="config_snapshot_delete_many",
        params={
            "site_name": "demo",
            "owner": "web_config_collection",
            "task_source": "local",
            "task_name": "删除配置快照",
        },
    )
    launch = task_service.prepare(job)
    task_service.mark_running(task_id)
    context = JobContext.from_job(
        JobSpec(
            job_id=task_id,
            task_type=job.task_type,
            params={
                **job.params,
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "delete_snapshots",
            "status": "running",
            "total": 3,
            "completed_items": [{"snapshot_id": 11}],
            "failed_items": [],
            "current_item": {"snapshot_id": 12},
            "pending_items": [13],
        },
    )
    task_service.request_cancel(task_id)
    task_service.record_external_event(
        task_id,
        "cancelled",
        {"message": "宿主已终止 Worker"},
        source="local",
        site_name="demo",
    )

    refreshed = ConfigCollectionApplicationService(paths, task_service, _FakeProcessAdapter(task_service))
    recovered = refreshed.get_task("demo", task_id)

    assert recovered is not None and recovered.status == TaskState.CANCELLED.value
    assert recovered.result == {
        "total": 3,
        "failed": 0,
        "failed_items": [],
        "unknown_items": [{"snapshot_id": 12}],
        "not_started_items": [13],
        "interrupted": True,
        "partial_success": True,
        "cancel_policy": "checkpointed_between_items",
        "deleted": 1,
        "deleted_snapshot_ids": [11],
    }
    assert recovered.error_message == "宿主已终止 Worker"
    recovery_events = [
        event
        for event in task_service.repository("demo").list_events(task_id, limit=100)
        if event["type"] == "recovery"
    ]
    assert len(recovery_events) == 1
    assert config_collection_job_handlers.read_irreversible_checkpoint(paths, launch.job.job_id) is None


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        (
            {
                "total": 2,
                "saved": 1,
                "failed": 1,
                "failed_items": [{"device_uuid": "missing", "error": "设备不存在"}],
                "partial_success": True,
                "cancel_policy": "checkpointed_between_items",
            },
            TaskState.COMPLETED,
        ),
        (
            {
                "total": 1,
                "saved": 0,
                "failed": 1,
                "failed_items": [{"device_uuid": "missing", "error": "设备不存在"}],
                "partial_success": True,
                "cancel_policy": "checkpointed_between_items",
            },
            TaskState.FAILED,
        ),
    ],
)
def test_config_completed_checkpoint_recovers_failed_terminal_once(
    tmp_path: Path,
    result: dict[str, object],
    expected_status: TaskState,
) -> None:
    _app, paths, _device, _running, _saved, _adapter = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    task_id = "config-web-" + "b" * 32
    params = {
        "site_name": "demo",
        "owner": "web_config_collection",
        "task_source": "local",
        "task_name": "保存配置",
    }
    task_service.prepare(JobSpec(job_id=task_id, task_type="config_web_save_force", params=params))
    task_service.mark_running(task_id)
    context = JobContext.from_job(
        JobSpec(
            job_id=task_id,
            task_type="config_web_save_force",
            params={**params, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
        )
    )
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "save_force",
            "status": "completed",
            "total": int(result["total"]),
            "completed_items": [],
            "failed_items": list(result["failed_items"]),
            "current_item": None,
            "pending_items": [],
            "result": result,
        },
    )
    task_service.record_external_event(
        task_id,
        "error",
        {"message": "Worker 终态事件丢失"},
        source="local",
        site_name="demo",
    )
    service = ConfigCollectionApplicationService(paths, task_service, _FakeProcessAdapter(task_service))

    with ThreadPoolExecutor(max_workers=2) as executor:
        recovered = list(executor.map(lambda _value: service.get_task("demo", task_id), range(2)))

    assert all(item is not None and item.status == expected_status.value for item in recovered)
    snapshot = task_service.repository("demo").get(task_id)
    assert snapshot is not None and snapshot.status is expected_status
    assert snapshot.result == result
    assert snapshot.error_message == ("" if expected_status is TaskState.COMPLETED else "Worker 终态事件丢失")
    events = task_service.repository("demo").list_events(task_id, limit=100)
    assert len([event for event in events if event["type"] == "recovery"]) == 1
    assert config_collection_job_handlers.read_irreversible_checkpoint(paths, task_id) is None


def test_config_export_forwards_progress_before_worker_finishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _app, paths, _device, running, saved, _adapter = _fixture(tmp_path)
    release_terminal = Event()
    progress_seen = Event()

    class StreamingProcess:
        returncode = None

        def __init__(self, command, **_kwargs) -> None:
            self.payload = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            self.stdout = self.Output(self)

        class Output:
            def __init__(self, process) -> None:
                self.process = process
                self.index = 0

            def readline(self) -> str:
                self.index += 1
                if self.index == 1:
                    return encode_event(progress_event("export", "streaming", 1, 2, "已写入一半"))
                if self.index == 2:
                    assert release_terminal.wait(2)
                    Path(self.process.payload["output_path"]).write_text("exported", encoding="utf-8")
                    self.process.returncode = 0
                    return encode_event(finished_event("export", {"ok": True}))
                return ""

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(config_collection_job_handlers.subprocess, "Popen", StreamingProcess)
    context = JobContext.from_job(
        JobSpec(
            "streaming-export",
            "config_web_export_diff",
            {
                "site_name": "demo",
                "db_path": str(paths.site_db_path("demo")),
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "owner": "web_config_collection",
                "task_source": "local",
                "left_snapshot_id": running.id,
                "right_snapshot_id": saved.id,
            },
        ),
        progress_callback=lambda stage, *_args: progress_seen.set() if stage == "streaming" else None,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(config_collection_job_handlers.config_web_export_diff, context)
        assert progress_seen.wait(1)
        assert not future.done()
        release_terminal.set()
        result = future.result(timeout=2)

    assert result["size"] == len("exported")


def test_config_export_handler_cleans_output_job_and_tmp_on_failure_and_cancel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _app, paths, _device, running, saved, _adapter = _fixture(tmp_path)
    params = {
        "site_name": "demo",
        "db_path": str(paths.site_db_path("demo")),
        "app_root": str(paths.app_root),
        "data_root": str(paths.data_root),
        "owner": "web_config_collection",
        "task_source": "local",
        "left_snapshot_id": running.id,
        "right_snapshot_id": saved.id,
    }

    class FailedProcess:
        returncode = 1

        def __init__(self, command, **_kwargs) -> None:
            self.command = command
            payload = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            Path(payload["output_path"]).write_text("partial", encoding="utf-8")
            Path(payload["tmp_path"]).write_text("partial", encoding="utf-8")
            self.stdout = io.StringIO(encode_event(error_event("export", "fake export failure")))

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(config_collection_job_handlers.subprocess, "Popen", FailedProcess)
    failed_context = JobContext.from_job(JobSpec("failed-export", "config_web_export_diff", params))
    with pytest.raises(RuntimeError, match="fake export failure"):
        config_collection_job_handlers.config_web_export_diff(failed_context)

    outputs = paths.config_center_root("demo") / "outputs"
    runtime_jobs = paths.runtime_cache_dir / "export_jobs"
    assert not list(outputs.glob("export-*"))
    assert not list(runtime_jobs.glob("failed-export*"))

    class HungProcess(FailedProcess):
        returncode = None

        def terminate(self):
            self.returncode = -15

    checks = iter((False, True))
    monkeypatch.setattr(config_collection_job_handlers.subprocess, "Popen", HungProcess)
    cancelled_context = JobContext.from_job(
        JobSpec("cancelled-export", "config_web_export_diff", params),
        should_cancel=lambda: next(checks, True),
    )
    with pytest.raises(BackgroundTaskCancelled):
        config_collection_job_handlers.config_web_export_diff(cancelled_context)
    assert not list(outputs.glob("export-*"))
    assert not list(runtime_jobs.glob("cancelled-export*"))
