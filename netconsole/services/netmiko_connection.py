from __future__ import annotations

from dataclasses import dataclass
import re
from time import monotonic
from typing import Any

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.utils.text_encoding import clean_h3c_device_text

try:
    from netmiko import ConnectHandler
except ImportError:  # pragma: no cover - exercised only when dependency is missing.
    ConnectHandler = None  # type: ignore[assignment]


H3C_NETMIKO_DEVICE_TYPE = "h3c_comware"
H3C_TELNET_NETMIKO_DEVICE_TYPE = "hp_comware_telnet"
H3C_DEFAULT_ENCODING = "gb18030"
PROMPT_SYSNAME_PATTERN = re.compile(r"^\s*[<\[]([^<>\[\]]+)[>\]]\s*$")

VENDOR_ENCODING_POLICY = {
    "H3C": H3C_DEFAULT_ENCODING,
    "Huawei": "utf-8",
    "ZTE": "utf-8",
}


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
    encoding: str = H3C_DEFAULT_ENCODING


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
            safe_send_command(connection, "display clock", read_timeout=10, encoding=target.encoding)
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
            encoding=encoding_for_vendor(device.device_vendor),
        )
    if bool(device.telnet_enabled):
        return ConnectionTarget(
            protocol="Telnet",
            device_type=H3C_TELNET_NETMIKO_DEVICE_TYPE,
            host=device.ip_address,
            port=int(device.telnet_port or 23),
            username=device.telnet_username or "",
            password=device.telnet_password or "",
            encoding=encoding_for_vendor(device.device_vendor),
        )
    return None


def build_netmiko_params(target: ConnectionTarget) -> dict[str, object]:
    return _netmiko_params(target)


def encoding_for_vendor(vendor: str | None) -> str:
    return VENDOR_ENCODING_POLICY.get(str(vendor or "H3C"), "utf-8")


def safe_send_command(
    connection: Any,
    command: str,
    *,
    read_timeout: int = 30,
    strip_prompt: bool | None = None,
    strip_command: bool | None = None,
    use_timing: bool = False,
    encoding: str = H3C_DEFAULT_ENCODING,
) -> str:
    if use_timing and hasattr(connection, "send_command_timing"):
        kwargs: dict[str, object] = {"read_timeout": read_timeout}
        if strip_prompt is not None:
            kwargs["strip_prompt"] = strip_prompt
        if strip_command is not None:
            kwargs["strip_command"] = strip_command
        output = connection.send_command_timing(command, **kwargs)
    else:
        output = connection.send_command(command, read_timeout=read_timeout)
    return normalize_command_output(output, encoding)


def normalize_command_output(output: object, encoding: str = H3C_DEFAULT_ENCODING) -> str:
    if isinstance(output, bytes):
        try:
            text = output.decode(encoding, errors="replace")
        except LookupError:
            text = output.decode(H3C_DEFAULT_ENCODING, errors="replace")
    else:
        text = str(output or "")
    if encoding == H3C_DEFAULT_ENCODING:
        return clean_h3c_device_text(text)
    return text


def extract_sysname_from_prompt(prompt: str) -> str | None:
    match = PROMPT_SYSNAME_PATTERN.match(prompt or "")
    if not match:
        return None
    sysname = match.group(1).strip()
    return sysname or None


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


def _detail(device: Device, protocol: str, port: int, message: str = "", elapsed_ms: int | None = None, sysname: str | None = None) -> str:
    parts = [
        f"device={device.name}",
        f"ip={device.ip_address}",
        f"protocol={protocol}",
        f"port={port}",
    ]
    if sysname:
        parts.append(f"sysname={sysname}")
    if elapsed_ms is not None:
        parts.append(f"elapsed={elapsed_ms}ms")
    if message:
        parts.append(f"message={message}")
    return ", ".join(parts)


def _log_result(event: str, device: Device, result: ConnectionTestResult) -> None:
    detail = _detail(device, result.protocol, result.port, result.message, result.elapsed_ms, extract_sysname_from_prompt(result.prompt or ""))
    if result.success:
        app_logger.log_info(event, detail)
    else:
        app_logger.log_error(event, detail)


test_device_connection.__test__ = False
