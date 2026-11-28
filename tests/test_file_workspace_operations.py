from __future__ import annotations

import hashlib
import io
import socket
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.file_management_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.services.file_management_service import FileManagementApplicationService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.file_workspace_operations import FileWorkspaceOperations
from netconsole.services.site_manager import SiteManager
from netconsole.services.local_network_services.manager import LocalNetworkServiceManager, ServiceConfig


class Manager:
    def __init__(self, root):
        self.root = root
        self.status = "stopped"
        self.runtimes = {kind: SimpleNamespace(lock=threading.RLock()) for kind in ("tftp", "ftp", "http", "https")}
        for kind in self.runtimes:
            (root / kind).mkdir(parents=True)

    def snapshot(self, kind):
        return {"root": str(self.root / kind), "available": True, "status": self.status}


class Tasks:
    def __init__(self):
        self.created = []
        self.events = []

    def create_external_task(self, **kwargs):
        self.created.append(kwargs)

    def record_external_event(self, identifier, event, payload, **kwargs):
        self.events.append((identifier, event, dict(payload), kwargs))


@pytest.fixture
def workspace(tmp_path):
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data", runtime_root=tmp_path / "runtime")
    SiteManager(paths).create_site("file-test")
    history = Tasks()
    service = FileWorkspaceOperations(paths, history)
    manager = Manager(tmp_path / "shares")
    yield service, manager, history
    service.close()


def wait(service, task):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        current = next(row for row in service.list_tasks() if row["task_id"] == task["task_id"])
        if current["status"] not in {"WAITING", "RUNNING"}:
            return current
        time.sleep(0.01)
    raise AssertionError("file operation did not finish")


def test_copy_verify_move_delete_and_task_link(workspace):
    service, manager, history = workspace
    download_root = service.paths.file_downloads_root("file-test")
    download_root.mkdir(parents=True)
    (download_root / "startup.cfg").write_bytes(b"verified-config")
    source = service.browse(manager, "downloads")["items"][0]["id"]
    http = service.browse(manager, "http")
    copied = wait(service, service.submit(manager, "copy", source, http["directory_id"], "startup.cfg"))
    assert copied["status"] == "COMPLETED"
    assert copied["sha256"] == hashlib.sha256(b"verified-config").hexdigest()
    assert (manager.root / "http" / "startup.cfg").read_bytes() == b"verified-config"
    target = service.browse(manager, "http")["items"][0]["id"]
    renamed = wait(service, service.submit(manager, "rename", target, name="renamed.cfg"))
    assert renamed["status"] == "COMPLETED"
    target = service.browse(manager, "http")["items"][0]["id"]
    refused = wait(service, service.submit(manager, "delete", target, expected_sha256="0" * 64))
    assert refused["status"] == "FAILED"
    assert (manager.root / "http" / "renamed.cfg").exists()
    deleted = wait(service, service.submit(manager, "delete", target, expected_sha256=copied["sha256"]))
    assert deleted["status"] == "COMPLETED"
    assert not (manager.root / "http" / "renamed.cfg").exists()
    assert history.created[0]["task_id"] == copied["task_id"]
    assert any(event[0] == copied["task_id"] and event[1] == "finished" for event in history.events)


def test_desktop_directory_accepts_only_current_managed_directory_references(workspace):
    service, manager, _ = workspace
    root = manager.root / "http"
    (root / "archive").mkdir()
    (root / "status.txt").write_text("ready", encoding="utf-8")
    page = service.browse(manager, "http")
    archive, file = page["items"]
    assert service.desktop_directory(manager, archive["id"], "file-test") == root / "archive"
    with pytest.raises(ValueError, match="受管目录"):
        service.desktop_directory(manager, file["id"], "file-test")
    with pytest.raises(ValueError, match="当前局点"):
        service.desktop_directory(manager, archive["id"], "other-site")
    with pytest.raises(ValueError, match="当前局点"):
        service.desktop_directory(manager, "../archive", "file-test")


def test_text_preview_limits_reads_and_rejects_unmanaged_references(workspace):
    service, manager, _ = workspace
    root = manager.root / "http"
    (root / "sample.txt").write_text("a" * 65_537, encoding="utf-8")
    entry = service.browse(manager, "http")["items"][0]["id"]
    assert service.preview(manager, entry) == {
        "name": "sample.txt", "text": "a" * 65_536, "truncated": True,
    }
    with pytest.raises(ValueError):
        service.preview(manager, "../sample.txt")


def test_running_share_is_read_only_and_upload_staging_cleaned(workspace):
    service, manager, _ = workspace
    page = service.browse(manager, "tftp")
    manager.status = "running"
    assert not service.browse(manager, "tftp")["writable"]
    with pytest.raises(ValueError, match="停止"):
        service.upload(manager, page["directory_id"], "payload.bin", io.BytesIO(b"payload"))
    manager.status = "stopped"
    task = service.upload(manager, page["directory_id"], "payload.bin", io.BytesIO(b"payload"))
    assert wait(service, task)["status"] == "COMPLETED"
    assert (manager.root / "tftp" / "payload.bin").read_bytes() == b"payload"
    assert not list((service.paths.runtime_dir / "file-workspace-uploads").iterdir())


