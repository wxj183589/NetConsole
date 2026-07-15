from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.file_management_router import router
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.file_transfer_service import FileTransferService, RemoteDeviceFile, file_sha256, normalize_remote_path
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    FileReferenceNotFound,
    run_file_management_download,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_registry import dispatch_job
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _fixture(tmp_path: Path) -> tuple[PathResolver, Path]:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    source = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "MR-01" / "sessions" / "s1" / "raw" / "collector.log"
    source.parent.mkdir(parents=True)
    source.write_text("sample", encoding="utf-8")
    (source.parent.parent / "outputs").mkdir()
    (source.parent.parent / "outputs" / "report.xlsx").write_bytes(b"report")
    return paths, source


def _app(service: FileManagementApplicationService) -> FastAPI:
    app = FastAPI()
    app.state.paths = service.paths
    app.state.file_management_service = service
    app.state.feature_gate = FeatureGate(service.paths.app_root)
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
        assert str(tmp_path) not in downloaded.headers.get("content-disposition", "")
        assert before_download == after_download
        assert client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"file_ref": "../outside"}).status_code == 422


def test_remote_file_web_flow_uses_session_entries_task_artifact_and_rejects_cross_device_reuse(tmp_path: Path, monkeypatch) -> None:
    paths, _source = _fixture(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    device_a = repository.create(Device(name="MR-A", device_type="MR", primary_address="192.0.2.10"))
    device_b = repository.create(Device(name="MR-B", device_type="MR", primary_address="192.0.2.11"))

    class FakeTransfer:
        payloads = {"flash:/diagfile/diag_a.tar.gz": b"remote artifact"}

        def __init__(self, site_name, fake_paths):
            self.site_name = site_name
            self.paths = fake_paths
            self.connected = False
            self.root_path = "flash:/"

        def connect(self, _device):
            self.connected = True
            return self.root_path

        def disconnect(self):
            self.connected = False

        def list_directory(self, path):
            current = normalize_remote_path(path, root_path=self.root_path)
            if current == "flash:/":
                return [RemoteDeviceFile("diagfile", "flash:/diagfile", None, None, "dir", is_dir=True, file_type="directory")]
            return [RemoteDeviceFile("diag_a.tar.gz", "flash:/diagfile/diag_a.tar.gz", 15, "2026-07-15 10:00:00", "diag")]

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
        def start_job(self, job: BackgroundJob) -> str:
            captured.append(job)
            task_service.prepare(job)
            return job.job_id

    service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=FakeProcessAdapter(),
        transfer_factory=FakeTransfer,
    )
    with TestClient(_app(service)) as client:
        connected = client.post("/api/file-management/connections", params={"site_id": "demo"}, json={"device_id": device_a.device_uuid})
        assert connected.status_code == 201
        connection_id = connected.json()["connection_id"]
        assert "flash:/" not in connected.text

        root = client.get(f"/api/file-management/connections/{connection_id}/entries", params={"site_id": "demo"})
        assert root.status_code == 200
        directory_id = root.json()["items"][0]["entry_id"]
        nested = client.get(
            f"/api/file-management/connections/{connection_id}/entries",
            params={"site_id": "demo", "entry_id": directory_id},
        )
        assert nested.status_code == 200
        remote_entry_id = nested.json()["items"][0]["entry_id"]

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
        result = run_file_management_download(JobContext.from_job(captured[-1]))
        assert result["sha256"] == file_sha256(paths.site_dir("demo") / result["relative_path"])
        task_service.record_external_event(task_id, "finished", {"result": result}, site_name="demo")
        queue = client.get("/api/file-management/downloads", params={"site_id": "demo"})
        assert queue.status_code == 200
        assert queue.json()[0]["result"]["artifact_id"].startswith("fa1_")
        artifact = client.get(f"/api/file-management/downloads/{task_id}/file", params={"site_id": "demo"})
        assert artifact.status_code == 200
        assert artifact.content == b"remote artifact"
        pending = client.post(
            "/api/file-management/downloads",
            params={"site_id": "demo"},
            json={"connection_id": connection_id, "remote_entry_id": remote_entry_id},
        )
        assert pending.status_code == 202
        pending_cancel = client.post(f"/api/file-management/downloads/{pending.json()['task_id']}/cancel", params={"site_id": "demo"})
        assert pending_cancel.status_code == 200
        cancelled = client.post(f"/api/file-management/downloads/{task_id}/cancel", params={"site_id": "demo"})
        assert cancelled.status_code == 422
        assert client.post("/api/file-management/desktop-actions/winscp", json={"device_id": device_a.device_uuid}).json()["integration_required"]
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
