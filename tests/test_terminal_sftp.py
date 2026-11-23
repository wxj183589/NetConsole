from __future__ import annotations

import io
import os
import socket
import threading
import time
import stat
from types import SimpleNamespace
from pathlib import Path

import paramiko
import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.file_transfer_service import RemoteDeviceFile
from netconsole.services.file_transfer_service import (
    FileTransferService,
    TransferCancelled,
)
from netconsole.services.sftp_resume import download_checkpoint
from netconsole.services.sftp_tree import inventory
from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_sftp import TerminalSftpManager


class _FakeFileTransferService:
    instances: list["_FakeFileTransferService"] = []

    def __init__(self, *_args, allow_device_writes: bool = False, **_kwargs) -> None:
        self.allow_device_writes = allow_device_writes
        self.current_path = "/"
        self.closed = False
        self.uploads: list[tuple[bytes, str]] = []
        self.copies: list[tuple[str, str]] = []
        self.renames: list[tuple[str, str]] = []
        self.deletes: list[str] = []
        type(self).instances.append(self)

    def connect(self, _device: Device) -> str:
        return "/"

    def disconnect(self) -> None:
        self.closed = True

    def list_directory(self, path: str):
        self.current_path = path
        return [RemoteDeviceFile("config.cfg", "/config.cfg", 6, None, "config")]

    def mkdir(self, path: str) -> str:
        return path

    def stat(self, path: str):
        if path in {"/config.cfg", "/"}:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR if path == "/" else stat.S_IFREG, st_size=6
            )
        raise FileNotFoundError(path)

    def rename(self, source: str, target: str, *, overwrite: bool = False) -> str:
        self.renames.append((source, target))
        return target

    def delete_path(self, path: str, *, recursive: bool = False) -> None:
        self.deletes.append(path)

    def upload(self, source: Path, target: str, **kwargs) -> str:
        payload = source.read_bytes()
        self.uploads.append((payload, target))
        kwargs["progress_callback"](len(payload), len(payload))
        return target

    def download(self, source: str, target: Path, **kwargs) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"remote")
        kwargs["progress_callback"](6, 6)
        return target

    def copy(self, source: str, target: str, **kwargs) -> str:
        self.copies.append((source, target))
        kwargs["progress_callback"](6, 6)
        return target


class _SftpServer(paramiko.ServerInterface):
    def check_auth_password(self, username: str, password: str) -> int:
        return (
            paramiko.AUTH_SUCCESSFUL
            if (username, password) == ("operator", "secret")
            else paramiko.AUTH_FAILED
        )

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return (
            paramiko.OPEN_SUCCEEDED
            if kind == "session"
            else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        )


