from __future__ import annotations

import os
import paramiko
import sys
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.file_management_router import router
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, MeshSchemaRebuildRequired
from netconsole.services.background_job import BackgroundJob
from netconsole.services.device_operation_service import DeviceSftpEnableProfileUnresolved
from netconsole.services.file_transfer_service import (
    FileTransferService,
    RemoteDeviceFile,
    SftpUnavailableError,
    file_sha256,
    normalize_remote_path,
)
from netconsole.services.host_key_trust_service import HostKeyTrustGrant
from netconsole.services.host_key_trust_service import HostKeyChallengeError
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    FileReferenceNotFound,
    run_file_management_download,
)
from netconsole.services.external_terminal import WinScpLaunchResult
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.job_registry import dispatch_job
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.mesh_storage_service import MeshStorageService


def _fixture(tmp_path: Path) -> tuple[PathResolver, Path]:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    source = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "MR-01" / "sessions" / "s1" / "raw" / "collector.log"
    source.parent.mkdir(parents=True)
    source.write_text("sample", encoding="utf-8")
    (source.parent.parent / "outputs").mkdir()
    (source.parent.parent / "outputs" / "report.xlsx").write_bytes(b"report")
    return paths, source


def _app(service: FileManagementApplicationService, *, remote_enabled: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.paths = service.paths
    app.state.file_management_service = service
    app.state.feature_gate = FeatureGate(service.paths.app_root)
    if remote_enabled:
        app.state.feature_gate.features["capability.file_management.remote"].update(
            visible=True,
            enabled=True,
            client_package=True,
        )
    app.include_router(router, prefix="/api")
    return app


def test_local_file_refs_are_opaque_and_path_escape_or_symlink_is_rejected(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    service = FileManagementApplicationService(paths)
    page = service.list_files("demo")

    row = next(item for item in page.items if item.name == source.name)
    assert row.file_ref.startswith("fm1_")
    assert len(row.file_ref) == 36
    assert str(tmp_path) not in row.model_dump_json()
    assert service.resolve_ref("demo", row.file_ref).path == source.resolve()
    with pytest.raises(FileReferenceNotFound):
        service.resolve_ref("demo", "../outside")
    with pytest.raises(FileReferenceNotFound):
        service.resolve_ref("demo", "fm1_" + "0" * 32)

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = paths.site_files_dir("demo") / "rail_transit" / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前 Windows 环境不允许创建测试符号链接")
    assert all(item.name != link.name for item in service.list_files("demo").items)


def test_local_file_index_excludes_databases_runtime_files_and_unknown_formats(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    files_root = paths.site_files_dir("demo")
    blocked = [
        files_root / "parsed" / "online_diagnosis.sqlite",
        files_root / "outputs" / "active.db-wal",
        files_root / "outputs" / "unknown.bin",
        files_root / "raw" / "private.key",
        files_root / "rail_transit" / "online_mr" / "imports" / "unknown.bin",
    ]
    for path in blocked:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private")

    service = FileManagementApplicationService(paths)
    page = service.list_files("demo")

    assert not {path.name for path in blocked} & {item.name for item in page.items}
    for path in blocked:
        ref = service._file_ref("demo", path.relative_to(files_root).as_posix())
        with pytest.raises(FileReferenceNotFound):
            service.resolve_ref("demo", ref)


def test_local_dual_pane_browser_is_root_clamped_paginated_and_supports_directory_creation(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(name="MR-LOCAL", device_type="MR", primary_address="192.0.2.80")
    )
    root = paths.file_downloads_root("demo")
    root.mkdir(parents=True)
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "folder").mkdir()
    (root / "folder" / "a.txt").write_text("a", encoding="utf-8")
    stale_part = root / "stale.bin.part"
    stale_part.write_bytes(b"partial")
    old = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(stale_part, (old, old))
    service = FileManagementApplicationService(paths)

    first = service.list_local_files("demo", page=1, limit=1)
    assert first.total == 2
    assert first.has_more is True
    assert first.items[0].is_dir is True
    assert str(root) not in first.model_dump_json()
    assert stale_part.exists(), "页面请求不得同步清理临时文件"
    service.start()
    assert service._parts_cleanup_thread is not None
    service._parts_cleanup_thread.join(timeout=2)
    assert not stale_part.exists()
    service.close()

    nested = service.list_local_files("demo", directory_id=first.items[0].entry_id)
    assert [item.name for item in nested.items] == ["a.txt"]
    assert nested.parent_entry_id == first.current_entry_id
    created = service.create_local_directory("demo", directory_id=nested.current_entry_id, name="新 目录")
    assert "新_目录" in {item.name for item in created.items}
    device_default = service.list_local_files("demo", device_id=device.device_uuid)
    assert device_default.current_entry_id != device_default.root_entry_id
    assert device_default.parent_entry_id == device_default.root_entry_id
    site_root = service.list_local_files(
        "demo",
        directory_id=device_default.parent_entry_id,
        device_id=device.device_uuid,
    )
    assert site_root.current_entry_id == site_root.root_entry_id
    with pytest.raises(FileReferenceNotFound):
        service.list_local_files("demo", directory_id="fl1_" + "0" * 32)


def test_file_desktop_actions_are_one_time_controlled_and_winscp_passes_password_in_desktop_process_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="MR-DESKTOP",
            device_type="MR",
            primary_address="192.0.2.90",
            ssh_enabled=True,
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    resolved: list[tuple[Path, bool]] = []

    class FakeDesktopActionService:
        runtime_mode = RuntimeMode.DESKTOP

        def resolve_controlled_path(self, path: Path, *, expect_directory: bool):
            resolved.append((path, expect_directory))
            return path.resolve()

    winscp_calls: list[tuple[str, bool]] = []

    def fake_launch_winscp(selected, _settings, _sessions=None, *, include_password=True):
        winscp_calls.append((selected.device_uuid, include_password))
        return WinScpLaunchResult(True, "已启动 WinSCP。", [])

    monkeypatch.setattr(
        "netconsole.services.file_management_service.launch_winscp",
        fake_launch_winscp,
    )
    monkeypatch.setattr(
        "netconsole.services.file_management_service.find_winscp_exe",
        lambda _settings: r"C:\\Tools\\WinSCP.exe",
    )
    service = FileManagementApplicationService(
        paths,
        desktop_action_service=FakeDesktopActionService(),
    )
    local = service.list_local_files("demo")
    open_action = service.desktop_action(
        "open_local",
        site_id="demo",
        local_entry_id=local.current_entry_id,
    )
    open_result = service.execute_desktop_action(open_action.action_ref)
    assert open_result.success is True
    assert open_result.target_path == str(paths.file_downloads_root("demo").resolve())
    assert resolved == [(paths.file_downloads_root("demo").resolve(), True)]
    with pytest.raises(FileReferenceNotFound):
        service.execute_desktop_action(open_action.action_ref)

    downloaded = paths.file_downloads_root("demo") / "downloaded.log"
    downloaded.write_text("done", encoding="utf-8")
    local = service.list_local_files("demo")
    file_entry = next(item for item in local.items if item.name == downloaded.name)
    file_action = service.desktop_action("open_local", site_id="demo", local_entry_id=file_entry.entry_id)
    file_result = service.execute_desktop_action(file_action.action_ref)
    assert file_result.success is True
    assert file_result.target_path == str(downloaded.resolve())
    assert resolved[-1] == (downloaded.resolve(), False)

    winscp_action = service.desktop_action(
        "winscp",
        site_id="demo",
        device_id=device.device_uuid,
    )
    assert service.execute_desktop_action(winscp_action.action_ref).success is True
    assert winscp_calls == [(device.device_uuid, True)]
    assert service.status("demo").winscp.available is True


def test_file_desktop_action_reference_expires_before_execution(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    service = FileManagementApplicationService(paths)
    local = service.list_local_files("demo")
    prepared = service.desktop_action(
        "open_local",
        site_id="demo",
        local_entry_id=local.current_entry_id,
    )
    stored = service._desktop_actions[prepared.action_ref]
    service._desktop_actions[prepared.action_ref] = replace(
        stored,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(FileReferenceNotFound):
        service.consume_desktop_action(prepared.action_ref)
    assert prepared.action_ref not in service._desktop_actions


def test_download_job_only_validates_and_returns_original_ref_without_creating_files(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    service = FileManagementApplicationService(paths)
    source_ref = next(item.file_ref for item in service.list_files("demo").items if item.name == source.name)
    before = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
    job = BackgroundJob(
        job_id="download-test",
        task_type="file_management_download",
        params={"site_name": "demo", "file_ref": source_ref, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
    )

    result = dispatch_job(job)

    after = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
    assert result == {"download_ref": source_ref, "name": source.name, "size_bytes": source.stat().st_size}
    assert before == after
    assert run_file_management_download(JobContext.from_job(job)) == result


def test_file_management_api_lists_filters_and_uses_controlled_download_task(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            task_service.prepare(job)
            return job.job_id

    service = FileManagementApplicationService(paths, task_service=task_service, process_adapter=FakeProcessAdapter())
    with TestClient(_app(service)) as client:
        local = client.get("/api/file-management/local/entries", params={"site_id": "demo"})
        assert local.status_code == 200
        assert str(tmp_path) not in local.text
        created = client.post(
            "/api/file-management/local/directories",
            params={"site_id": "demo"},
            json={"directory_id": local.json()["current_entry_id"], "name": "API 目录"},
        )
        assert created.status_code == 201
        assert "API_目录" in {item["name"] for item in created.json()["items"]}
        response = client.get("/api/file-management/files", params={"site_id": "demo", "category": "raw"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["name"] == source.name
        assert str(tmp_path) not in response.text

        file_ref = payload["items"][0]["file_ref"]
        started = client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"file_ref": file_ref})
        assert started.status_code == 202
        task_id = started.json()["task_id"]
        assert started.json()["status"] in {TaskState.STARTING.value, TaskState.PENDING.value}
        snapshot = task_service.repository("demo").get(task_id)
        assert snapshot is not None
        assert snapshot.source == "local"
        assert snapshot.owner == "web_file_management"
        assert client.get(f"/api/file-management/downloads/{task_id}", params={"site_id": "demo"}).status_code == 200
        result = run_file_management_download(
            JobContext.from_job(
                BackgroundJob(
                    job_id=task_id,
                    task_type="file_management_download",
                    params={"site_name": "demo", "file_ref": file_ref, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
                )
            )
        )
        task_service.record_external_event(task_id, "finished", {"result": result}, site_name="demo")
        before_download = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
        downloaded = client.get(f"/api/file-management/downloads/{task_id}/file", params={"site_id": "demo"})
        after_download = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
        assert downloaded.status_code == 200
        assert downloaded.content == source.read_bytes()
        disposition = unquote(downloaded.headers["content-disposition"])
        assert source.name in disposition
        assert str(tmp_path) not in disposition
        assert int(downloaded.headers["content-length"]) == source.stat().st_size
        assert downloaded.headers["content-type"] == "text/plain; charset=utf-8"
        assert before_download == after_download
        assert client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"file_ref": "../outside"}).status_code == 422
        assert client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": Device.new_uuid()},
        ).status_code == 404
        assert client.post(
            "/api/file-management/desktop-actions/winscp",
            json={"device_id": Device.new_uuid()},
        ).status_code == 404


def test_completed_mesh_import_failure_can_be_retried_and_cleared_as_failed(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            task_service.prepare(job)
            return job.job_id

    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
    )
    file_ref = next(item.file_ref for item in service.list_files("demo").items if item.name == source.name)
    task = service.submit_download("demo", file_ref)
    result = {
        "download_ref": file_ref,
        "name": source.name,
        "size_bytes": source.stat().st_size,
        "mesh_import_status": "failed",
        "mesh_import_error": "MESH 自动导入失败",
    }
    task_service.record_external_event(task.task_id, "finished", {"result": result}, site_name="demo")

    completed = service.download_task("demo", task.task_id)
    assert completed is not None
    assert completed.status == TaskState.COMPLETED.value
    assert completed.retryable is True
    assert completed.result is not None
    assert completed.result.mesh_import_status == "failed"

    retried = service.retry_download("demo", task.task_id)
    assert retried.task_id != task.task_id
    cleared = service.clear_downloads("demo", [TaskState.FAILED.value])
    assert cleared.cleared_count == 1
    assert task.task_id not in {item.task_id for item in service.list_download_tasks("demo")}
    service.close()


def test_download_queue_thread_follows_explicit_host_lifecycle(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            return job.job_id

    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
    )

    assert service._queue_thread is None
    service.start()
    first = service._queue_thread
    service.start()
    assert first is not None and first.is_alive()
    assert service._queue_thread is first

    service.close()
    assert service._queue_thread is None


def test_download_queue_close_waits_for_inflight_repository_work_before_process_shutdown(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    entered = threading.Event()
    release = threading.Event()
    shutdown_called = threading.Event()

    class BlockingProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            return job.job_id

        def shutdown(self) -> None:
            shutdown_called.set()

    adapter = BlockingProcessAdapter()
    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=adapter,
    )
    service._owns_process_adapter = True

    def block_dispatch(_site: str) -> None:
        entered.set()
        release.wait(timeout=5)

    service._dispatch_next_waiting = block_dispatch  # type: ignore[method-assign]
    service.start()
    assert entered.wait(timeout=2)

    closer = threading.Thread(target=service.close)
    closer.start()
    closer.join(timeout=0.2)
    assert closer.is_alive()
    assert service._queue_thread is not None
    assert shutdown_called.is_set() is False

    release.set()
    closer.join(timeout=2)
    assert closer.is_alive() is False
    assert service._queue_thread is None
    assert shutdown_called.is_set() is True


def test_remote_device_list_includes_backup_only_ssh_device(
    tmp_path: Path,
) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="MR-backup-only",
            primary_address="",
            backup_address="10.62.89.105",
            ssh_enabled=1,
        )
    )
    service = FileManagementApplicationService(paths)

    items = service.list_remote_devices("demo")

    assert len(items) == 1
    assert items[0].device_id == device.device_uuid
    assert items[0].address == "10.62.89.105"


def test_remote_file_web_flow_uses_session_entries_persistent_device_file_results_and_rejects_cross_device_reuse(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    device_a = repository.create(Device(name="MR-A", device_type="MR", primary_address="192.0.2.10"))
    device_b = repository.create(Device(name="MR-B", device_type="MR", primary_address="192.0.2.11"))

    class FakeTransfer:
        payloads = {
            "flash:/diagfile/diag_a.tar.gz": b"remote artifact",
            "flash:/diagfile/启动:配置?.bin": b"binary configuration",
        }
        instances: list["FakeTransfer"] = []

        def __init__(
            self,
            site_name,
            fake_paths,
            *,
            strict_host_keys=False,
            host_key_trust=None,
            trust_host_key_once=False,
        ):
            self.site_name = site_name
            self.paths = fake_paths
            self.strict_host_keys = strict_host_keys
            self.host_key_trust = host_key_trust
            self.trust_host_key_once = trust_host_key_once
            self.connected = False
            self.disconnect_calls = 0
            self.root_path = "flash:/"
            self.successful_target = None
            self.attempt_summaries: list[dict[str, object]] = []
            self.instances.append(self)

        def connect(self, device):
            self.connected = True
            self.successful_target = SimpleNamespace(
                method="tunnel1_primary",
                target_role="primary",
                host=device.primary_address,
                port=22,
                via_tunnel=True,
                tunnel_label="tunnel1",
                tunnel=SimpleNamespace(host="198.51.100.10", port=22),
            )
            self.attempt_summaries = [
                {
                    "connection_method": "primary_direct",
                    "target_role": "primary",
                    "target_host": device.primary_address,
                    "target_port": 22,
                    "success": False,
                    "failure_stage": "target_connect",
                    "error_code": "DEVICE_FILE_DIRECT_UNREACHABLE",
                    "message": "设备直连网络不可达或 SSH 端口不可用。",
                    "elapsed_ms": 20,
                },
                {
                    "connection_method": "tunnel1_primary",
                    "target_role": "primary",
                    "target_host": device.primary_address,
                    "target_port": 22,
                    "tunnel_label": "tunnel1",
                    "jump_host": "198.51.100.10",
                    "jump_port": 22,
                    "success": True,
                    "failure_stage": "connected",
                    "elapsed_ms": 35,
                },
            ]
            return self.root_path

        def disconnect(self):
            self.connected = False
            self.disconnect_calls += 1

        def list_directory(self, path):
            current = normalize_remote_path(path, root_path=self.root_path)
            if current == "flash:/":
                return [RemoteDeviceFile("diagfile", "flash:/diagfile", None, None, "dir", is_dir=True, file_type="directory")]
            return [
                RemoteDeviceFile("diag_a.tar.gz", "flash:/diagfile/diag_a.tar.gz", 15, "2026-07-15 10:00:00", "diag"),
                RemoteDeviceFile("启动:配置?.bin", "flash:/diagfile/启动:配置?.bin", 20, "2026-07-15 10:00:00", "bin"),
            ]

        def local_path_for(self, device, remote_file):
            return FileTransferService(self.site_name, self.paths).local_path_for(device, remote_file)

        def download(self, remote_path, local_path, progress_callback=None, cancel_token=None, **_kwargs):
            if cancel_token is not None:
                cancel_token.is_cancelled()
            payload = self.payloads[normalize_remote_path(remote_path)]
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(payload)
            if progress_callback is not None:
                progress_callback(len(payload), len(payload))
            return Path(local_path)

    monkeypatch.setattr("netconsole.services.file_management_service.FileTransferService", FakeTransfer)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    captured: list[BackgroundJob] = []

    class FakeProcessAdapter:
        cancelled: list[str] = []

        def start_job(self, job: BackgroundJob) -> str:
            captured.append(job)
            task_service.prepare(job)
            return job.job_id

        def cancel_job(self, job_id: str) -> bool:
            self.cancelled.append(job_id)
            task_service.record_external_event(job_id, "cancelled", {"message": "后台任务已取消"}, site_name="demo")
            return True

    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
        transfer_factory=FakeTransfer,
    )
    with TestClient(_app(service, remote_enabled=True)) as client:
        candidates = client.get("/api/file-management/devices", params={"site_id": "demo"})
        assert candidates.status_code == 200
        assert candidates.json() == [
            {
                "device_id": device_a.device_uuid,
                "name": "MR-A",
                "address": "192.0.2.10",
                "group_id": None,
                "group_name": "",
                "device_type": "MR",
                "station": "",
            },
            {
                "device_id": device_b.device_uuid,
                "name": "MR-B",
                "address": "192.0.2.11",
                "group_id": None,
                "group_name": "",
                "device_type": "MR",
                "station": "",
            },
        ]
        assert "password" not in candidates.text.casefold()
        connected = client.post("/api/file-management/connections", params={"site_id": "demo"}, json={"device_id": device_a.device_uuid})
        assert connected.status_code == 201
        connection_id = connected.json()["connection_id"]
        assert "flash:/" not in connected.text
        assert FakeTransfer.instances[-1].strict_host_keys is True
        assert connected.json()["connection_method"] == "tunnel1_primary"
        assert connected.json()["target_role"] == "primary"
        assert connected.json()["target_host"] == "192.0.2.10"
        assert connected.json()["target_port"] == 22
        assert connected.json()["via_tunnel"] is True
        assert connected.json()["tunnel_label"] == "tunnel1"
        assert connected.json()["jump_host"] == "198.51.100.10"
        assert connected.json()["jump_port"] == 22
        assert [item["connection_method"] for item in connected.json()["attempts"]] == [
            "primary_direct",
            "tunnel1_primary",
        ]

        reconnected = client.post("/api/file-management/connections", params={"site_id": "demo"}, json={"device_id": device_a.device_uuid})
        assert reconnected.status_code == 201
        assert FakeTransfer.instances[-2].disconnect_calls == 1
        connection_id = reconnected.json()["connection_id"]

        root = client.get(f"/api/file-management/connections/{connection_id}/entries", params={"site_id": "demo"})
        assert root.status_code == 200
        directory_id = root.json()["items"][0]["entry_id"]
        nested = client.get(
            f"/api/file-management/connections/{connection_id}/entries",
            params={"site_id": "demo", "entry_id": directory_id},
        )
        assert nested.status_code == 200
        entries = {item["name"]: item["entry_id"] for item in nested.json()["items"]}
        remote_entry_id = entries["diag_a.tar.gz"]
        binary_entry_id = entries["启动:配置?.bin"]
        remote_entry_ids = [item["entry_id"] for item in nested.json()["items"]]

        second = client.post("/api/file-management/connections", params={"site_id": "demo"}, json={"device_id": device_b.device_uuid})
        assert second.status_code == 201
        second_id = second.json()["connection_id"]
        cross_device = client.get(
            f"/api/file-management/connections/{second_id}/entries",
            params={"site_id": "demo", "entry_id": remote_entry_id},
        )
        assert cross_device.status_code == 404

        started = client.post(
            "/api/file-management/downloads",
            params={"site_id": "demo"},
            json={"connection_id": connection_id, "remote_entry_id": remote_entry_id},
        )
        assert started.status_code == 202
        task_id = started.json()["task_id"]
        assert captured and captured[-1].params["remote_path"] == "flash:/diagfile/diag_a.tar.gz"
        persisted_events = task_service.list_events(task_id)
        assert "flash:/diagfile/diag_a.tar.gz" not in str(persisted_events)
        assert str(paths.site_dir("demo")) not in str(persisted_events)
        first_job = captured[-1]
        pending = client.post(
            "/api/file-management/downloads",
            params={"site_id": "demo"},
            json={"connection_id": connection_id, "remote_entry_id": remote_entry_id},
        )
        assert pending.status_code == 202
        assert len(captured) == 1
        pending_descriptor = service._task_descriptor(task_service.repository("demo"), pending.json()["task_id"])
        assert pending_descriptor is not None
        assert service._task_waiting(task_service.repository("demo"), pending.json()["task_id"])
        assert first_job.params["target_relative_path"] != pending_descriptor["target_relative_path"]
        assert str(first_job.params["target_relative_path"]).startswith("files/file_manager/downloads/MR-A/")
        assert str(pending_descriptor["target_relative_path"]).startswith("files/file_manager/downloads/MR-A/")
        batch = client.post(
            "/api/file-management/downloads/batch",
            params={"site_id": "demo"},
            json={"connection_id": connection_id, "remote_entry_ids": remote_entry_ids},
        )
        assert batch.status_code == 202
        assert len(batch.json()["tasks"]) == 1
        assert len(batch.json()["failures"]) == 1
        assert batch.json()["tasks"][0]["batch_id"] == batch.json()["batch_id"]
        result = run_file_management_download(JobContext.from_job(first_job))
        assert result["sha256"] == file_sha256(paths.site_dir("demo") / str(first_job.params["target_relative_path"]))
        assert result["relative_path"] == first_job.params["target_relative_path"]
        assert "artifact_id" not in result
        task_service.record_external_event(task_id, "finished", {"result": result}, site_name="demo")
        queue = client.get("/api/file-management/downloads", params={"site_id": "demo"})
        assert queue.status_code == 200
        completed = next(item for item in queue.json() if item["task_id"] == task_id)
        assert completed["result"]["result_kind"] == "device_file"
        assert completed["result"]["device_file_ref"].startswith("fd1_")
        assert completed["result"]["artifact_id"] == ""
        assert completed["result"]["relative_path"] == first_job.params["target_relative_path"]
        assert completed["remote_path"] == "flash:/diagfile/diag_a.tar.gz"
        assert completed["local_path"] == str(paths.site_dir("demo") / str(first_job.params["target_relative_path"]))
        device_file = client.get(f"/api/file-management/downloads/{task_id}/file", params={"site_id": "demo"})
        assert device_file.status_code == 200
        assert device_file.content == b"remote artifact"
        assert "diag_a.tar.gz" in unquote(device_file.headers["content-disposition"])
        assert int(device_file.headers["content-length"]) == len(b"remote artifact")
        assert device_file.headers["content-type"] == "application/gzip"

        binary_started = client.post(
            "/api/file-management/downloads",
            params={"site_id": "demo"},
            json={"connection_id": connection_id, "remote_entry_id": binary_entry_id},
        )
        assert binary_started.status_code == 202
        binary_task_id = binary_started.json()["task_id"]
        binary_descriptor = service._task_descriptor(
            task_service.repository("demo"),
            binary_task_id,
        )
        assert binary_descriptor is not None
        binary_job = BackgroundJob(
            job_id=binary_task_id,
            task_type="file_management_download",
            params=service._job_params("demo", binary_descriptor),
        )
        binary_result = run_file_management_download(JobContext.from_job(binary_job))
        assert binary_result["name"] == Path(str(binary_job.params["target_relative_path"])).name
        assert ":" not in str(binary_job.params["target_relative_path"])
        assert "?" not in str(binary_job.params["target_relative_path"])
        task_service.record_external_event(
            binary_task_id,
            "finished",
            {"result": binary_result},
            site_name="demo",
        )
        binary_artifact = client.get(
            f"/api/file-management/downloads/{binary_task_id}/file",
            params={"site_id": "demo"},
        )
        assert binary_artifact.status_code == 200
        assert binary_artifact.content == b"binary configuration"
        assert binary_result["name"] in unquote(binary_artifact.headers["content-disposition"])
        assert int(binary_artifact.headers["content-length"]) == len(b"binary configuration")
        assert binary_artifact.headers["content-type"] == "application/octet-stream"
        cleared = client.post(
            "/api/file-management/downloads/clear",
            params={"site_id": "demo"},
            json={"statuses": [TaskState.COMPLETED.value]},
        )
        assert cleared.status_code == 200
        assert cleared.json()["cleared_count"] == 2
        assert task_id not in {item["task_id"] for item in client.get("/api/file-management/downloads", params={"site_id": "demo"}).json()}
        pending_cancel = client.post(f"/api/file-management/downloads/{pending.json()['task_id']}/cancel", params={"site_id": "demo"})
        assert pending_cancel.status_code == 200
        assert pending_cancel.json()["status"] == TaskState.CANCELLED.value
        batch_cancel = client.post(
            f"/api/file-management/downloads/{batch.json()['tasks'][0]['task_id']}/cancel",
            params={"site_id": "demo"},
        )
        assert batch_cancel.status_code == 200
        cancelled = client.post(f"/api/file-management/downloads/{task_id}/cancel", params={"site_id": "demo"})
        assert cancelled.status_code == 422
        prepared_action = client.post(
            "/api/file-management/desktop-actions/winscp",
            json={"device_id": device_a.device_uuid},
        )
        assert prepared_action.status_code == 200
        assert prepared_action.json()["action_ref"].startswith("fda1_")
        assert "password" not in prepared_action.text.casefold()
        assert client.post(
            f"/api/file-management/desktop-actions/{prepared_action.json()['action_ref']}/execute"
        ).status_code == 422
        assert client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"connection_id": connection_id, "remote_entry_id": "fe1_" + "0" * 32}).status_code == 404

        unsafe_job = BackgroundJob(
            job_id="unsafe-remote-download",
            task_type="file_management_download",
            params={
                "site_name": "demo",
                "device_id": device_a.device_uuid,
                "remote_entry_id": remote_entry_id,
                "remote_path": "flash:/diagfile/diag_a.tar.gz",
                "remote_name": "diag_a.tar.gz",
                "remote_category": "diag",
                "target_relative_path": "file_manager/downloads/../outside.bin",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
        with pytest.raises(FileReferenceNotFound):
            run_file_management_download(JobContext.from_job(unsafe_job))
    session_instances = [instance for instance in FakeTransfer.instances if instance.connected]
    service.close()
    service.close()
    assert all(not instance.connected and instance.disconnect_calls == 1 for instance in session_instances)
    restarted = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
    )
    recovered = next(item for item in restarted.list_download_tasks("demo") if item.task_id == pending.json()["task_id"])
    assert recovered.remote_name == "diag_a.tar.gz"
    assert recovered.retryable is True
    retried = restarted.retry_download("demo", recovered.task_id)
    assert retried.task_id != recovered.task_id
    assert next(job for job in captured if job.job_id == retried.task_id).params["remote_path"] == "flash:/diagfile/diag_a.tar.gz"
    restarted.close()


def test_web_connect_is_strict_read_only_when_sftp_is_disabled(tmp_path: Path, monkeypatch) -> None:
    import netconsole.services.file_transfer_service as transfer_module

    paths, _source = _fixture(tmp_path)
    commands: list[str] = []
    host_key_events: list[str] = []
    log_events: list[tuple[str, str]] = []

    class FakeTransport:
        def __init__(self):
            self.active = True

        def is_active(self):
            return self.active

    class FakeSshClient:
        instances: list["FakeSshClient"] = []

        def __init__(self):
            self.transport = FakeTransport()
            self.connect_called = False
            self.instances.append(self)

        def set_missing_host_key_policy(self, policy):
            host_key_events.append(policy.__class__.__name__)

        def connect(self, **_kwargs):
            self.connect_called = True
            self.transport.active = True

        def get_transport(self):
            return self.transport

        def open_sftp(self):
            self.transport.active = False
            raise RuntimeError("Channel closed.")

        def invoke_shell(self):
            commands.append("invoke_shell")
            raise AssertionError("Web read-only connection must not open a configuration shell")

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(
            SSHClient=FakeSshClient,
            MissingHostKeyPolicy=object,
            BadHostKeyException=RuntimeError,
        ),
    )
    monkeypatch.setattr(transfer_module.app_logger, "log_error", lambda event, message: log_events.append((event, message)))
    device = Device(
        device_uuid=Device.new_uuid(),
        name="MR-read-only",
        device_type="MR",
        primary_address="192.0.2.30",
        ssh_enabled=1,
        ssh_username="ops",
        ssh_password="secret",
    )
    service = FileManagementApplicationService(paths, device_resolver=lambda _site, _device_id: device)

    with TestClient(_app(service, remote_enabled=True)) as client:
        response = client.post("/api/file-management/connections", params={"site_id": "demo"}, json={"device_id": device.device_uuid})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEVICE_FILE_SFTP_UNAVAILABLE"
    assert response.json()["detail"]["details"]["confirmation_id"].startswith("sf1_")
    assert response.json()["detail"]["message"] == "检测到设备未启用 SFTP，需要确认后通过受控命令启用并重新连接。"
    assert "channel closed" not in response.text.casefold()
    assert "DEVICE_FILE_NETWORK_UNREACHABLE" not in response.text
    assert FakeSshClient.instances[0].connect_called is True
    assert FakeSshClient.instances[0].transport.active is False
    assert commands == []
    assert host_key_events == ["_ManagedHostKeyPolicy"]
    rejected = next(message for event, message in log_events if event == "SFTP_SUBSYSTEM_REJECTED")
    for field in (
        "site_id=demo",
        "failure_stage=open_sftp",
        "ssh_authenticated=True",
        "transport_active=False",
        "exception_type=RuntimeError",
        "classification_reason=explicit_marker:channel_closed",
        "classified_code=DEVICE_FILE_SFTP_UNAVAILABLE",
    ):
        assert field in rejected
    assert "secret" not in rejected


def test_web_connect_authorized_sftp_setup_runs_device_operation_then_reconnects(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="MR-auto-sftp",
        device_vendor="H3C",
        device_type="MR",
        primary_address="192.0.2.31",
        ssh_enabled=1,
        ssh_username="ops",
        ssh_password="secret",
    )
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    operation_calls: list[tuple[str, str]] = []
    host_key = paramiko.RSAKey.generate(1024)

    class FakeDeviceOperationService:
        def start(self, device_uuid: str, operation_id: str, **_kwargs):
            operation_calls.append((device_uuid, operation_id))
            task_id = "device-sftp-enable-test"
            task_service.repository("demo").save(
                TaskSnapshot(
                    task_id=task_id,
                task_type="device_sftp_enable",
                task_name="启用设备 SFTP",
                status=TaskState.COMPLETED,
                created_time="2026-07-19T00:00:00Z",
                updated_time="2026-07-19T00:00:00Z",
                owner="web_file_management",
                    source="local",
                    site_name="demo",
                    device=device_uuid,
                )
            )
            return SimpleNamespace(task_id=task_id, status="COMPLETED")

        def cancel(self, _task_id: str, *, site: str) -> bool:
            return site == "demo"

    class FakeProcessAdapter:
        @staticmethod
        def wait(_task_id: str, _timeout: float) -> bool:
            return True

    class FakeTransfer:
        instances: list["FakeTransfer"] = []

        def __init__(self, *_args, **_kwargs):
            self.index = len(self.instances)
            self.instances.append(self)

        def connect(self, _device):
            if self.index == 0:
                raise SftpUnavailableError()
            if self.index == 1:
                raise HostKeyChallengeError(
                    "SFTP 重连目标需要确认设备主机密钥。",
                    {
                        "host": "192.0.2.31",
                        "port": 22,
                        "algorithm": "ssh-ed25519",
                        "fingerprint_sha256": "SHA256:reconnect",
                    },
                    key=host_key,
                )
            return "flash:/"

        def disconnect(self):
            pass

    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
        device_resolver=lambda _site, _device_id: device,
        transfer_factory=FakeTransfer,
        device_operation_service=FakeDeviceOperationService(),  # type: ignore[arg-type]
    )

    with TestClient(_app(service, remote_enabled=True)) as client:
        requested = client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": device.device_uuid},
        )
        challenged = client.post(
            "/api/file-management/connections/confirm-sftp-setup",
            params={"site_id": "demo"},
            json={"confirmation_id": requested.json()["detail"]["details"]["confirmation_id"]},
        )
        response = client.post(
            "/api/file-management/host-keys/trust-once",
            params={"site_id": "demo"},
            json={"challenge_id": challenged.json()["detail"]["details"]["challenge_id"]},
        )

    assert requested.status_code == 409
    assert challenged.status_code == 409
    assert challenged.json()["detail"]["code"] == "DEVICE_FILE_HOST_KEY_UNKNOWN"
    assert response.status_code == 201
    assert response.json()["message"] == "已在设备侧启用 SFTP，并完成重新连接。"
    assert operation_calls == [(device.device_uuid, "device.sftp.enable")]
    assert len(FakeTransfer.instances) == 3


