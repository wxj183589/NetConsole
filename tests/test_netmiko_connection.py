from __future__ import annotations

from netconsole.models.device import Device
from netconsole.services import netmiko_connection
from netconsole.services.netmiko_connection import choose_connection_target, extract_sysname_from_prompt, sanitize_sensitive_text, test_device_connection


def test_extract_sysname_from_angle_prompt():
    assert extract_sysname_from_prompt("<AC>") == "AC"
    assert extract_sysname_from_prompt("<SW01>") == "SW01"


def test_extract_sysname_from_square_prompt():
    assert extract_sysname_from_prompt("[AC]") == "AC"
    assert extract_sysname_from_prompt("[SW01-probe]") == "SW01-probe"


def test_extract_sysname_from_invalid_prompt_returns_none():
    assert extract_sysname_from_prompt("") is None
    assert extract_sysname_from_prompt("invalid") is None


def test_ssh_enabled_prefers_ssh():
    device = Device(
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_port=2222,
        telnet_enabled=1,
        telnet_port=2323,
        ssh_username="ssh_user",
        ssh_password="ssh_password",
        telnet_username="telnet_user",
        telnet_password="telnet_password",
    )

    target = choose_connection_target(device)

    assert target is not None
    assert target.protocol == "SSH"
    assert target.device_type == "h3c_comware"
    assert target.port == 2222
    assert target.username == "ssh_user"
    assert target.password == "ssh_password"


def test_telnet_selected_when_ssh_disabled():
    device = Device(
        ip_address="10.0.0.1",
        ssh_enabled=0,
        telnet_enabled=1,
        telnet_port=2323,
        telnet_username="telnet_user",
        telnet_password="telnet_password",
    )

    target = choose_connection_target(device)

    assert target is not None
    assert target.protocol == "Telnet"
    assert target.device_type == "hp_comware_telnet"
    assert target.port == 2323
    assert target.username == "telnet_user"
    assert target.password == "telnet_password"


def test_no_protocol_enabled_returns_failure():
    device = Device(ip_address="10.0.0.1", ssh_enabled=0, telnet_enabled=0)

    result = test_device_connection(device)

    assert result.success is False
    assert result.message == "未启用连接方式"
    assert result.protocol == ""


def test_sanitize_sensitive_text_masks_passwords():
    device = Device(
        ssh_password="sshSecret",
        telnet_password="telnetSecret",
        snmpv3_auth_password="authSecret",
        snmpv3_priv_password="privSecret",
    )

    safe = sanitize_sensitive_text(
        "sshSecret telnetSecret authSecret privSecret password=plain ssh_password=named",
        device,
    )

    assert "sshSecret" not in safe
    assert "telnetSecret" not in safe
    assert "authSecret" not in safe
    assert "privSecret" not in safe
    assert "plain" not in safe
    assert "named" not in safe
    assert "***" in safe


def test_connect_handler_called_with_netmiko_params(monkeypatch):
    calls = {}

    class FakeConnection:
        def find_prompt(self):
            return "<SW01>"

        def send_command(self, command, read_timeout=None):
            calls["command"] = command
            calls["read_timeout"] = read_timeout
            return "clock"

        def disconnect(self):
            calls["disconnect"] = True

    def fake_connect_handler(**kwargs):
        calls["kwargs"] = kwargs
        return FakeConnection()

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    result = test_device_connection(
        Device(
            name="SW01",
            ip_address="10.0.0.52",
            ssh_enabled=1,
            ssh_port=22,
            ssh_username="admin",
            ssh_password="Admin@123",
        )
    )

    assert result.success is True
    assert result.protocol == "SSH"
    assert result.prompt == "<SW01>"
    assert calls["kwargs"] == {
        "device_type": "h3c_comware",
        "host": "10.0.0.52",
        "username": "admin",
        "password": "Admin@123",
        "port": 22,
        "timeout": 10,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 10,
    }
    assert calls["command"] == "display clock"
    assert calls["read_timeout"] == 10
    assert calls["disconnect"] is True


def test_connection_exception_returns_failure_without_password(monkeypatch):
    def fake_connect_handler(**_kwargs):
        raise RuntimeError("auth failed with Admin@123")

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    result = test_device_connection(
        Device(
            name="SW01",
            ip_address="10.0.0.52",
            ssh_enabled=1,
            ssh_username="admin",
            ssh_password="Admin@123",
        )
    )

    assert result.success is False
    assert "Admin@123" not in result.message
    assert "***" in result.message


def test_disconnect_called_when_send_command_fails(monkeypatch):
    calls = {}

    class FakeConnection:
        def find_prompt(self):
            return "<SW01>"

        def send_command(self, *_args, **_kwargs):
            raise RuntimeError("command failed")

        def disconnect(self):
            calls["disconnect"] = True

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", lambda **_kwargs: FakeConnection())

    result = test_device_connection(Device(ip_address="10.0.0.52", ssh_enabled=1))

    assert result.success is True
    assert "display clock" in result.message
    assert calls["disconnect"] is True
