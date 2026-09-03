from __future__ import annotations

import importlib.util
import paramiko
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from netconsole.models.device import Device
from netconsole.services import netmiko_connection
from netconsole.services.netmiko_connection import (
    H3C_DEFAULT_ENCODING,
    choose_connection_target,
    encoding_for_vendor,
    extract_cli_prompt,
    extract_sysname_from_prompt,
    safe_send_command,
    sanitize_sensitive_text,
    test_device_connection,
    connection_targets,
)


def test_extract_sysname_from_angle_prompt():
    assert extract_sysname_from_prompt("<AC>") == "AC"
    assert extract_sysname_from_prompt("<SW01>") == "SW01"


def test_extract_sysname_from_square_prompt():
    assert extract_sysname_from_prompt("[AC]") == "AC"
    assert extract_sysname_from_prompt("[SW01-probe]") == "SW01-probe"


def test_extract_sysname_from_zte_prompt():
    assert extract_sysname_from_prompt("ZTE-Core-01#") == "ZTE-Core-01"
    assert extract_sysname_from_prompt("ZTE-Access-01>") == "ZTE-Access-01"


def test_extract_sysname_from_invalid_prompt_returns_none():
    assert extract_sysname_from_prompt("") is None
    assert extract_sysname_from_prompt("invalid") is None


def test_extract_cli_prompt_ignores_screen_length_echo():
    assert extract_cli_prompt("screen-length disable\nsc d\n<YunLongCLD-2>\n") == "<YunLongCLD-2>"


def test_extract_cli_prompt_handles_timestamped_h3c_prompt():
    output = "[23:48:10]<NBDT12HX-WX3540X-AC1>screen-length disable\n[23:48:10]<NBDT12HX-WX3540X-AC1>\n"

    assert extract_cli_prompt(output) == "<NBDT12HX-WX3540X-AC1>"


def test_extract_cli_prompt_rejects_command_echo_only():
    assert extract_cli_prompt("sc d\n") == ""


def test_extract_cli_prompt_accepts_probe_prompt():
    assert extract_cli_prompt("[H3C-probe]\n") == "[H3C-probe]"


def test_h3c_encoding_policy_defaults_to_gb2312():
    assert H3C_DEFAULT_ENCODING == "gb2312"
    assert encoding_for_vendor("H3C") == "gb2312"


def test_safe_send_command_decodes_h3c_gb2312_output_to_unicode():
    class FakeConnection:
        def send_command(self, command, read_timeout=None, encoding=None):
            assert encoding == "gb2312"
            return "Description: To_广播系统".encode("gb2312")

    output = safe_send_command(FakeConnection(), "display interface")

    assert "Description: To_广播系统" in output


def test_safe_send_command_falls_back_to_utf8_on_decode_error():
    calls = []

    class FakeConnection:
        def send_command(self, command, read_timeout=None, encoding=None):
            calls.append(encoding)
            if encoding == "gb2312":
                raise UnicodeDecodeError("gb2312", b"", 0, 1, "boom")
            return "utf8 ok"

    assert safe_send_command(FakeConnection(), "display interface") == "utf8 ok"
    assert calls == ["gb2312", "utf-8"]


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
    assert target.device_type == "hp_comware"
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


def test_tunnel_hosts_enable_specific_tunnels_without_global_switch():
    device = Device(
        name="MR2",
        ip_address="192.0.2.10",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        tunnel_enabled=0,
        tunnel1_enabled=0,
        tunnel1_host="198.51.100.10",
        tunnel1_username="jump",
        tunnel1_password="jump-secret",
        tunnel2_enabled=0,
        tunnel2_host="198.51.100.11",
        tunnel2_username="jump",
        tunnel2_password="jump-secret",
    )

    targets = connection_targets(device)

    tunnel_targets = [target for target in targets if target.via_tunnel]
    assert [target.method for target in tunnel_targets] == [
        "tunnel1_primary",
        "tunnel2_primary",
    ]
    assert [target.tunnel.host for target in tunnel_targets if target.tunnel is not None] == ["198.51.100.10", "198.51.100.11"]