def test_confirm_sftp_setup_fails_closed_when_software_version_is_unresolved(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="SW-unknown-version",
        device_vendor="H3C",
        device_type="SW",
        primary_address="192.0.2.33",
        ssh_enabled=1,
    )

    class FakeDeviceOperationService:
        @staticmethod
        def start(_device_uuid: str, _operation_id: str, **_kwargs):
            raise DeviceSftpEnableProfileUnresolved("无法确认设备的软件版本，未执行 SFTP 配置命令。")

    class FakeTransfer:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def connect(_device):
            raise SftpUnavailableError()

        @staticmethod
        def disconnect():
            pass

    service = FileManagementApplicationService(
        paths,
        device_resolver=lambda _site, _device_id: device,
        transfer_factory=FakeTransfer,
        device_operation_service=FakeDeviceOperationService(),  # type: ignore[arg-type]
    )

    with TestClient(_app(service, remote_enabled=True)) as client:
        requested = client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": device.device_uuid},
        )
        response = client.post(
            "/api/file-management/connections/confirm-sftp-setup",
            params={"site_id": "demo"},
            json={"confirmation_id": requested.json()["detail"]["details"]["confirmation_id"]},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED"
    assert response.json()["detail"]["message"] == "无法确认设备的软件版本，未执行 SFTP 配置命令。"


def test_host_key_trust_once_continues_the_original_connection_flow(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="AC-host-key",
        primary_address="192.0.2.32",
        ssh_enabled=1,
    )
    key = paramiko.RSAKey.generate(1024)

    class FakeTransfer:
        instances: list["FakeTransfer"] = []

        def __init__(self, *_args, strict_host_keys=False, trust_host_key_once=False, **_kwargs):
            self.index = len(self.instances)
            self.strict_host_keys = strict_host_keys
            self.trust_host_key_once = trust_host_key_once
            self.instances.append(self)

        def connect(self, _device):
            if self.index == 0:
                raise HostKeyChallengeError(
                    "首次连接需要确认设备主机密钥。",
                    {
                        "host": "192.0.2.32",
                        "port": 22,
                        "algorithm": "ssh-ed25519",
                        "fingerprint_sha256": "SHA256:test",
                    },
                    key=key,
                )
            return "flash:/"

        def disconnect(self):
            pass

    service = FileManagementApplicationService(
        paths,
        device_resolver=lambda _site, _device_id: device,
        transfer_factory=FakeTransfer,
    )
    with TestClient(_app(service, remote_enabled=True)) as client:
        challenged = client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": device.device_uuid},
        )
        trusted = client.post(
            "/api/file-management/host-keys/trust-once",
            params={"site_id": "demo"},
            json={"challenge_id": challenged.json()["detail"]["details"]["challenge_id"]},
        )

    assert challenged.status_code == 409
    assert challenged.json()["detail"]["details"] == {
        "host": "192.0.2.32",
        "port": 22,
        "algorithm": "ssh-ed25519",
        "fingerprint_sha256": "SHA256:test",
        "host_key_role": "target",
        "challenge_id": challenged.json()["detail"]["details"]["challenge_id"],
        "device_id": device.device_uuid,
        "device_name": "AC-host-key",
    }
    assert trusted.status_code == 201
    assert trusted.json()["message"] == "SFTP 连接成功"
    assert FakeTransfer.instances[-1].strict_host_keys is True
    assert len(FakeTransfer.instances[-1].trust_host_key_once) == 1
    assert isinstance(
        FakeTransfer.instances[-1].trust_host_key_once[0],
        HostKeyTrustGrant,
    )