class _LocalSftpInterface(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, root: Path, **kwargs) -> None:
        super().__init__(server, *args, **kwargs)
        self.root = root.resolve()

    def _path(self, remote_path: str) -> Path:
        relative = str(remote_path or "/").replace("\\", "/").lstrip("/")
        candidate = (self.root / relative).resolve()
        candidate.relative_to(self.root)
        return candidate

    @staticmethod
    def _error(exc: OSError) -> int:
        return paramiko.SFTPServer.convert_errno(exc.errno or 1)

    def list_folder(self, path: str):
        try:
            result = []
            for child in self._path(path).iterdir():
                attrs = paramiko.SFTPAttributes.from_stat(child.stat())
                attrs.filename = child.name
                result.append(attrs)
            return result
        except OSError as exc:
            return self._error(exc)

    def stat(self, path: str):
        try:
            return paramiko.SFTPAttributes.from_stat(self._path(path).stat())
        except OSError as exc:
            return self._error(exc)

    lstat = stat

    def open(self, path: str, flags: int, attr):
        try:
            local_path = self._path(path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(local_path, flags, 0o666)
            if flags & os.O_RDWR:
                mode = "r+b"
            elif flags & os.O_WRONLY:
                mode = "wb"
            else:
                mode = "rb"
            handle = paramiko.SFTPHandle(flags)
            stream = os.fdopen(descriptor, mode)
            if flags & os.O_WRONLY or flags & os.O_RDWR:
                handle.writefile = stream
            if not flags & os.O_WRONLY:
                handle.readfile = stream
            return handle
        except OSError as exc:
            return self._error(exc)

    def mkdir(self, path: str, attr) -> int:
        try:
            self._path(path).mkdir()
            return paramiko.SFTP_OK
        except OSError as exc:
            return self._error(exc)

    def remove(self, path: str) -> int:
        try:
            self._path(path).unlink()
            return paramiko.SFTP_OK
        except OSError as exc:
            return self._error(exc)

    def rename(self, oldpath: str, newpath: str) -> int:
        try:
            self._path(oldpath).replace(self._path(newpath))
            return paramiko.SFTP_OK
        except OSError as exc:
            return self._error(exc)

    def rmdir(self, path: str) -> int:
        try:
            self._path(path).rmdir()
            return paramiko.SFTP_OK
        except OSError as exc:
            return self._error(exc)


def _start_sftp_server(root: Path) -> tuple[int, threading.Thread, list[BaseException]]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    errors: list[BaseException] = []

    def run() -> None:
        transport = None
        try:
            client, _address = listener.accept()
            transport = paramiko.Transport(client)
            transport.add_server_key(paramiko.RSAKey.generate(1024))
            transport.set_subsystem_handler(
                "sftp",
                paramiko.SFTPServer,
                _LocalSftpInterface,
                root=root,
            )
            transport.start_server(server=_SftpServer())
            channel = transport.accept(3)
            if channel is None:
                raise TimeoutError("SFTP client did not open a session channel")
            while transport.is_active():
                time.sleep(0.01)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if transport is not None:
                transport.close()
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, thread, errors


def _wait_task(manager: TerminalSftpManager, task_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        task = manager.task(task_id)
        if task["status"] not in {"WAITING", "QUEUED", "RUNNING"}:
            return task
        time.sleep(0.01)
    raise AssertionError("SFTP task did not finish")


def _manager(tmp_path: Path, monkeypatch) -> tuple[TerminalSftpManager, Device]:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("terminal-sftp", display_name="Terminal SFTP")
    device = DeviceRepository(Database(paths.site_db_path("terminal-sftp"))).create(
        Device(
            name="LAB-SW",
            primary_address="192.0.2.10",
            ssh_enabled=1,
            ssh_username="operator",
            ssh_password="secret",
        )
    )
    monkeypatch.setattr(
        "netconsole.services.terminal_sftp.FileTransferService",
        _FakeFileTransferService,
    )
    return TerminalSftpManager(paths), device


def test_terminal_sftp_uses_independent_write_enabled_subsystem(
    tmp_path: Path, monkeypatch
) -> None:
    _FakeFileTransferService.instances.clear()
    manager, device = _manager(tmp_path, monkeypatch)

    session = manager.connect(str(device.device_uuid))
    listed = manager.list_directory(session["session_id"], "/")

    assert listed["items"][0]["name"] == "config.cfg"
    assert _FakeFileTransferService.instances[0].allow_device_writes is True
    assert session["session_id"] != str(device.device_uuid)
    manager.close()


def test_terminal_sftp_upload_download_copy_and_path_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    _FakeFileTransferService.instances.clear()
    manager, device = _manager(tmp_path, monkeypatch)
    session = manager.connect(str(device.device_uuid))
    session_id = session["session_id"]

    staged, size = manager.stage_upload("local.cfg", io.BytesIO(b"local"))
    upload = manager.submit_upload(session_id, staged, "/local.cfg")
    assert _wait_task(manager, upload["task_id"])["status"] == "COMPLETED"

    copied = manager.submit_copy(session_id, "/config.cfg", "/config-copy.cfg")
    assert _wait_task(manager, copied["task_id"])["status"] == "COMPLETED"

    downloaded = manager.submit_download(session_id, "/config.cfg")
    completed = _wait_task(manager, downloaded["task_id"])
    assert completed["status"] == "READY"
    result, name = manager.download_result(completed["task_id"])

    assert size == 5
    assert _FakeFileTransferService.instances[0].uploads == [(b"local", "/local.cfg")]
    assert _FakeFileTransferService.instances[0].copies == [
        ("/config.cfg", "/config-copy.cfg")
    ]
    assert result.read_bytes() == b"remote"
    assert name == "config.cfg"

    try:
        manager.list_directory(session_id, "/../outside")
    except ValueError as error:
        assert "上级目录" in str(error)
    else:
        raise AssertionError("path traversal should be rejected")
    manager.close()


def test_terminal_sftp_uses_real_independent_paramiko_subsystem(tmp_path: Path) -> None:
    remote_root = tmp_path / "remote-sftp"
    remote_root.mkdir()
    (remote_root / "config.cfg").write_bytes(b"remote-config")
    port, server_thread, server_errors = _start_sftp_server(remote_root)

    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site(
        "terminal-sftp-real", display_name="Terminal SFTP Real"
    )
    device = DeviceRepository(
        Database(paths.site_db_path("terminal-sftp-real"))
    ).create(
        Device(
            name="LAB-SFTP",
            primary_address="127.0.0.1",
            ssh_enabled=1,
            ssh_port=port,
            ssh_username="operator",
            ssh_password="secret",
        )
    )
    manager = TerminalSftpManager(paths)
    try:
        session = manager.connect(str(device.device_uuid))
        session_id = session["session_id"]
        assert session["root_path"] == "/"
        assert [
            item["name"] for item in manager.list_directory(session_id, "/")["items"]
        ] == ["config.cfg"]

        staged, _size = manager.stage_upload("local.cfg", io.BytesIO(b"local-config"))
        upload = manager.submit_upload(session_id, staged, "/local.cfg")
        assert _wait_task(manager, upload["task_id"])["status"] == "COMPLETED"

        copied = manager.submit_copy(session_id, "/local.cfg", "/local-copy.cfg")
        assert _wait_task(manager, copied["task_id"])["status"] == "COMPLETED"

        downloaded = manager.submit_download(session_id, "/config.cfg")
        completed = _wait_task(manager, downloaded["task_id"])
        assert completed["status"] == "READY"
        result, name = manager.download_result(completed["task_id"])
        assert name == "config.cfg"
        assert result.read_bytes() == b"remote-config"
        assert (remote_root / "local.cfg").read_bytes() == b"local-config"
        assert (remote_root / "local-copy.cfg").read_bytes() == b"local-config"
    finally:
        manager.close()
        server_thread.join(timeout=3)

    assert not server_thread.is_alive()
    assert server_errors == []


def test_download_requires_verified_native_save_and_survives_restart(
    tmp_path, monkeypatch
):
    manager, device = _manager(tmp_path, monkeypatch)
    session = manager.connect(str(device.device_uuid))
    task = _wait_task(
        manager,
        manager.submit_download(session["session_id"], "/config.cfg")["task_id"],
    )
    assert task["status"] == "READY"
    with pytest.raises(ValueError, match="不一致"):
        manager.record_save(task["task_id"], saved=True, size=999, sha256="invalid")
    assert manager.record_save(task["task_id"], saved=False)["status"] == "FAILED"
    assert manager.download_result(task["task_id"])[0].read_bytes() == b"remote"
    paths = manager.paths
    manager.close()
    restored = TerminalSftpManager(paths)
    try:
        assert restored.task(task["task_id"])["status"] == "FAILED"
        assert restored.retry_task(task["task_id"])["status"] == "READY"
        saved = restored.record_save(
            task["task_id"],
            saved=True,
            size=task["result_size"],
            sha256=task["result_sha256"],
        )
        assert saved["status"] == "COMPLETED"
        assert restored.clear_completed() == 1
        assert restored.list_tasks() == []
    finally:
        restored.close()


def test_separate_sftp_sessions_and_background_instance_have_independent_lifetimes(
    tmp_path, monkeypatch
):
    manager, device = _manager(tmp_path, monkeypatch)
    first = manager.connect(str(device.device_uuid))
    second = manager.connect(str(device.device_uuid))
    a = manager._sessions[first["session_id"]].service
    b = manager._sessions[second["session_id"]].service
    from netconsole.services.sftp_connection import SftpConnectionService

    background = SftpConnectionService(manager.paths, _FakeFileTransferService).create(
        "terminal-sftp", relay_site_id="terminal-sftp", source="background"
    )
    background.connect(device)
    assert len({id(a), id(b), id(background)}) == 3
    assert not background.allow_device_writes
    manager.close_session(first["session_id"])
    assert a.closed and not b.closed and not background.closed
    assert manager.list_directory(second["session_id"], "/")["items"]
    background.disconnect()
    assert not b.closed
    manager.close()


def test_waiting_cancel_is_terminal_and_does_not_dispatch_bytes(tmp_path, monkeypatch):
    manager, device = _manager(tmp_path, monkeypatch)
    session = manager.connect(str(device.device_uuid))
    runtime = manager._sessions[session["session_id"]]
    with runtime.operation_lock:
        queued = manager.submit_download(session["session_id"], "/config.cfg")
        assert manager.task(queued["task_id"])["status"] == "WAITING"
        manager.cancel_task(queued["task_id"])
    assert _wait_task(manager, queued["task_id"])["status"] == "CANCELLED"
    assert not manager.task(queued["task_id"])["transferred_bytes"]
    manager.close()


def test_directory_recursive_real_sftp_upload_download_copy_delete(tmp_path):
    remote = tmp_path / "server"
    (remote / "目录" / "子目录").mkdir(parents=True)
    (remote / "目录" / "子目录" / "中文.cfg").write_bytes(b"nested-content")
    port, thread, errors = _start_sftp_server(remote)
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("tree")
    device = DeviceRepository(Database(paths.site_db_path("tree"))).create(
        Device(
            name="fixture",
            primary_address="127.0.0.1",
            ssh_enabled=1,
            ssh_port=port,
            ssh_username="operator",
            ssh_password="secret",
        )
    )
    manager = TerminalSftpManager(paths)
    try:
        session = manager.connect(str(device.device_uuid))
        task = _wait_task(
            manager, manager.submit_download(session["session_id"], "/目录")["task_id"]
        )
        assert task["status"] == "READY", task
        assert task["files_total"] == task["files_completed"] == 1
        from zipfile import ZipFile

        path, _ = manager.download_result(task["task_id"])
        with ZipFile(path) as archive:
            assert archive.read("目录/子目录/中文.cfg") == b"nested-content"
        staged, _ = manager.stage_upload("upload.cfg", io.BytesIO(b"upload"))
        upload = _wait_task(
            manager,
            manager.submit_upload(
                session["session_id"], staged, "/上传/嵌套/upload.cfg"
            )["task_id"],
        )
        assert upload["status"] == "COMPLETED", upload
        copied = _wait_task(
            manager,
            manager.submit_copy(session["session_id"], "/目录", "/副本")["task_id"],
        )
        assert copied["status"] == "COMPLETED", copied
        assert (
            remote / "副本" / "子目录" / "中文.cfg"
        ).read_bytes() == b"nested-content"
        manager.delete(session["session_id"], ["/副本"], recursive=True)
        assert not (remote / "副本").exists()
    finally:
        manager.close()
        thread.join(timeout=3)
    assert not thread.is_alive() and not errors


def test_real_sftp_download_checkpoint_verifies_prefix_before_resuming(tmp_path):
    remote = tmp_path / "server"
    remote.mkdir()
    payload = b"x" * (3 * 1024 * 1024 + 17)
    (remote / "large.bin").write_bytes(payload)
    port, thread, errors = _start_sftp_server(remote)
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    service = FileTransferService("fixture", paths)
    cancel = threading.Event()
    checkpoint = tmp_path / "checkpoint.part"
    target = tmp_path / "result.bin"
    try:
        service.connect(
            Device(
                name="fixture",
                primary_address="127.0.0.1",
                ssh_enabled=1,
                ssh_port=port,
                ssh_username="operator",
                ssh_password="secret",
            )
        )

        def pause(done, total):
            if done >= 1024 * 1024:
                cancel.set()

        with pytest.raises(TransferCancelled):
            download_checkpoint(
                service, "/large.bin", target, checkpoint, cancel, pause
            )
        assert checkpoint.stat().st_size == 1024 * 1024
        assert not target.exists()
        cancel.clear()
        # Same-size corruption cannot be hidden by matching mtime/length.
        with checkpoint.open("r+b") as stream:
            stream.write(b"!")
        with pytest.raises(ValueError, match="前缀"):
            download_checkpoint(
                service, "/large.bin", target, checkpoint, cancel, lambda *_: None
            )
        with checkpoint.open("r+b") as stream:
            stream.write(b"x")
        observed = []
        download_checkpoint(
            service,
            "/large.bin",
            target,
            checkpoint,
            cancel,
            lambda done, total: observed.append(done),
        )
        assert target.read_bytes() == payload
        assert observed[0] == 2 * 1024 * 1024
        assert not checkpoint.exists()
    finally:
        service.disconnect()
        thread.join(timeout=3)
    assert not thread.is_alive() and not errors


def test_recursive_manifest_rejects_limits_and_symlinks():
    cancel = threading.Event()

    class Tree:
        def lstat(self, _path):
            return SimpleNamespace(st_mode=stat.S_IFREG, st_size=100)

    with pytest.raises(ValueError, match="64 GiB"):
        inventory(Tree(), "/file", cancel, byte_limit=10)

    class Link:
        def lstat(self, _path):
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_size=0)

    with pytest.raises(ValueError, match="符号链接"):
        inventory(Link(), "/link", cancel)


def test_remote_commit_failure_restores_original_target():
    files = {"target": b"original", "partial": b"replacement"}

    class Server:
        def stat(self, path):
            if path not in files:
                raise FileNotFoundError(path)
            return SimpleNamespace(st_mode=stat.S_IFREG)

        def rename(self, source, target):
            if source == "partial":
                raise OSError("rename unsupported")
            files[target] = files.pop(source)

        def remove(self, path):
            files.pop(path)

    with pytest.raises(OSError):
        FileTransferService._publish_remote(
            Server(), "partial", "target", overwrite=True
        )
    assert files == {"target": b"original", "partial": b"replacement"}


def test_task_center_persists_transfer_and_cancel_signal_reaches_its_owner(
    tmp_path, monkeypatch
):
    original, device = _manager(tmp_path, monkeypatch)
    paths = original.paths
    original.close()
    from netconsole.services.job_center.task_application_service import (
        TaskApplicationService,
    )
    from netconsole.services.job_center.query_service import JobCenterQueryService
    from netconsole.models.task_state import TaskState

    service = TaskApplicationService(
        paths, site_name="terminal-sftp", reconcile_on_start=False
    )
    manager = TerminalSftpManager(paths, service)
    try:
        session = manager.connect(str(device.device_uuid))
        runtime = manager._sessions[session["session_id"]]
        with runtime.operation_lock:
            queued = manager.submit_download(session["session_id"], "/config.cfg")
            assert (
                service.repository("terminal-sftp").get(queued["task_id"]).status
                == TaskState.PENDING
            )
            assert service.cancel_task(queued["task_id"], site_name="terminal-sftp")
        assert _wait_task(manager, queued["task_id"])["status"] == "CANCELLED"
        deadline = time.monotonic() + 2
        while (
            service.repository("terminal-sftp").get(queued["task_id"]).status
            != TaskState.CANCELLED
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert (
            service.repository("terminal-sftp").get(queued["task_id"]).status
            == TaskState.CANCELLED
        )
        assert (
            JobCenterQueryService._module("terminal_sftp", "terminal_sftp_transfer")
            == "files"
        )
    finally:
        manager.close()


def test_clear_history_keeps_checkpoint_owned_by_retry(tmp_path, monkeypatch):
    manager, device = _manager(tmp_path, monkeypatch)
    try:
        session = manager.connect(str(device.device_uuid))
        runtime = manager._sessions[session["session_id"]]
        with runtime.operation_lock:
            previous = manager.submit_download(session["session_id"], "/config.cfg")
            manager.cancel_task(previous["task_id"])
        assert _wait_task(manager, previous["task_id"])["status"] == "CANCELLED"
        with runtime.operation_lock:
            retry = manager.retry_task(previous["task_id"])
            checkpoint_root = manager.download_root / previous["task_id"]
            checkpoint_root.mkdir(parents=True, exist_ok=True)
            retained = checkpoint_root / "checkpoint.part"
            retained.write_bytes(b"checkpoint")
            assert manager.clear_completed() == 1
            assert retained.read_bytes() == b"checkpoint"
            manager.cancel_task(retry["task_id"])
        assert _wait_task(manager, retry["task_id"])["status"] == "CANCELLED"
        deadline = time.monotonic() + 2
        while checkpoint_root.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not checkpoint_root.exists()
    finally:
        manager.close()


def test_save_after_task_center_recovery_creates_separate_attempt(
    tmp_path, monkeypatch
):
    original, device = _manager(tmp_path, monkeypatch)
    paths = original.paths
    original.close()
    from netconsole.services.job_center.task_application_service import (
        TaskApplicationService,
    )
    from netconsole.models.task_state import TaskState

    service = TaskApplicationService(
        paths, site_name="terminal-sftp", reconcile_on_start=False
    )
    manager = TerminalSftpManager(paths, service)
    try:
        session = manager.connect(str(device.device_uuid))
        task = _wait_task(
            manager,
            manager.submit_download(session["session_id"], "/config.cfg")["task_id"],
        )
        service.record_external_event(
            task["task_id"],
            "error",
            {"error": "previous runtime lost"},
            site_name="terminal-sftp",
        )
        saved = manager.record_save(
            task["task_id"],
            saved=True,
            size=task["result_size"],
            sha256=task["result_sha256"],
        )
        assert saved["status"] == "COMPLETED"
        attempt_id = manager._tasks[task["task_id"]].params["task_center_id"]
        assert attempt_id != task["task_id"]
        assert (
            service.repository("terminal-sftp").get(task["task_id"]).status
            == TaskState.FAILED
        )
        attempt = service.repository("terminal-sftp").get(attempt_id)
        assert attempt.status == TaskState.COMPLETED
        assert attempt.retry_of_task_id == task["task_id"]
        manager.record_save(
            task["task_id"],
            saved=True,
            size=task["result_size"],
            sha256=task["result_sha256"],
        )
        assert manager._tasks[task["task_id"]].params["task_center_id"] == attempt_id
        output, _ = manager.download_result(task["task_id"])
        manager.clear_completed()
        assert not output.exists()
    finally:
        manager.close()


def test_remote_hash_rejects_same_size_corruption():
    import hashlib

    class Server:
        def open(self, _path, _mode):
            return io.BytesIO(b"bad")

    from netconsole.services.file_transfer_service import TransferVerificationFailed

    with pytest.raises(TransferVerificationFailed, match="SHA-256"):
        FileTransferService._verify_remote_hash(
            Server(), "/staging", hashlib.sha256(b"new").hexdigest()
        )


def test_broken_journal_does_not_block_shutdown_or_overwrite_evidence(
    tmp_path, monkeypatch
):
    original, _ = _manager(tmp_path, monkeypatch)
    paths, journal = original.paths, original.journal_path
    original.close()
    journal.write_text("broken journal", encoding="utf-8")
    restored = TerminalSftpManager(paths)
    with pytest.raises(ValueError, match="日志损坏"):
        restored.list_tasks()
    restored.close()
    assert journal.read_text(encoding="utf-8") == "broken journal"


def test_failed_connection_retry_replaces_closed_session(tmp_path, monkeypatch):
    manager, device = _manager(tmp_path, monkeypatch)
    try:
        session = manager.connect(str(device.device_uuid))
        runtime = manager._sessions[session["session_id"]]
        runtime.service.is_connected = lambda: False
        task = _wait_task(
            manager,
            manager.submit_download(session["session_id"], "/config.cfg")["task_id"],
        )
        runtime.service.disconnect()
        # Simulate network failure before a result became available.
        pending = manager._tasks[task["task_id"]]
        pending.snapshot.status, pending.snapshot.result_name = "FAILED", ""
        retry = manager.retry_task(task["task_id"])
        assert retry["session_id"] != session["session_id"]
        assert runtime.snapshot.state == "CLOSED"
        assert _wait_task(manager, retry["task_id"])["status"] == "READY"
    finally:
        manager.close()


@pytest.mark.parametrize("stage", ["WAITING", "READY"])
def test_task_center_http_cancel_reaches_transfer_owner(tmp_path, monkeypatch, stage):
    from contextlib import nullcontext
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from netconsole.backend.api.job_center_router import router
    from netconsole.services.job_center.query_service import JobCenterQueryService
    from netconsole.services.job_center.task_application_service import (
        TaskApplicationService,
    )

    original, device = _manager(tmp_path, monkeypatch)
    paths = original.paths
    original.close()
    service = TaskApplicationService(
        paths, site_name="terminal-sftp", reconcile_on_start=False
    )
    manager = TerminalSftpManager(paths, service)
    app = FastAPI()
    app.state.job_center_query_service = JobCenterQueryService(paths)
    app.state.task_service = service
    app.state.terminal_sftp_manager = manager
    app.include_router(router, prefix="/api")
    try:
        session = manager.connect(str(device.device_uuid))
        runtime = manager._sessions[session["session_id"]]
        with runtime.operation_lock if stage == "WAITING" else nullcontext():
            task = manager.submit_download(session["session_id"], "/config.cfg")
            if stage == "READY":
                assert _wait_task(manager, task["task_id"])["status"] == "READY"
                output, _ = manager.download_result(task["task_id"])
            with TestClient(app) as client:
                response = client.post(
                    f"/api/job-center/tasks/{task['task_id']}/cancel"
                )
            assert response.status_code == 200, response.text
            assert response.json()["status"] in {"STOPPING", "CANCELLED"}
        assert _wait_task(manager, task["task_id"])["status"] == "CANCELLED"
        if stage == "READY":
            assert not output.exists()
            with pytest.raises(ValueError):
                manager.download_result(task["task_id"])
    finally:
        manager.close()


def test_console_transfer_history_does_not_duplicate_global_jobs(tmp_path, monkeypatch):
    original, device = _manager(tmp_path, monkeypatch)
    paths = original.paths
    original.close()
    from netconsole.services.job_center.task_application_service import (
        TaskApplicationService,
    )
    from netconsole.services.job_center.query_service import JobCenterQueryService

    service = TaskApplicationService(
        paths, site_name="terminal-sftp", reconcile_on_start=False
    )
    manager = TerminalSftpManager(paths, service)
    try:
        session = manager.connect(device.device_uuid)
        task = _wait_task(
            manager,
            manager.submit_download(session["session_id"], "/config.cfg")["task_id"],
        )
        query = JobCenterQueryService(paths)
        assert all(
            item.id != task["task_id"] for item in query.list_tasks("terminal-sftp")
        )
        assert query.get_task("terminal-sftp", task["task_id"]) is not None
        assert manager.task(task["task_id"])["status"] == "READY"
    finally:
        manager.close()