def test_empty_tunnel_host_disables_specific_tunnel():
    device = Device(
        name="MR2",
        ip_address="192.0.2.10",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="",
        tunnel1_username="jump",
        tunnel1_password="jump-secret",
        tunnel2_enabled=1,
        tunnel2_host="198.51.100.11",
        tunnel2_username="jump",
        tunnel2_password="jump-secret",
    )

    assert [
        target.method
        for target in connection_targets(device)
        if target.via_tunnel
    ] == ["tunnel2_primary"]


def test_no_protocol_enabled_returns_failure():
    device = Device(ip_address="10.0.0.1", ssh_enabled=0, telnet_enabled=0)

    result = test_device_connection(device)

    assert result.success is False
    assert result.protocol == ""


def test_sanitize_sensitive_text_masks_passwords():
    device = Device(
        ssh_password="sshSecret",
        telnet_password="telnetSecret",
        snmp_ro_community="communitySecret",
    )

    safe = sanitize_sensitive_text(
        "sshSecret telnetSecret communitySecret password=plain ssh_password=named",
        device,
    )

    assert "sshSecret" not in safe
    assert "telnetSecret" not in safe
    assert "communitySecret" not in safe
    assert "plain" not in safe
    assert "named" not in safe
    assert "***" in safe


def test_connect_handler_called_with_netmiko_params(monkeypatch):
    calls = {}
    prompts = ["sc d", "<SW01>"]
    commands = []

    class FakeConnection:
        def find_prompt(self):
            return prompts.pop(0)

        def send_command(self, command, read_timeout=None, encoding=None):
            commands.append(command)
            calls["read_timeout"] = read_timeout
            calls["encoding"] = encoding
            return "clock"

        def send_command_timing(self, command, **_kwargs):
            commands.append(command)
            return "screen-length disable\n<SW01>\n"

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
        "device_type": "hp_comware",
        "host": "10.0.0.52",
        "username": "admin",
        "password": "Admin@123",
        "port": 22,
        "timeout": 10,
        "conn_timeout": 5,
        "auth_timeout": 8,
        "banner_timeout": 8,
        "encoding": "gb2312",
        "session_log": None,
        "global_delay_factor": 1,
        "fast_cli": False,
    }
    assert commands == ["screen-length disable", "display clock"]
    assert calls["read_timeout"] == 10
    assert calls["encoding"] == "gb2312"
    assert calls["disconnect"] is True


def test_zte_connection_uses_zxros_and_never_sends_h3c_session_commands(
    monkeypatch,
):
    calls: dict[str, object] = {}
    commands: list[str] = []

    class FakeConnection:
        def find_prompt(self):
            return "ZTE-Core-01#"

        def send_command_timing(self, command, **_kwargs):
            commands.append(command)
            return "ZTE-Core-01#"

        def send_command(self, command, **_kwargs):
            commands.append(command)
            return "ZXR10 software version test"

        def disconnect(self):
            return None

    def fake_connect_handler(**kwargs):
        calls.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    result = test_device_connection(
        Device(
            name="ZTE-Core-01",
            device_vendor="ZTE",
            device_type="SW",
            ip_address="203.0.113.10",
            ssh_enabled=1,
            ssh_username="test",
            ssh_password="TEST_PASSWORD",
        )
    )

    assert result.success is True
    assert calls["device_type"] == "zte_zxros"
    assert calls["encoding"] == "utf-8"
    assert commands == ["show version"]
    assert "screen-length disable" not in commands


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
    assert "认证失败" in result.message


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
    assert "会话校验命令未返回预期结果" in result.message
    assert calls["disconnect"] is True


