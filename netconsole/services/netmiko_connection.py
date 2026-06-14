from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from netconsole.core import app_logger
from netconsole.models.device import Device

try:
    from netmiko import ConnectHandler
except ImportError:  # pragma: no cover - exercised only when dependency is missing.
    ConnectHandler = None  # type: ignore[assignment]


H3C_NETMIKO_DEVICE_TYPE = "h3c_comware"
H3C_TELNET_NETMIKO_DEVICE_TYPE = "hp_comware_telnet"


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    protocol: str
    host: str
    port: int
    message: str
    prompt: str | None
    elapsed_ms: int | None


@dataclass(frozen=True)
class ConnectionTarget:
    protocol: str
    device_type: str
    host: str
    port: int
    username: str
    password: str


def test_device_connection(device: Device) -> ConnectionTestResult:
    target = choose_connection_target(device)
    if target is None:
        result = ConnectionTestResult(False, "", device.ip_address, 0, "未启用连接方式", None, None)
        _log_result("TEST_CONNECTION_FAILED", device, result)
        return result

    app_logger.log_info("TEST_CONNECTION_STARTED", _detail(device, target.protocol, target.port))
    started = monotonic()
    connection: Any | None = None
    try:
        if ConnectHandler is None:
            raise RuntimeError("netmiko is not installed")
        connection = ConnectHandler(**_netmiko_params(target))
        prompt = _safe_find_prompt(connection)
        message = "连接成功"
        try:
            connection.send_command("display clock", read_timeout=10)
        except Exception as exc:
            message = f"连接成功，display clock 执行失败：{sanitize_sensitive_text(str(exc), device)}"
        result = ConnectionTestResult(
            True,
            target.protocol,
            target.host,
            target.port,
            message,
            prompt,
            _elapsed_ms(started),
        )
        _log_result("TEST_CONNECTION_SUCCESS", device, result)
        return result
    except Exception as exc:
        result = ConnectionTestResult(
            False,
            target.protocol,
            target.host,
            target.port,
            sanitize_sensitive_text(str(exc), device),
            None,
            _elapsed_ms(started),
        )
        _log_result("TEST_CONNECTION_FAILED", device, result)
        return result
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def choose_connection_target(device: Device) -> ConnectionTarget | None:
    if bool(device.ssh_enabled):
        return ConnectionTarget(
            protocol="SSH",
            device_type=H3C_NETMIKO_DEVICE_TYPE,
            host=device.ip_address,
            port=int(device.ssh_port or 22),
            username=device.ssh_username or "",
            password=device.ssh_password or "",
        )
    if bool(device.telnet_enabled):
        return ConnectionTarget(
            protocol="Telnet",
            device_type=H3C_TELNET_NETMIKO_DEVICE_TYPE,
            host=device.ip_address,
            port=int(device.telnet_port or 23),
            username=device.telnet_username or "",
            password=device.telnet_password or "",
        )
    return None


def build_netmiko_params(target: ConnectionTarget) -> dict[str, object]:
    return _netmiko_params(target)


def sanitize_sensitive_text(text: str, device: Device | None = None) -> str:
    safe = text
    secrets = []
    if device is not None:
        secrets.extend(
            [
                device.ssh_password,
                device.telnet_password,
                device.snmpv3_auth_password,
                device.snmpv3_priv_password,
            ]
        )
    for secret in sorted({str(value) for value in secrets if value}, key=len, reverse=True):
        safe = safe.replace(secret, "***")
    return app_logger.sanitize_detail(safe)


def _netmiko_params(target: ConnectionTarget) -> dict[str, object]:
    return {
        "device_type": target.device_type,
        "host": target.host,
        "username": target.username,
        "password": target.password,
        "port": target.port,
        "timeout": 10,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 10,
    }


def _safe_find_prompt(connection: Any) -> str | None:
    try:
        prompt = connection.find_prompt()
    except Exception:
        return None
    return str(prompt) if prompt is not None else None


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _detail(device: Device, protocol: str, port: int, message: str = "", elapsed_ms: int | None = None) -> str:
    parts = [
        f"device={device.name}",
        f"ip={device.ip_address}",
        f"protocol={protocol}",
        f"port={port}",
    ]
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms}")
    if message:
        parts.append(f"message={message}")
    return ", ".join(parts)


def _log_result(event: str, device: Device, result: ConnectionTestResult) -> None:
    detail = _detail(device, result.protocol, result.port, result.message, result.elapsed_ms)
    if result.success:
        app_logger.log_info(event, detail)
    else:
        app_logger.log_error(event, detail)


test_device_connection.__test__ = False
