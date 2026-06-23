from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re
from time import monotonic
from typing import Any, Callable, Iterator, TypeVar

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.connection_manager import ConnectionManager
from netconsole.services.ssh_tunnel import TunnelManager, TunnelSession
from netconsole.utils.text_encoding import clean_h3c_device_text, safe_decode

try:
    from netmiko import ConnectHandler
except ImportError:  # pragma: no cover - exercised only when dependency is missing.
    ConnectHandler = None  # type: ignore[assignment]


H3C_NETMIKO_DEVICE_TYPE = "hp_comware"
H3C_TELNET_NETMIKO_DEVICE_TYPE = "hp_comware_telnet"
H3C_DEFAULT_ENCODING = "gb2312"
H3C_FALLBACK_ENCODING = "utf-8"
PROMPT_SYSNAME_PATTERN = re.compile(r"^\s*[<\[]([^<>\[\]]+)[>\]]\s*$")

VENDOR_ENCODING_POLICY = {
    "H3C": H3C_DEFAULT_ENCODING,
    "Huawei": "utf-8",
    "ZTE": "utf-8",
}

T = TypeVar("T")


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    protocol: str
    host: str
    port: int
    message: str
    prompt: str | None
    elapsed_ms: int | None
    method: str = ""


@dataclass(frozen=True)
class ConnectionTarget:
    protocol: str
    device_type: str
    host: str
    port: int
    username: str
    password: str
    encoding: str = H3C_DEFAULT_ENCODING
    method: str = "primary_direct"
    via_tunnel: bool = False
    tunnel: object | None = None


@dataclass(frozen=True)
class ConnectionAttemptLog:
    method: str
    host: str
    port: int
    success: bool
    error_message: str = ""


def test_device_connection(device: Device) -> ConnectionTestResult:
    targets = connection_targets(device)
    if not targets:
        result = ConnectionTestResult(False, "", device.primary_address, 0, "No connection method is enabled.", None, None)
        _log_result("TEST_CONNECTION_FAILED", device, result)
        return result

    started = monotonic()
    last_result: ConnectionTestResult | None = None
    for target in targets:
        app_logger.log_info("TEST_CONNECTION_STARTED", _detail(device, target.protocol, target.port, method=target.method))
        connection: Any | None = None
        try:
            if ConnectHandler is None:
                raise RuntimeError("netmiko is not installed")
            with prepared_connection_target(target) as prepared:
                connection = ConnectHandler(**_netmiko_params(prepared))
                prompt = _safe_find_prompt(connection)
                message = "Connection succeeded"
                try:
                    safe_send_command(connection, "display clock", read_timeout=10, encoding=prepared.encoding)
                except Exception as exc:
                    message = f"Connection succeeded; display clock failed: {sanitize_sensitive_text(str(exc), device)}"
                result = ConnectionTestResult(True, prepared.protocol, prepared.host, prepared.port, message, prompt, _elapsed_ms(started), prepared.method)
                _log_result("TEST_CONNECTION_SUCCESS", device, result)
                return result
        except Exception as exc:
            last_result = ConnectionTestResult(False, target.protocol, target.host, target.port, sanitize_sensitive_text(str(exc), device), None, _elapsed_ms(started), target.method)
            _log_result("TEST_CONNECTION_ATTEMPT_FAILED", device, last_result)
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass
    result = last_result or ConnectionTestResult(False, "", device.primary_address, 0, "All connection attempts failed.", None, _elapsed_ms(started))
    _log_result("TEST_CONNECTION_FAILED", device, result)
    return result


def run_netmiko_with_retry(device: Device, operation: Callable[[Any, ConnectionTarget], T]) -> T:
    targets = connection_targets(device)
    if not targets:
        raise RuntimeError("No SSH or Telnet connection is enabled.")
    failures: list[ConnectionAttemptLog] = []
    for target in targets:
        connection: Any | None = None
        try:
            if ConnectHandler is None:
                raise RuntimeError("netmiko is not installed")
            with prepared_connection_target(target) as prepared:
                connection = ConnectHandler(**_netmiko_params(prepared))
                result = operation(connection, prepared)
                failures.append(ConnectionAttemptLog(prepared.method, prepared.host, prepared.port, True))
                return result
        except Exception as exc:
            failures.append(ConnectionAttemptLog(target.method, target.host, target.port, False, str(exc)))
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass
    detail = "; ".join(f"{item.method} {item.host}:{item.port} failed: {item.error_message}" for item in failures if not item.success)
    raise RuntimeError(detail or "All connection attempts failed.")