def test_jump_and_target_trust_once_challenges_preserve_both_exact_grants(
    tmp_path: Path,
) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="MR-two-host-keys",
        primary_address="192.0.2.40",
        ssh_enabled=1,
    )
    jump_key = paramiko.RSAKey.generate(1024)
    target_key = paramiko.RSAKey.generate(1024)

    class FakeTransfer:
        instances: list["FakeTransfer"] = []

        def __init__(
            self,
            *_args,
            trust_host_key_once=(),
            **_kwargs,
        ):
            self.index = len(self.instances)
            self.grants = tuple(trust_host_key_once)
            self.instances.append(self)

        def connect(self, _device):
            if self.index == 0:
                raise HostKeyChallengeError(
                    "首次连接需要确认跳板机主机密钥。",
                    {
                        "host": "198.51.100.10",
                        "port": 22,
                        "algorithm": jump_key.get_name(),
                        "fingerprint_sha256": "SHA256:jump",
                        "host_key_role": "jump",
                    },
                    key=jump_key,
                    code="DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN",
                )
            if self.index == 1:
                raise HostKeyChallengeError(
                    "首次连接需要确认目标设备主机密钥。",
                    {
                        "host": "192.0.2.40",
                        "port": 22,
                        "algorithm": target_key.get_name(),
                        "fingerprint_sha256": "SHA256:target",
                        "host_key_role": "target",
                    },
                    key=target_key,
                    code="DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN",
                )
            return "flash:/"

        def disconnect(self):
            pass

    service = FileManagementApplicationService(
        paths,
        device_resolver=lambda _site, _device_id: device,
        transfer_factory=FakeTransfer,
    )
    with TestClient(_app(service, remote_enabled=True)) as client:
        jump_challenge = client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": device.device_uuid},
        )
        target_challenge = client.post(
            "/api/file-management/host-keys/trust-once",
            params={"site_id": "demo"},
            json={
                "challenge_id": jump_challenge.json()["detail"]["details"][
                    "challenge_id"
                ]
            },
        )
        connected = client.post(
            "/api/file-management/host-keys/trust-once",
            params={"site_id": "demo"},
            json={
                "challenge_id": target_challenge.json()["detail"]["details"][
                    "challenge_id"
                ]
            },
        )

    assert jump_challenge.json()["detail"]["code"] == (
        "DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN"
    )
    assert target_challenge.json()["detail"]["code"] == (
        "DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN"
    )
    assert connected.status_code == 201
    assert [len(instance.grants) for instance in FakeTransfer.instances] == [
        0,
        1,
        2,
    ]
    assert FakeTransfer.instances[-1].grants[0].host == "198.51.100.10"
    assert FakeTransfer.instances[-1].grants[1].host == "192.0.2.40"