def test_connection_banner_failure_is_structured_without_traceback(monkeypatch, capsys):
    def fake_connect_handler(**_kwargs):
        raise RuntimeError("Exception (client): Error reading SSH protocol banner")

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    result = test_device_connection(Device(ip_address="10.0.0.52", ssh_enabled=1, ssh_username="admin", ssh_password="pwd"))

    captured = capsys.readouterr()
    assert result.success is False
    assert result.status == "ssh_banner_failed"
    assert "SSH握手失败" in result.message
    assert "Traceback" not in result.message
    assert "Traceback" not in captured.err


def test_connection_targets_include_telnet_after_ssh_when_both_enabled():
    targets = connection_targets(
        Device(
            ip_address="10.0.0.52",
            ssh_enabled=1,
            ssh_port=22,
            ssh_username="ssh",
            ssh_password="ssh_pwd",
            telnet_enabled=1,
            telnet_port=23,
            telnet_username="telnet",
            telnet_password="telnet_pwd",
        )
    )

    assert [target.protocol for target in targets[:2]] == ["SSH", "Telnet"]
    assert targets[0].username == "ssh"
    assert targets[1].username == "telnet"


def test_auto_targets_fall_back_to_telnet_after_ssh_banner_failure(monkeypatch):
    calls = []

    class FakeConnection:
        def find_prompt(self):
            return "<SW01>"

        def send_command_timing(self, command, **_kwargs):
            return "screen-length disable\n<SW01>\n"

        def send_command(self, command, **_kwargs):
            return "clock"

        def disconnect(self):
            calls.append("disconnect")

    def fake_connect_handler(**kwargs):
        calls.append(kwargs["device_type"])
        if kwargs["device_type"] == "hp_comware":
            raise RuntimeError("Error reading SSH protocol banner")
        return FakeConnection()

    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    result = test_device_connection(
        Device(
            ip_address="10.0.0.52",
            ssh_enabled=1,
            ssh_username="ssh",
            ssh_password="ssh_pwd",
            telnet_enabled=1,
            telnet_username="telnet",
            telnet_password="telnet_pwd",
        )
    )

    assert result.success is True
    assert result.protocol == "Telnet"
    assert result.status == "telnet_ok"
    assert calls[:2] == ["hp_comware", "hp_comware_telnet"]
    assert "disconnect" in calls