@contextmanager
def prepared_connection_target(target: ConnectionTarget) -> Iterator[ConnectionTarget]:
    session: TunnelSession | None = None
    prepared = target
    if target.via_tunnel:
        if target.tunnel is None:
            raise RuntimeError("Tunnel target is missing tunnel profile")
        session = TunnelManager().open_tunnel(target.tunnel, target.host, target.port)  # type: ignore[arg-type]
        prepared = ConnectionTarget(
            protocol=target.protocol,
            device_type=target.device_type,
            host=session.local_host,
            port=session.local_port,
            username=target.username,
            password=target.password,
            encoding=target.encoding,
            method=target.method,
            via_tunnel=True,
            tunnel=target.tunnel,
        )
    try:
        yield prepared
    finally:
        if session is not None:
            session.close()


def choose_connection_target(device: Device) -> ConnectionTarget | None:
    targets = connection_targets(device)
    return targets[0] if targets else None


def connection_targets(device: Device) -> list[ConnectionTarget]:
    targets: list[ConnectionTarget] = []
    for attempt in ConnectionManager().iter_attempts(device):
        if attempt.protocol.casefold() == "ssh":
            targets.append(
                ConnectionTarget(
                    protocol="SSH",
                    device_type=H3C_NETMIKO_DEVICE_TYPE,
                    host=attempt.host,
                    port=attempt.port,
                    username=attempt.username,
                    password=attempt.password,
                    encoding=encoding_for_vendor(device.device_vendor),
                    method=attempt.label,
                    via_tunnel=attempt.via_tunnel,
                    tunnel=attempt.tunnel,
                )
            )
        elif attempt.protocol.casefold() == "telnet":
            targets.append(
                ConnectionTarget(
                    protocol="Telnet",
                    device_type=H3C_TELNET_NETMIKO_DEVICE_TYPE,
                    host=attempt.host,
                    port=attempt.port,
                    username=attempt.username,
                    password=attempt.password,
                    encoding=encoding_for_vendor(device.device_vendor),
                    method=attempt.label,
                    via_tunnel=attempt.via_tunnel,
                    tunnel=attempt.tunnel,
                )
            )
    return targets


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
        output = _send_with_encoding(connection.send_command_timing, command, kwargs, encoding)
    else:
        output = _send_with_encoding(connection.send_command, command, {"read_timeout": read_timeout}, encoding)
    return normalize_command_output(output, encoding)


def normalize_command_output(output: object, encoding: str = H3C_DEFAULT_ENCODING) -> str:
    if isinstance(output, bytes):
        text = safe_decode(output)
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
                device.tunnel1_password,
                device.tunnel2_password,
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
        "encoding": target.encoding,
        "session_log": None,
        "global_delay_factor": 1,
    }


def _send_with_encoding(method: Any, command: str, kwargs: dict[str, object], encoding: str) -> object:
    try:
        return method(command, encoding=encoding, **kwargs)
    except UnicodeDecodeError:
        return method(command, encoding=H3C_FALLBACK_ENCODING, **kwargs)
    except TypeError as exc:
        if "encoding" not in str(exc):
            raise
        return method(command, **kwargs)


def _safe_find_prompt(connection: Any) -> str | None:
    try:
        prompt = connection.find_prompt()
    except Exception:
        return None
    return str(prompt) if prompt is not None else None


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _detail(
    device: Device,
    protocol: str,
    port: int,
    message: str = "",
    elapsed_ms: int | None = None,
    sysname: str | None = None,
    method: str = "",
) -> str:
    parts = [
        f"device={device.name}",
        f"primary_address={device.primary_address}",
        f"protocol={protocol}",
        f"port={port}",
    ]
    if method:
        parts.append(f"method={method}")
    if sysname:
        parts.append(f"system_name={sysname}")
    if elapsed_ms is not None:
        parts.append(f"elapsed={elapsed_ms}ms")
    if message:
        parts.append(f"message={message}")
    return ", ".join(parts)


def _log_result(event: str, device: Device, result: ConnectionTestResult) -> None:
    detail = _detail(device, result.protocol, result.port, result.message, result.elapsed_ms, extract_sysname_from_prompt(result.prompt or ""), result.method)
    if result.success:
        app_logger.log_info(event, detail)
    else:
        app_logger.log_error(event, detail)


test_device_connection.__test__ = False
