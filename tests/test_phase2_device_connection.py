from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.connection_manager import ConnectionManager
from netconsole.services.device_import_export import DeviceImportExportService
from netconsole.services.file_transfer_service import build_h3c_sftp_enable_commands
from netconsole.services import netmiko_connection
from netconsole.services.netmiko_connection import build_netmiko_params, connection_targets, prepared_connection_target, test_device_connection
from netconsole.services.ssh_tunnel import TunnelManager


def _repository(tmp_path: Path) -> DeviceRepository:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return DeviceRepository(database)


def test_device_repository_uses_primary_backup_and_system_name(tmp_path):
    repository = _repository(tmp_path)

    device = repository.create(
        Device(
            name="SW1",
            system_name="SW1-SYS",
            primary_address="10.0.0.1",
            backup_address="10.0.1.1",
            ssh_username="admin",
            ssh_password="pwd",
        )
    )

    saved = repository.get(int(device.id))
    assert saved.primary_address == "10.0.0.1"
    assert saved.backup_address == "10.0.1.1"
    assert saved.system_name == "SW1-SYS"
    with repository.database.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
    assert "ip_address" not in columns
    assert "sysname" not in columns


def test_old_template_address_fields_are_rejected(tmp_path):
    repository = _repository(tmp_path)
    service = DeviceImportExportService(repository)
    path = tmp_path / "old.csv"
    path.write_text("设备名称,IP,用户名,密码\nSW1,10.0.0.1,admin,pwd\n", encoding="utf-8-sig")

    with pytest.raises(ValueError, match="最新模板"):
        service.import_csv(path)
    assert repository.list() == []


def test_connection_manager_orders_primary_backup_then_complete_tunnels():
    device = Device(
        name="SW1",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_port=2222,
        ssh_username="admin",
        ssh_password="pwd",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
        tunnel1_password="jump_pwd",
        tunnel2_enabled=1,
        tunnel2_host="",
        tunnel2_username="jump",
    )

    attempts = ConnectionManager().iter_attempts(device)

    assert [attempt.label for attempt in attempts] == ["primary_direct", "backup_direct", "tunnel1"]
    assert attempts[0].host == "10.0.0.1"
    assert attempts[1].host == "10.0.1.1"
    assert attempts[0].username == "admin"
    assert attempts[0].port == 2222
    assert attempts[2].via_tunnel is True
    assert attempts[2].tunnel and attempts[2].tunnel.host == "jump1"


def test_connection_manager_uses_tunnel_host_when_global_tunnel_disabled():
    device = Device(
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        tunnel_enabled=0,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )

    attempts = ConnectionManager().iter_attempts(device)

    assert [attempt.label for attempt in attempts] == ["primary_direct", "backup_direct", "tunnel1"]
    assert [attempt.via_tunnel for attempt in attempts] == [False, False, True]


def test_connection_manager_includes_two_complete_tunnels_when_enabled():
    device = Device(
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
        tunnel2_enabled=1,
        tunnel2_host="jump2",
        tunnel2_username="jump",
    )

    attempts = ConnectionManager().iter_attempts(device)

    assert [attempt.label for attempt in attempts] == ["primary_direct", "backup_direct", "tunnel1", "tunnel2"]
    assert [attempt.via_tunnel for attempt in attempts] == [False, False, True, True]


def test_connection_manager_ignores_persisted_tunnel_local_ports():
    device = Device(
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
        tunnel1_local_port=10022,
        tunnel2_enabled=1,
        tunnel2_host="jump2",
        tunnel2_username="jump",
        tunnel2_local_port=10023,
    )

    tunnels = [attempt.tunnel for attempt in ConnectionManager().iter_attempts(device) if attempt.via_tunnel]

    assert [tunnel.local_port for tunnel in tunnels if tunnel is not None] == [None, None]


def test_connection_manager_prefers_ui_ssh_telnet_fields_over_compat_protocol_port():
    ssh_device = Device(
        primary_address="10.0.0.1",
        protocol="Telnet",
        port=23,
        ssh_enabled=1,
        ssh_port=2022,
        telnet_enabled=1,
        telnet_port=2323,
        ssh_username="ssh",
        telnet_username="telnet",
    )
    telnet_device = Device(
        primary_address="10.0.0.2",
        protocol="SSH",
        port=22,
        ssh_enabled=0,
        telnet_enabled=1,
        telnet_port=2323,
        telnet_username="telnet",
    )

    ssh_attempt = ConnectionManager().iter_attempts(ssh_device)[0]
    telnet_attempt = ConnectionManager().iter_attempts(telnet_device)[0]

    assert ssh_attempt.protocol == "SSH"
    assert ssh_attempt.port == 2022
    assert ssh_attempt.username == "ssh"
    assert telnet_attempt.protocol == "Telnet"
    assert telnet_attempt.port == 2323