def test_overwrite_requires_checksum_and_cancel_preserves_files(workspace):
    service, manager, _ = workspace
    destination = service.browse(manager, "http")["directory_id"]
    first = wait(service, service.upload(manager, destination, "same.txt", io.BytesIO(b"old")))
    failed = wait(service, service.upload(manager, destination, "same.txt", io.BytesIO(b"new")))
    assert failed["status"] == "FAILED"
    assert (manager.root / "http" / "same.txt").read_bytes() == b"old"
    replaced = wait(service, service.upload(manager, destination, "same.txt", io.BytesIO(b"new"), True, first["sha256"]))
    assert replaced["status"] == "COMPLETED"
    assert (manager.root / "http" / "same.txt").read_bytes() == b"new"
    with manager.runtimes["http"].lock:
        queued = service.upload(manager, destination, "cancel.txt", io.BytesIO(b"cancel"))
        service.cancel(queued["task_id"])
    assert wait(service, queued)["status"] == "CANCELLED"
    assert not (manager.root / "http" / "cancel.txt").exists()


def test_invalid_name_cross_site_and_nonempty_directory_are_rejected(workspace):
    service, manager, _ = workspace
    root = service.browse(manager, "http")["directory_id"]
    bad = wait(service, service.submit(manager, "mkdir", destination=root, name="../outside"))
    assert bad["status"] == "FAILED"
    (manager.root / "http" / "nonempty").mkdir()
    (manager.root / "http" / "nonempty" / "keep").write_bytes(b"keep")
    folder = service.browse(manager, "http")["items"][0]["id"]
    task = wait(service, service.submit(manager, "delete", folder))
    assert task["status"] == "FAILED"
    assert (manager.root / "http" / "nonempty" / "keep").exists()
    with pytest.raises(ValueError, match="当前局点"):
        service._resolve(manager, folder, "other-site")


def test_browse_preserves_opaque_references_for_checksum_confirmation(workspace):
    service, manager, _ = workspace
    (manager.root / "http" / "same.cfg").write_bytes(b"config")
    first = service.browse(manager, "http")
    for _ in range(30):
        assert service.browse(manager, "http") == first
    assert len(service.refs) == 2


def test_copied_file_is_published_by_real_http_service(workspace, tmp_path):
    service, _, history = workspace
    manager = LocalNetworkServiceManager(tmp_path / "managed-services", adapters=lambda: {})
    try:
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        manager.configure("http", ServiceConfig(port=port))
        source_page = service.browse(manager, "downloads")
        downloads = service.paths.file_downloads_root("file-test")
        (downloads / "release.cfg").write_bytes(b"phase7-http-published")
        source = service.browse(manager, "downloads")["items"][0]["id"]
        target = service.browse(manager, "http")
        copied = wait(service, service.submit(manager, "copy", source, target["directory_id"], "release.cfg"))
        assert copied["status"] == "COMPLETED"
        assert manager.action("http", "start")["status"] == "running"
        with urlopen(f"http://127.0.0.1:{port}/release.cfg", timeout=3) as response:
            assert response.read() == b"phase7-http-published"
        published = service.browse(manager, "http")
        assert not published["writable"]
        denied = wait(service, service.submit(manager, "rename", published["items"][0]["id"], name="changed.cfg"))
        assert denied["status"] == "FAILED"
        assert "停止" in denied["error"]
        assert manager.action("http", "stop")["status"] == "stopped"
        moved = wait(service, service.submit(manager, "move", published["items"][0]["id"], source_page["directory_id"], "returned.cfg"))
        assert moved["status"] == "COMPLETED"
        assert (downloads / "returned.cfg").read_bytes() == b"phase7-http-published"
        assert any(event[0] == copied["task_id"] and event[1] == "finished" for event in history.events)
    finally:
        manager.close()


def test_workspace_api_upload_download_and_write_feature_gate(workspace):
    operations, manager, _ = workspace
    application_service = FileManagementApplicationService(operations.paths)
    app = FastAPI()
    app.state.file_management_service = application_service
    app.state.local_network_services = manager
    app.state.feature_gate = FeatureGate(operations.paths.app_root)
    gate = app.state.feature_gate.features["capability.file_management.local_write"]
    gate.update(visible=True, enabled=True, client_package=True)
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            base = "/api/file-management/workspace"
            page = client.get(f"{base}/entries", params={"kind": "http"}).json()
            result = client.post(f"{base}/upload", data={"destination": page["directory_id"]}, files={"file": ("api.cfg", b"api-payload")})
            assert result.status_code == 200
            completed = wait(application_service.workspace_operations, result.json())
            assert completed["status"] == "COMPLETED"
            page = client.get(f"{base}/entries", params={"kind": "http"}).json()
            downloaded = client.get(f"{base}/files/{page['items'][0]['id']}")
            assert downloaded.status_code == 200
            assert downloaded.content == b"api-payload"
            assert client.get(f"{base}/operations").json()["items"][0]["task_id"] == completed["task_id"]
            assert client.get(f"{base}/files/unknown").status_code == 409
            gate["enabled"] = False
            assert client.post(f"{base}/operations", json={"action": "mkdir", "destination": page["directory_id"], "name": "denied"}).status_code == 404
            assert not (manager.root / "http" / "denied").exists()
    finally:
        application_service.close()


def test_file_operation_history_persists_in_task_center(workspace):
    original, manager, _ = workspace
    center = TaskApplicationService(paths=original.paths, site_name="file-test")
    service = FileWorkspaceOperations(original.paths, center)
    try:
        destination = service.browse(manager, "http")["directory_id"]
        submitted = service.upload(manager, destination, "history.cfg", io.BytesIO(b"persisted"))
        assert wait(service, submitted)["status"] == "COMPLETED"
    finally:
        service.close()
    reopened = TaskApplicationService(paths=original.paths, site_name="file-test")
    snapshot = reopened.get_task(submitted["task_id"], site_name="file-test")
    assert snapshot.status.value == "COMPLETED"
    assert snapshot.result["sha256"] == hashlib.sha256(b"persisted").hexdigest()
    events = reopened.list_events(submitted["task_id"], site_name="file-test")
    assert any(row["type"] == "state" and row["payload"]["state"] == "RUNNING" for row in events)