def test_h3c_legacy_ssh_rsa_fallback_is_scoped_and_logged(monkeypatch):
    calls: list[dict[str, object]] = []
    events: list[tuple[str, str]] = []

    def fake_handler(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise paramiko.SSHException("Negotiation failed.")
        return object()

    monkeypatch.setattr(
        netmiko_connection.app_logger,
        "log_info",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )
    monkeypatch.setattr(
        netmiko_connection.app_logger,
        "log_warning",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )

    with netmiko_connection.ssh_connection_context(
        "fit_ap", "collect", device_uuid="device-uuid"
    ):
        result = netmiko_connection._connect_with_compatibility(
            fake_handler,
            {
                "device_type": "hp_comware",
                "host": "10.82.21.209",
                "username": "admin",
                "password": "secret",
            },
        )

    assert result is not None
    assert len(calls) == 2
    assert "disabled_algorithms" not in calls[0]
    assert calls[1]["disabled_algorithms"] == {
        "keys": ["rsa-sha2-512", "rsa-sha2-256"]
    }
    assert any(
        event == "ssh_compatibility_fallback"
        and "collector=fit_ap" in detail
        and "phase=collect" in detail
        and "device_uuid=device-uuid" in detail
        and "host=10.82.21.209" in detail
        and "reason=host_key_algorithm" in detail
        and "mode=legacy_ssh_rsa" in detail
        and "success=true" in detail
        for event, detail in events
    )
    assert any(
        event == "ssh_connection_attempt"
        and "ssh_mode=normal" in detail
        and "result=negotiation_failed" in detail
        for event, detail in events
    )
    assert any(
        event == "ssh_connection_attempt"
        and "ssh_mode=legacy_ssh_rsa" in detail
        and "result=success" in detail
        for event, detail in events
    )
    assert all("secret" not in detail for _event, detail in events)


def test_h3c_legacy_fallback_recognizes_netmiko_wrapped_paramiko_negotiation(monkeypatch):
    from netmiko.exceptions import NetmikoTimeoutException

    calls: list[dict[str, object]] = []

    def fake_handler(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise NetmikoTimeoutException(
                "A paramiko SSHException occurred during connection creation:\n\nNegotiation failed."
            )
        return object()

    with netmiko_connection.ssh_connection_context("ac_basic", "collect", device_uuid="ac-1"):
        result = netmiko_connection._connect_with_compatibility(
            fake_handler,
            {"device_type": "hp_comware", "host": "10.82.21.209"},
        )

    assert result is not None
    assert len(calls) == 2
    assert calls[1]["disabled_algorithms"] == {
        "keys": ["rsa-sha2-512", "rsa-sha2-256"]
    }


def test_legacy_fallback_does_not_apply_to_auth_timeout_or_other_algorithm_errors(monkeypatch):
    for error in (
        paramiko.AuthenticationException("Authentication failed"),
        TimeoutError("connection timed out"),
        paramiko.SSHException("no matching key exchange method found"),
    ):
        calls: list[dict[str, object]] = []

        def fake_handler(**kwargs):
            calls.append(kwargs)
            raise error

        with netmiko_connection.ssh_connection_context("fit_ap", "collect"):
            try:
                netmiko_connection._connect_with_compatibility(
                    fake_handler,
                    {"device_type": "hp_comware", "host": "10.0.0.1"},
                )
            except BaseException as actual:
                assert actual is error
            else:  # pragma: no cover - assertion keeps the fallback contract explicit.
                raise AssertionError("connection error should be raised")
        assert len(calls) == 1


def test_legacy_fallback_does_not_apply_to_non_h3c_device():
    calls = []

    def fake_handler(**kwargs):
        calls.append(kwargs)
        raise paramiko.SSHException("Negotiation failed.")

    try:
        netmiko_connection._connect_with_compatibility(
            fake_handler,
            {"device_type": "zte_zxros", "host": "10.0.0.2"},
        )
    except paramiko.SSHException:
        pass
    assert len(calls) == 1


def test_mr_sidecar_connection_log_uses_actual_collector(monkeypatch, tmp_path):
    module_name = "netconsole_test_mr_collector_cli"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PROJECT_ROOT / "apps" / "agent" / "mr_collector_py" / "collector_cli.py",
    )
    assert spec is not None and spec.loader is not None
    sidecar = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = sidecar
    try:
        spec.loader.exec_module(sidecar)
        calls = []

        def fake_connect_handler(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError(
                    "A paramiko SSHException occurred during connection creation:\n\nNegotiation failed."
                )
            return object()

        monkeypatch.setattr(sidecar, "ConnectHandler", fake_connect_handler)
        app = sidecar.MRCollectorApp(
            {
                "target": {
                    "host": "10.82.21.209",
                    "protocol": "ssh",
                    "username": "admin",
                    "password": "secret",
                },
                "session": {"device_uuid": "device-uuid"},
            },
            tmp_path / "session",
            tmp_path / "stop",
            tmp_path / "events.jsonl",
            tmp_path / "status.json",
        )
        app.prepare()
        connection = app.connect(collector=sidecar.ITEM_AP_RADIO_STATISTICS)

        assert connection is not None
        assert len(calls) == 2
        assert calls[1]["disabled_algorithms"] == {
            "keys": ["rsa-sha2-512", "rsa-sha2-256"]
        }
        log_text = (tmp_path / "session" / "logs" / "collector.log").read_text(encoding="utf-8")
        assert "collector=ap_radio_statistics" in log_text
        assert "device_uuid=device-uuid" in log_text
        assert "host=10.82.21.209" in log_text
        assert "ssh_mode=normal" in log_text
        assert "result=negotiation_failed" in log_text
        assert "ssh_mode=legacy_ssh_rsa" in log_text
        assert "result=success" in log_text
    finally:
        sys.modules.pop(module_name, None)