def test_tunnel_target_prepares_local_netmiko_endpoint(monkeypatch):
    device = Device(
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_port=22,
        ssh_username="admin",
        ssh_password="device-pwd",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_port=22,
        tunnel1_username="jump",
        tunnel1_password="jump-pwd",
    )
    target = [item for item in connection_targets(device) if item.via_tunnel][0]
    closed = []

    class FakeSession:
        local_host = "127.0.0.1"
        local_port = 10022

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        "netconsole.services.netmiko_connection.TunnelManager.open_tunnel",
        lambda _self, tunnel, host, port: FakeSession(),
    )

    with prepared_connection_target(target) as prepared:
        params = build_netmiko_params(prepared)

    assert params["host"] == "127.0.0.1"
    assert params["port"] == 10022
    assert closed == [True]


def test_tunnel_manager_binds_auto_local_port_and_closes(monkeypatch):
    bound: list[tuple[str, int]] = []
    closed: list[str] = []

    class FakeClient:
        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            pass

        def get_transport(self):
            return object()

        def close(self):
            closed.append("client")

    class FakeServer:
        daemon_threads = False

        def __init__(self, address, _handler):
            bound.append(address)
            self.server_address = ("127.0.0.1", 34567)

        def serve_forever(self):
            pass

        def shutdown(self):
            closed.append("shutdown")

        def server_close(self):
            closed.append("server")

    monkeypatch.setitem(sys.modules, "paramiko", SimpleNamespace(SSHClient=FakeClient, AutoAddPolicy=lambda: object()))
    monkeypatch.setattr("netconsole.services.ssh_tunnel.socketserver.ThreadingTCPServer", FakeServer)

    profile = ConnectionManager().iter_attempts(
        Device(
            primary_address="10.0.0.1",
            ssh_enabled=1,
            ssh_username="admin",
            tunnel_enabled=1,
            tunnel1_enabled=1,
            tunnel1_host="jump",
            tunnel1_username="jump",
            tunnel1_local_port=10022,
        )
    )[-1].tunnel

    session = TunnelManager().open_tunnel(profile, "10.0.0.1", 22)
    session.close()

    assert bound == [("127.0.0.1", 0)]
    assert session.local_port == 34567
    assert {"shutdown", "server", "client"}.issubset(set(closed))


def test_test_device_connection_stops_after_primary_direct_success(monkeypatch):
    device = Device(
        name="MR",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="pwd",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )
    calls: list[str] = []

    class FakeConnection:
        def find_prompt(self):
            return "<MR>"

        def send_command(self, *_args, **_kwargs):
            return "clock"

        def disconnect(self):
            pass

    def fake_connect(**params):
        calls.append(str(params["host"]))
        return FakeConnection()

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect)
    monkeypatch.setattr("netconsole.services.netmiko_connection.TunnelManager.open_tunnel", lambda *_args: (_ for _ in ()).throw(AssertionError("tunnel should not open")))

    result = test_device_connection(device)

    assert result.success is True
    assert result.method == "primary_direct"
    assert calls == ["10.0.0.1"]


def test_test_device_connection_uses_tunnel_after_direct_failures(monkeypatch):
    device = Device(
        name="MR",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="pwd",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )
    calls: list[str] = []
    closed: list[bool] = []

    class FakeConnection:
        def find_prompt(self):
            return "<MR>"

        def send_command(self, *_args, **_kwargs):
            return "clock"

        def disconnect(self):
            pass

    class FakeSession:
        local_host = "127.0.0.1"
        local_port = 10022

        def close(self):
            closed.append(True)

    def fake_connect(**params):
        calls.append(str(params["host"]))
        if params["host"] != "127.0.0.1":
            raise RuntimeError("direct failed")
        return FakeConnection()

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect)
    monkeypatch.setattr("netconsole.services.netmiko_connection.TunnelManager.open_tunnel", lambda *_args: FakeSession())

    result = test_device_connection(device)

    assert result.success is True
    assert result.method == "tunnel1"
    assert calls == ["10.0.0.1", "10.0.1.1", "127.0.0.1"]
    assert closed == [True]


def test_h3c_sftp_enable_commands_use_current_username_only():
    commands = build_h3c_sftp_enable_commands("admin")

    assert commands == [
        "system-view",
        "sftp server enable",
        "ssh user admin service-type all authentication-type any",
        "return",
        "quit",
    ]
    assert all("password" not in command.lower() for command in commands)


def test_h3c_sftp_enable_commands_require_username():
    with pytest.raises(ValueError):
        build_h3c_sftp_enable_commands("")
