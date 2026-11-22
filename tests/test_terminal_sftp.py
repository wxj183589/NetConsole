from __future__ import annotations

import io
import os
import socket
import threading
import time
from pathlib import Path

import paramiko

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.file_transfer_service import RemoteDeviceFile
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
        if task["status"] not in {"QUEUED", "RUNNING"}:
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


def test_terminal_sftp_uses_independent_write_enabled_subsystem(tmp_path: Path, monkeypatch) -> None:
    _FakeFileTransferService.instances.clear()
    manager, device = _manager(tmp_path, monkeypatch)

    session = manager.connect(str(device.device_uuid))
    listed = manager.list_directory(session["session_id"], "/")

    assert listed["items"][0]["name"] == "config.cfg"
    assert _FakeFileTransferService.instances[0].allow_device_writes is True
    assert session["session_id"] != str(device.device_uuid)
    manager.close()


def test_terminal_sftp_upload_download_copy_and_path_boundary(tmp_path: Path, monkeypatch) -> None:
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
    result, name = manager.download_result(completed["task_id"])

    assert size == 5
    assert _FakeFileTransferService.instances[0].uploads == [(b"local", "/local.cfg")]
    assert _FakeFileTransferService.instances[0].copies == [("/config.cfg", "/config-copy.cfg")]
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
    SiteManager(paths).create_site("terminal-sftp-real", display_name="Terminal SFTP Real")
    device = DeviceRepository(Database(paths.site_db_path("terminal-sftp-real"))).create(
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
        assert [item["name"] for item in manager.list_directory(session_id, "/")["items"]] == [
            "config.cfg"
        ]

        staged, _size = manager.stage_upload("local.cfg", io.BytesIO(b"local-config"))
        upload = manager.submit_upload(session_id, staged, "/local.cfg")
        assert _wait_task(manager, upload["task_id"])["status"] == "COMPLETED"

        copied = manager.submit_copy(session_id, "/local.cfg", "/local-copy.cfg")
        assert _wait_task(manager, copied["task_id"])["status"] == "COMPLETED"

        downloaded = manager.submit_download(session_id, "/config.cfg")
        completed = _wait_task(manager, downloaded["task_id"])
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