def test_expired_remote_session_is_removed_and_returns_a_stable_message(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(id=1, device_uuid=Device.new_uuid(), name="AC-session", primary_address="192.0.2.33", ssh_enabled=1)

    class FakeTransfer:
        def __init__(self, *_args, **_kwargs):
            self.connected = False

        def connect(self, _device):
            self.connected = True
            return "flash:/"

        def is_connected(self):
            return self.connected

        def list_directory(self, _path):
            raise RuntimeError("Channel closed.")

        def disconnect(self):
            self.connected = False

    service = FileManagementApplicationService(
        paths,
        device_resolver=lambda _site, _device_id: device,
        transfer_factory=FakeTransfer,
    )
    with TestClient(_app(service, remote_enabled=True)) as client:
        connected = client.post(
            "/api/file-management/connections",
            params={"site_id": "demo"},
            json={"device_id": device.device_uuid},
        )
        connection_id = connected.json()["connection_id"]
        failed = client.get(
            f"/api/file-management/connections/{connection_id}/entries",
            params={"site_id": "demo"},
        )
        stale = client.get(
            f"/api/file-management/connections/{connection_id}/entries",
            params={"site_id": "demo"},
        )

    assert failed.status_code == 409
    assert failed.json()["detail"] == {
        "code": "DEVICE_FILE_SESSION_DISCONNECTED",
        "message": "设备文件会话已断开，请重新连接。",
        "details": {},
    }
    assert "channel closed" not in failed.text.casefold()
    assert stale.status_code == 404


def test_desktop_action_contract_is_opaque_one_time_and_never_contains_password(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    device = Device(
        device_uuid=Device.new_uuid(),
        name="MR-action",
        primary_address="192.0.2.40",
        ssh_username="ops",
        ssh_password="top-secret",
    )
    service = FileManagementApplicationService(paths, device_resolver=lambda _site, _device_id: device)

    prepared = service.desktop_action("winscp", site_id="demo", device_id=device.device_uuid)

    assert prepared.action_ref.startswith("fda1_")
    assert "top-secret" not in prepared.model_dump_json()
    command = service.consume_desktop_action(prepared.action_ref)
    assert command.site_id == "demo"
    assert command.device_id == device.device_uuid
    assert not hasattr(command, "host")
    assert not hasattr(command, "username")
    assert not hasattr(command, "password")
    with pytest.raises(FileReferenceNotFound):
        service.consume_desktop_action(prepared.action_ref)


def test_remote_download_target_keeps_qt_mr_and_regular_device_semantics(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    mr_group = DeviceGroupRepository(database, "demo").create("车载-MR", sort_order=40)
    mr = repository.create(Device(name="MR-01", device_type="MR", primary_address="192.0.2.51", group_id=mr_group.id))
    ac = repository.create(Device(name="AC-01", device_type="AC", primary_address="192.0.2.52"))
    misleading = repository.create(Device(name="MR-looking-switch", device_type="MR", primary_address="192.0.2.53"))
    service = FileManagementApplicationService(paths)
    local = service.list_local_files("demo", device_id=ac.device_uuid)
    created = service.create_local_directory(
        "demo",
        directory_id=local.current_entry_id,
        device_id=ac.device_uuid,
        name="manual",
    )
    manual = next(item for item in created.items if item.name == "manual")

    mr_target, mr_kind = service._download_target(
        "demo",
        mr,
        RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-07-16 12:00:00", "meshlog"),
        manual.entry_id,
    )
    regular_target, regular_kind = service._download_target(
        "demo",
        ac,
        RemoteDeviceFile("diag.tar.gz", "flash:/diagfile/diag.tar.gz", 1, None, "diag"),
        manual.entry_id,
    )
    misleading_target, misleading_kind = service._download_target(
        "demo",
        misleading,
        RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-07-16 12:00:00", "meshlog"),
        manual.entry_id,
    )

    assert mr_kind == "mr_raw"
    assert mr_target.name == "MR-01-2026_07_16-meshlog.log"
    assert paths.site_mesh_root("demo").resolve() in mr_target.parents
    assert regular_kind == "device_file"
    assert regular_target.parent.name == "manual"
    assert paths.file_downloads_root("demo").resolve() in regular_target.parents
    assert misleading_kind == "device_file"
    assert misleading_target.parent.name == "manual"
    profile = MeshStorageService("demo", paths).catalog.get_by_linked_device_id(int(mr.id))
    assert profile is not None
    assert profile.linked_device_uuid == mr.device_uuid
    mr_target.write_text("mesh", encoding="utf-8")
    mr_local = service.list_local_files("demo", device_id=mr.device_uuid)
    assert mr_local.current_label == "raw"
    assert mr_target.name in {item.name for item in mr_local.items}


def test_remote_mesh_download_target_does_not_open_incompatible_parsed_db(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    group = DeviceGroupRepository(database, "demo").create("车载-MR", sort_order=40)
    device = DeviceRepository(database).create(
        Device(name="MR-old-schema", device_type="MR", primary_address="192.0.2.54", group_id=group.id)
    )
    profile = MeshStorageService("demo", paths).create_mr_profile(
        "MR-old-schema",
        linked_device_id=device.id,
        linked_device_uuid=device.device_uuid,
    )
    index_path = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with Database(index_path).connect() as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()
    with pytest.raises(MeshSchemaRebuildRequired):
        MeshMrRepository(index_path)

    target, target_kind = FileManagementApplicationService(paths)._download_target(
        "demo",
        device,
        RemoteDeviceFile("2026_07_21_1meshlog.log.gz", "flash:/2026_07_21_1meshlog.log.gz", 1024, None, "meshlog"),
        "",
    )

    assert target_kind == "mr_raw"
    assert paths.mesh_mr_raw_dir("demo", profile.safe_folder_name).resolve() in target.parents


def test_mr_mesh_download_runs_auto_import_inside_file_job(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(name="MR-02", device_type="MR", primary_address="192.0.2.53")
    )
    imported: list[Path] = []

    class FakeTransfer:
        def __init__(self, *_args, **_kwargs):
            pass

        def connect(self, _device):
            return "flash:/"

        def disconnect(self):
            pass

        def download(self, _remote_path, local_path, progress_callback=None, **_kwargs):
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("mesh", encoding="utf-8")
            if progress_callback:
                progress_callback(4, 4)
            return target

    class FakeImport:
        def __init__(self, *_args, **_kwargs):
            pass

        def import_files(self, _profile, files, **_kwargs):
            imported.extend(files)
            return SimpleNamespace(imported_count=1, duplicate_count=0, parsed_record_count=7)

    monkeypatch.setattr("netconsole.services.file_management_service.FileTransferService", FakeTransfer)
    monkeypatch.setattr("netconsole.services.file_management_service.MeshImportService", FakeImport)
    target = paths.site_mesh_root("demo") / "MR-02" / "raw" / "MR-02-2026_07_16-meshlog.log"
    relative = target.relative_to(paths.site_dir("demo")).as_posix()
    job = BackgroundJob(
        job_id="mesh-auto-import",
        task_type="file_management_download",
        params={
            "site_name": "demo",
            "device_id": device.device_uuid,
            "remote_entry_id": "fe1_" + "1" * 32,
            "remote_path": "flash:/meshlog.log",
            "remote_name": "meshlog.log",
            "remote_category": "meshlog",
            "target_relative_path": relative,
            "target_kind": "mr_raw",
            "mesh_auto_import": True,
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    result = run_file_management_download(JobContext.from_job(job))

    assert result["mesh_import_status"] == "completed"
    assert result["mesh_imported_count"] == 1
    assert result["mesh_parsed_record_count"] == 7
    assert imported == [target.resolve()]


def test_mr_mesh_download_keeps_raw_when_auto_repair_cannot_complete(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(name="MR-03", device_type="MR", primary_address="192.0.2.55")
    )
    expected_profile = MeshStorageService("demo", paths).ensure_mr_profile_identity_for_device(device)
    repaired_profile_ids: list[str] = []

    class FakeTransfer:
        def __init__(self, *_args, **_kwargs):
            pass

        def connect(self, _device):
            return "flash:/"

        def disconnect(self):
            pass

        def download(self, _remote_path, local_path, progress_callback=None, **_kwargs):
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("mesh", encoding="utf-8")
            if progress_callback:
                progress_callback(4, 4)
            return target

    class FakeImport:
        def __init__(self, *_args, **_kwargs):
            pass

        def import_files(self, *_args, **_kwargs):
            raise MeshSchemaRebuildRequired("MESH 派生数据库版本不兼容")

    class FakeMaintenance:
        def __init__(self, *_args, **_kwargs):
            pass

        def repair(self, _site, *, profile_ids, **_kwargs):
            repaired_profile_ids.extend(profile_ids)
            raise RuntimeError("repair failed")

    monkeypatch.setattr("netconsole.services.file_management_service.FileTransferService", FakeTransfer)
    monkeypatch.setattr("netconsole.services.file_management_service.MeshImportService", FakeImport)
    monkeypatch.setattr(
        "netconsole.services.file_management_service.MeshDerivedDataMaintenanceService",
        FakeMaintenance,
    )
    target = paths.site_mesh_root("demo") / "MR-03" / "raw" / "MR-03-2026_07_16-meshlog.log"
    relative = target.relative_to(paths.site_dir("demo")).as_posix()
    job = BackgroundJob(
        job_id="mesh-auto-import-rebuild",
        task_type="file_management_download",
        params={
            "site_name": "demo",
            "device_id": device.device_uuid,
            "remote_entry_id": "fe1_" + "2" * 32,
            "remote_path": "flash:/meshlog.log",
            "remote_name": "meshlog.log",
            "remote_category": "meshlog",
            "target_relative_path": relative,
            "target_kind": "mr_raw",
            "mesh_auto_import": True,
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    result = run_file_management_download(JobContext.from_job(job))

    assert result["mesh_import_status"] == "repair_failed"
    assert result["mesh_import_error_code"] == "MESH_DERIVED_DATA_REPAIR_FAILED"
    assert "自动修复失败" in result["mesh_import_error"]
    assert target.read_text(encoding="utf-8") == "mesh"
    assert repaired_profile_ids == [expected_profile.mr_id]


def test_mesh_parse_failure_keeps_the_downloaded_raw_file(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(name="MR-raw-protected", device_type="MR", primary_address="192.0.2.56")
    )
    profile = MeshStorageService("demo", paths).ensure_mr_profile_identity_for_device(device)
    raw = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name) / "meshlog.log"
    raw.write_text("unsupported", encoding="utf-8")

    class FakeImport:
        def __init__(self, *_args, **_kwargs):
            pass

        def import_files(self, *_args, **_kwargs):
            raise ValueError("parse failed")

    monkeypatch.setattr("netconsole.services.file_management_service.MeshImportService", FakeImport)
    context = JobContext.from_job(
        BackgroundJob(
            job_id="mesh-parse-failure",
            task_type="file_management_download",
            params={"site_name": "demo", "mesh_auto_import": True, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
        )
    )

    result = FileManagementApplicationService(paths)._auto_import_mesh(context, "demo", device, raw, "mr_raw")

    assert result == {
        "mesh_import_status": "failed",
        "mesh_import_error": "MESH 日志格式不受支持或解析失败",
    }
    assert raw.read_text(encoding="utf-8") == "unsupported"


def test_remote_cancel_preserves_cancelled_exception_and_cleans_partial_file(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    transfer = FileTransferService("demo", paths)
    target = paths.file_downloads_root("demo") / "cancelled.bin"

    class FakeSftp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def open(self, _path, _mode):
            return self

        def read(self, _size):
            return b"partial"

    class CancelToken:
        calls = 0

        def is_cancelled(self):
            self.calls += 1
            if self.calls > 1:
                raise BackgroundTaskCancelled("后台任务已取消")
            return False

    transfer._sftp = FakeSftp()
    monkeypatch.setattr(transfer, "_stable_remote_size", lambda *_args: 10)
    with pytest.raises(BackgroundTaskCancelled):
        transfer.download("flash:/diagfile/slow.bin", target, cancel_token=CancelToken())

    assert not target.exists()
    assert not target.with_name(f"{target.name}.part").exists()


def test_download_task_recovery_scans_past_other_modules_and_validates_source(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    repository = task_service.repository("demo")
    for index in range(250):
        timestamp = f"2026-07-15T12:{index // 60:02d}:{index % 60:02d}.000Z"
        repository.save(
            TaskSnapshot(
                task_id=f"other-{index:03d}",
                task_type="device_collection",
                task_name="其他模块任务",
                status=TaskState.COMPLETED,
                created_time=timestamp,
                updated_time=timestamp,
                owner="other_module",
                source="local",
                site_name="demo",
            )
        )
    repository.save(
        TaskSnapshot(
            task_id="file-task-old",
            task_type="file_management_download",
            task_name="文件下载",
            status=TaskState.PENDING,
            created_time="2026-07-15T00:00:00.000Z",
            updated_time="2026-07-15T00:00:00.000Z",
            owner="web_file_management",
            source="local",
            site_name="demo",
        )
    )
    repository.save(
        TaskSnapshot(
            task_id="file-task-external",
            task_type="file_management_download",
            task_name="外部任务",
            status=TaskState.COMPLETED,
            created_time="2026-07-15T00:00:01.000Z",
            updated_time="2026-07-15T00:00:01.000Z",
            owner="web_file_management",
            source="external",
            site_name="demo",
        )
    )
    service = FileManagementApplicationService(paths, task_service=task_service, process_adapter=object())

    tasks = service.list_download_tasks("demo", limit=1)

    assert [task.task_id for task in tasks] == ["file-task-old"]
    assert service.download_task("demo", "file-task-external") is None


def test_download_task_recovery_keeps_older_active_task_ahead_of_recent_history(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    repository = task_service.repository("demo")
    repository.save(
        TaskSnapshot(
            task_id="active-download",
            task_type="file_management_download",
            task_name="仍在运行的下载",
            status=TaskState.RUNNING,
            created_time="2026-07-15T00:00:00.000Z",
            updated_time="2026-07-15T00:00:00.000Z",
            owner="web_file_management",
            source="local",
            site_name="demo",
        )
    )
    for index in range(100):
        timestamp = f"2026-07-15T12:{index // 60:02d}:{index % 60:02d}.000Z"
        repository.save(
            TaskSnapshot(
                task_id=f"completed-download-{index:03d}",
                task_type="file_management_download",
                task_name="历史下载",
                status=TaskState.COMPLETED,
                created_time=timestamp,
                updated_time=timestamp,
                owner="web_file_management",
                source="local",
                site_name="demo",
            )
        )
    service = FileManagementApplicationService(paths, task_service=task_service, process_adapter=object())

    tasks = service.list_download_tasks("demo", limit=100)

    assert len(tasks) == 100
    assert tasks[0].task_id == "active-download"
    assert {task.task_id for task in tasks} >= {"active-download"}


def test_download_task_query_filters_in_sql_and_batches_events_with_large_unrelated_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, _source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    repository = task_service.repository("demo")
    other_rows = [
        (
            f"other-{index:04d}",
            "mesh_parse",
            "其他模块任务",
            "2026-07-15T00:00:00.000Z",
            TaskState.COMPLETED.value,
            "other_owner",
            "local",
            "demo",
            f"2026-07-15T00:{index // 60:02d}:{index % 60:02d}.000Z",
        )
        for index in range(5000)
    ]
    with repository._connect() as connection:
        connection.executemany(
            "INSERT INTO task_snapshots(task_id, task_type, task_name, created_time, status, owner, source, site_name, updated_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            other_rows,
        )
        connection.executemany(
            "INSERT INTO task_snapshots(task_id, task_type, task_name, created_time, status, owner, source, site_name, updated_time) "
            "VALUES (?, 'file_management_download', '文件下载', ?, ?, 'web_file_management', 'local', 'demo', ?)",
            [
                (
                    f"file-{index:03d}",
                    "2026-07-16T00:00:00.000Z",
                    TaskState.RUNNING.value if index < 2 else TaskState.COMPLETED.value,
                    f"2026-07-16T00:00:{index:02d}.000Z",
                )
                for index in range(50)
            ],
        )
        connection.commit()

    calls = 0
    original_batch = repository.list_events_for_tasks

    def counted_batch(task_ids, *, event_types=None):
        nonlocal calls
        calls += 1
        return original_batch(task_ids, event_types=event_types)

    monkeypatch.setattr(repository, "list_events", lambda *_args, **_kwargs: pytest.fail("不得逐任务读取事件"))
    monkeypatch.setattr(repository, "list_events_for_tasks", counted_batch)
    monkeypatch.setattr(task_service, "repository", lambda _site="demo": repository)
    service = FileManagementApplicationService(paths, task_service=task_service, process_adapter=object())
    monkeypatch.setattr(Path, "rglob", lambda *_args, **_kwargs: pytest.fail("状态/任务请求不得递归扫描目录"))

    assert service.status("demo").site_id == "demo"
    tasks = service.list_download_tasks("demo", limit=20)

    assert len(tasks) == 20
    assert {task.task_id for task in tasks} >= {"file-000", "file-001"}
    assert all(task.task_id.startswith("file-") for task in tasks)
    assert calls == 1
