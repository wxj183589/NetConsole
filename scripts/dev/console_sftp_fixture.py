"""Loopback-only SSH/SFTP fixture for isolated Electron acceptance."""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

import paramiko

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import test_data_root_base
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.site_manager import SiteManager


class Authentication(paramiko.ServerInterface):
    def __init__(self, metrics=None):
        self.metrics = metrics

    def check_auth_password(self, username, password):
        if self.metrics is not None:
            self.metrics["authentications"] += 1
        return (
            paramiko.AUTH_SUCCESSFUL
            if (username, password) == ("operator", "fixture-only")
            else paramiko.AUTH_FAILED
        )

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return (
            paramiko.OPEN_SUCCEEDED
            if kind == "session"
            else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        )

    def check_channel_pty_request(self, *args):
        if self.metrics is not None:
            self.metrics["ptys"] += 1
        return True

    def check_channel_shell_request(self, channel):
        if self.metrics is not None:
            self.metrics["shells"] += 1

        def shell():
            try:
                channel.send(b"LAB-SFTP isolated server\r\n<LAB-SW> ")
                command = b""
                while data := channel.recv(65536):
                    channel.send(data)
                    command += data
                    while b"\r" in command:
                        line, command = command.split(b"\r", 1)
                        channel.send(
                            b"\r\nfixture interactive response: "
                            + line
                            + b"\r\n<LAB-SW> "
                        )
                        if b"watch" in line:

                            def ticker():
                                try:
                                    for index in range(20):
                                        __import__("time").sleep(0.2)
                                        channel.send(
                                            f"\r\nbackground-tick-{index}\r\n<LAB-SW> ".encode()
                                        )
                                except OSError:
                                    pass

                            threading.Thread(target=ticker, daemon=True).start()
            except (OSError, EOFError):
                pass

        threading.Thread(target=shell, daemon=True).start()
        return True


class Files(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, root, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.root = root.resolve()

    def path(self, value):
        target = (self.root / str(value).lstrip("/")).resolve()
        target.relative_to(self.root)
        return target

    @staticmethod
    def error(exc):
        return paramiko.SFTPServer.convert_errno(exc.errno or 1)

    def list_folder(self, path):
        try:
            values = []
            for child in self.path(path).iterdir():
                value = paramiko.SFTPAttributes.from_stat(child.lstat())
                value.filename = child.name
                values.append(value)
            return values
        except OSError as exc:
            return self.error(exc)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(self.path(path).stat())
        except OSError as exc:
            return self.error(exc)

    lstat = stat

    def open(self, path, flags, attr):
        try:
            handle = paramiko.SFTPHandle(flags)
            if str(path).endswith("large.bin"):
                original_read = handle.read

                def delayed_read(offset, length):
                    __import__("time").sleep(0.008)
                    return original_read(offset, length)

                handle.read = delayed_read
            descriptor = os.open(self.path(path), flags, 0o600)
            mode = "r+b" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb"
            stream = os.fdopen(descriptor, mode)
            if flags & (os.O_RDWR | os.O_WRONLY):
                handle.writefile = stream
            if not flags & os.O_WRONLY:
                handle.readfile = stream
            return handle
        except OSError as exc:
            return self.error(exc)

    def mkdir(self, path, attr):
        return self.mutate(lambda: self.path(path).mkdir())

    def remove(self, path):
        return self.mutate(lambda: self.path(path).unlink())

    def rmdir(self, path):
        return self.mutate(lambda: self.path(path).rmdir())

    def rename(self, source, target):
        return self.mutate(lambda: self.path(source).rename(self.path(target)))

    def mutate(self, operation):
        try:
            operation()
            return paramiko.SFTP_OK
        except OSError as exc:
            return self.error(exc)


def main():
    if os.environ.get("NETCONSOLE_RUNTIME_MODE") != "test":
        raise RuntimeError("SFTP fixture 只允许 TEST 模式")
    paths = PathResolver()
    allowed = test_data_root_base(repository_root=Path(__file__).resolve().parents[2])
    if not paths.data_root.resolve().is_relative_to(allowed.resolve()):
        raise RuntimeError("SFTP fixture 数据根不属于项目隔离测试目录")
    root = paths.runtime_dir / "fixture-server"
    (root / "日志目录").mkdir(parents=True)
    (root / "startup.cfg").write_bytes(b"isolated device configuration\n")
    (root / "日志目录" / "中文.log").write_text("隔离 SFTP 日志\n", encoding="utf-8")
    (root / ".hidden").write_bytes(b"hidden")
    with (root / "large.bin").open("wb") as stream:
        for _ in range(16):
            stream.write(b"x" * 1024 * 1024)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(10)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    SiteManager(paths).create_site("sftp-lab", display_name="SFTP 隔离验收")
    device = DeviceRepository(Database(paths.site_db_path("sftp-lab"))).create(
        Device(
            name="LAB-SFTP-SW",
            primary_address="127.0.0.1",
            ssh_enabled=1,
            ssh_port=port,
            ssh_username="operator",
            ssh_password="fixture-only",
            device_vendor="H3C",
            device_type="SW",
        )
    )
    stop = threading.Event()
    key = paramiko.RSAKey.generate(2048)
    transports = []
    metrics = {"connections": [], "authentications": 0, "shells": 0, "ptys": 0}
    metrics_path = root / "connections.json"

    def publish_metrics():
        while not stop.wait(0.1):
            temporary = metrics_path.with_suffix(".part")
            temporary.write_text(json.dumps(metrics), encoding="utf-8")
            temporary.replace(metrics_path)

    metrics_thread = threading.Thread(target=publish_metrics, daemon=True)
    metrics_thread.start()

    def accept():
        while not stop.is_set():
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            metrics["connections"].append(list(peer))
            transport = paramiko.Transport(connection)
            transport.add_server_key(key)
            transport.set_subsystem_handler(
                "sftp", paramiko.SFTPServer, Files, root=root
            )
            transport.start_server(server=Authentication(metrics))
            transports.append(transport)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    print(
        json.dumps(
            {
                "port": port,
                "device_uuid": device.device_uuid,
                "metrics_path": str(metrics_path),
            }
        ),
        flush=True,
    )
    input()
    stop.set()
    thread.join(timeout=2)
    metrics_thread.join(timeout=2)
    listener.close()
    for transport in transports:
        transport.close()
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")


if __name__ == "__main__":
    main()
