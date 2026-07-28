import sys
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.file_transfer_service import (
    FileTransferConnectionError,
    FileTransferService,
    RemoteDeviceFile,
    SftpUnavailableError,
)


def test_file_transfer_reports_sftp_unavailable_without_running_device_write_commands(
    tmp_path, monkeypatch
):
    import netconsole.services.file_transfer_service as service_module

    connect_hosts: list[str] = []
    shell_commands: list[str] = []
    closed: list[str] = []

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def recv_ready(self):
            return False

        def close(self):
            closed.append("shell")

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            closed.append("sftp")

    class FakeSSHClient:
        open_count = 0

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            connect_hosts.append(str(kwargs["hostname"]))
            if kwargs["hostname"] != "127.0.0.1":
                raise RuntimeError("direct failed")

        def open_sftp(self):
            FakeSSHClient.open_count += 1
            raise RuntimeError("sftp disabled")

        def invoke_shell(self):
            return FakeShell()

        def close(self):
            closed.append("client")

    class FakeTunnelSession:
        local_host = "127.0.0.1"
        local_port = 10022

        def close(self):
            closed.append("tunnel")

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()),
    )
    monkeypatch.setattr(
        service_module.TunnelManager, "open_tunnel", lambda *_args: FakeTunnelSession()
    )
    monkeypatch.setattr(service_module, "sleep", lambda _seconds: None)

    device = Device(
        id=1,
        name="MR",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(SftpUnavailableError, match="未启用 SFTP"):
        service.connect(device)
    assert shell_commands == []


def test_file_transfer_does_not_invoke_shell_when_another_sftp_target_is_available(
    tmp_path, monkeypatch
):
    connect_hosts: list[str] = []
    shell_commands: list[str] = []

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def close(self):
            pass

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            pass

    class FakeSSHClient:
        def __init__(self):
            self.hostname = ""

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            self.hostname = str(kwargs["hostname"])
            connect_hosts.append(self.hostname)

        def open_sftp(self):
            if self.hostname == "10.0.0.1":
                raise RuntimeError("sftp subsystem disabled")
            return FakeSftp()

        def invoke_shell(self):
            return FakeShell()

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()),
    )

    device = Device(
        id=1,
        name="Cisco-SW",
        device_vendor="Cisco",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="ops",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    root = service.connect(device)
    assert service.successful_target is not None
    assert service.successful_target.host == "10.0.1.1"
    service.disconnect()

    assert root == "flash:/"
    assert connect_hosts == ["10.0.0.1", "10.0.1.1"]
    assert shell_commands == []


def test_file_transfer_reports_sftp_unavailable_without_invoking_shell(
    tmp_path, monkeypatch
):
    import netconsole.services.file_transfer_service as service_module

    connect_hosts: list[str] = []
    shell_commands: list[str] = []
    closed: list[str] = []
    invoked_on_clients: list[int] = []
    client_index = 0

    class FakeTransport:
        def __init__(self, active: bool):
            self.active = active

        def is_active(self):
            return self.active

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def recv_ready(self):
            return False

        def close(self):
            closed.append("shell")

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            closed.append("sftp")

    class FakeSSHClient:
        def __init__(self):
            nonlocal client_index
            client_index += 1
            self.index = client_index

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            connect_hosts.append(str(kwargs["hostname"]))

        def get_transport(self):
            return FakeTransport(True)

        def open_sftp(self):
            raise RuntimeError("sftp subsystem disabled")

        def invoke_shell(self):
            invoked_on_clients.append(self.index)
            return FakeShell()

        def close(self):
            closed.append(f"client-{self.index}")

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()),
    )
    monkeypatch.setattr(service_module, "sleep", lambda _seconds: None)

    device = Device(
        id=1,
        name="H3C-SW",
        device_vendor="H3C",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(SftpUnavailableError, match="未启用 SFTP"):
        service.connect(device)

    assert connect_hosts == ["10.0.0.1"]
    assert invoked_on_clients == []
    assert shell_commands == []


def test_open_sftp_channel_closed_is_sftp_unavailable_only_when_transport_active(
    tmp_path, monkeypatch
):
    class FakeSSHException(Exception):
        pass

    class FakeTransport:
        def __init__(self, active: bool):
            self.active = active

        def is_active(self):
            return self.active

    class FakeSSHClient:
        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            pass

        def get_transport(self):
            return FakeTransport(True)

        def open_sftp(self):
            raise FakeSSHException("Channel closed.")

        def invoke_shell(self):
            raise AssertionError("open_sftp failure must not open an interactive shell")

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(
            SSHClient=FakeSSHClient,
            SSHException=FakeSSHException,
            AutoAddPolicy=lambda: object(),
        ),
    )
    device = Device(
        id=1,
        name="H3C-SW",
        device_vendor="H3C",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(SftpUnavailableError, match="未启用 SFTP"):
        service.connect(device)


def test_open_sftp_channel_closed_with_inactive_transport_is_sftp_unavailable(
    tmp_path, monkeypatch
):
    class FakeSSHException(Exception):
        pass

    class FakeSSHClient:
        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            pass

        def get_transport(self):
            return SimpleNamespace(is_active=lambda: False)

        def open_sftp(self):
            raise FakeSSHException("Channel closed.")

        def invoke_shell(self):
            raise AssertionError("inactive transport must not open an interactive shell")

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(
            SSHClient=FakeSSHClient,
            SSHException=FakeSSHException,
            AutoAddPolicy=lambda: object(),
        ),
    )
    device = Device(
        id=1,
        name="H3C-SW",
        device_vendor="H3C",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(SftpUnavailableError, match="未启用 SFTP"):
        service.connect(device)


def test_file_transfer_keeps_transport_errors_separate_without_invoking_shell(
    tmp_path, monkeypatch
):
    class FakeSSHClient:
        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            pass

        def get_transport(self):
            return SimpleNamespace(is_active=lambda: True)

        def open_sftp(self):
            raise RuntimeError("SSH session not active")

        def invoke_shell(self):
            raise AssertionError("unsupported vendor should not run shell commands")

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()),
    )
    device = Device(
        id=1,
        name="Huawei-SW",
        device_vendor="Huawei",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(FileTransferConnectionError) as excinfo:
        service.connect(device)

    assert excinfo.value.code == "DEVICE_FILE_SFTP_NEGOTIATION_FAILED"
    assert "SSH session not active" not in str(excinfo.value)


def test_file_transfer_service_rejects_remote_write_operations_in_read_only_mode(
    tmp_path,
):
    calls: list[tuple[str, str]] = []

    class FakeSftp:
        def mkdir(self, path):
            calls.append(("mkdir", path))

        def remove(self, path):
            calls.append(("remove", path))

        def rmdir(self, path):
            calls.append(("rmdir", path))

    service = FileTransferService("demo", PathResolver(tmp_path))
    service._sftp = FakeSftp()
    service._root_path = "flash:/"
    service._current_path = "flash:/diagfile"

    with pytest.raises(PermissionError, match="只读模式"):
        service.mkdir("logs")
    with pytest.raises(PermissionError, match="只读模式"):
        service.delete(RemoteDeviceFile("a.log", "a.log", 1, "", "log"))
    with pytest.raises(PermissionError, match="只读模式"):
        service.delete(RemoteDeviceFile("old", "old", None, "", "dir", is_dir=True))

    assert calls == []


class FakeRepository:
    def __init__(self) -> None:
        self.device = Device(
            id=1,
            device_uuid=Device.new_uuid(),
            name="AC-1",
            ip_address="192.0.2.1",
            device_type="AC",
        )

    def list(self):
        return [self.device]

    def get(self, device_id):
        assert int(device_id) == 1
        return self.device


class FakeConnectedSftpService:
    root_path = "flash:/"
    current_path = "flash:/"

    def is_connected(self):
        return True

    def disconnect(self):
        return None
