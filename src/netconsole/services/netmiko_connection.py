from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import logging
import re
import socket
from time import monotonic
from typing import Any, Callable, Iterator, TypeVar

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.connection_manager import ConnectionManager
from netconsole.services.device_command_profile_service import (
    resolve_device_capability_commands,
)
from netconsole.services.ssh_tunnel import TunnelManager, TunnelSession
from netconsole.utils.text_encoding import clean_h3c_device_text, safe_decode


logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)


H3C_NETMIKO_DEVICE_TYPE = "hp_comware"
H3C_TELNET_NETMIKO_DEVICE_TYPE = "hp_comware_telnet"
ZTE_NETMIKO_DEVICE_TYPE = "zte_zxros"
ZTE_TELNET_NETMIKO_DEVICE_TYPE = "zte_zxros_telnet"
H3C_DEFAULT_ENCODING = "gb2312"
H3C_FALLBACK_ENCODING = "utf-8"
PROMPT_RE = re.compile(
    r"(?m)(<[^<>\r\n]+>|\[[^\[\]\r\n]+\]|[A-Za-z0-9_.:/()-]{1,128}[>#])\s*$"
)
PROMPT_SYSNAME_PATTERN = re.compile(
    r"^\s*(?:[<\[]([^<>\[\]]+)[>\]]|([A-Za-z0-9_.:/()-]{1,128})[>#])\s*$"
)
PROMPT_TIMESTAMP_PREFIX_RE = re.compile(r"^\s*\[\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s*")
INVALID_PROMPT_CANDIDATES = {
    "sc d",
    "screen-length disable",
    "screen-length d",
    "display version",
    "display current-configuration | include sysname",
    "terminal length 0",
    "show version",
    "quit",
    "return",
    "password:",
    "the connection was closed by the remote host",
}

VENDOR_ENCODING_POLICY = {
    "H3C": H3C_DEFAULT_ENCODING,
    "Huawei": "utf-8",
    "ZTE": "utf-8",
}

T = TypeVar("T")
ConnectionPhaseCallback = Callable[[str, str], None]


def ConnectHandler(**kwargs: object) -> Any:  # noqa: N802 - 保持 Netmiko 公共入口兼容
    try:
        from netmiko import ConnectHandler as connect_handler
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing.
        raise RuntimeError("netmiko is not installed") from exc
    return connect_handler(**kwargs)


@lru_cache(maxsize=1)
def _authentication_exception_types() -> tuple[type[BaseException], ...]:
    classes: list[type[BaseException]] = []
    try:  # pragma: no cover - concrete classes depend on installed dependency versions.
        from netmiko.exceptions import NetmikoAuthenticationException

        classes.append(NetmikoAuthenticationException)
    except Exception:
        pass
    try:  # pragma: no cover
        from paramiko.ssh_exception import AuthenticationException

        classes.append(AuthenticationException)
    except Exception:
        pass
    return tuple(classes)


@lru_cache(maxsize=1)
def _timeout_exception_types() -> tuple[type[BaseException], ...]:
    try:  # pragma: no cover
        from netmiko.exceptions import NetmikoTimeoutException, ReadTimeout
    except Exception:
        return ()
    return NetmikoTimeoutException, ReadTimeout


@lru_cache(maxsize=1)
def _tcp_exception_types() -> tuple[type[BaseException], ...]:
    try:  # pragma: no cover
        from paramiko.ssh_exception import NoValidConnectionsError
    except Exception:
        return ()
    return (NoValidConnectionsError,)


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
    status: str = ""
    error_type: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class ConnectionCheckResult:
    ok: bool
    status: str
    detail: str
    protocol: str
    host: str
    port: int
    latency_ms: float | None = None
    error_type: str | None = None
    suggestion: str | None = None


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


@dataclass(frozen=True)
class ConnectionErrorClassification:
    status: str
    detail: str
    short_detail: str
    error_type: str
    suggestion: str


def test_device_connection(
    device: Device,
    *,
    phase_callback: ConnectionPhaseCallback | None = None,
) -> ConnectionTestResult:
    targets = connection_targets(device)
    if not targets:
        result = ConnectionTestResult(False, "", device.primary_address, 0, "No connection method is enabled.", None, None)
        _log_result("TEST_CONNECTION_FAILED", device, result)
        return result

    started = monotonic()
    last_result: ConnectionTestResult | None = None
    for target in targets:
        _report_connection_phase(
            phase_callback,
            "connecting",
            f"正在连接 {target.host}:{target.port}",
        )
        app_logger.log_debug("TEST_CONNECTION_STARTED", _detail(device, target.protocol, target.port, method=target.method))
        connection: Any | None = None
        try:
            with prepared_connection_target(target) as prepared:
                _report_connection_phase(
                    phase_callback,
                    "handshaking",
                    f"正在执行 {prepared.protocol.upper()} 握手",
                )
                _report_connection_phase(
                    phase_callback,
                    "authenticating",
                    f"正在执行 {prepared.protocol.upper()} 用户认证",
                )
                connection = ConnectHandler(**_netmiko_params(prepared))
                _report_connection_phase(
                    phase_callback,
                    "verifying_session",
                    "正在验证可用会话",
                )
                prompt = _safe_find_prompt(connection)
                screen_output = ""
                session_prepare = resolve_device_capability_commands(
                    device, "session_prepare"
                )[0]
                try:
                    screen_output = safe_send_command(
                        connection,
                        session_prepare,
                        read_timeout=10,
                        strip_prompt=False,
                        strip_command=False,
                        use_timing=True,
                        encoding=prepared.encoding,
                    )
                except Exception:
                    screen_output = ""
                prompt = _safe_find_prompt(connection) or extract_cli_prompt(screen_output) or prompt
                message = f"{prepared.protocol.upper()} 连接成功"
                try:
                    verification = resolve_device_capability_commands(
                        device, "session_verify"
                    )[0]
                    safe_send_command(
                        connection,
                        verification,
                        read_timeout=10,
                        encoding=prepared.encoding,
                    )
                except Exception:
                    message = f"{prepared.protocol.upper()} 连接成功，但会话校验命令未返回预期结果"
                result = ConnectionTestResult(
                    True,
                    prepared.protocol,
                    prepared.host,
                    prepared.port,
                    message,
                    prompt,
                    _elapsed_ms(started),
                    prepared.method,
                    "telnet_ok" if prepared.protocol.casefold() == "telnet" else "ok",
                )
                _log_result("TEST_CONNECTION_SUCCESS", device, result)
                return result
        except Exception as exc:
            classification = classify_connection_exception(exc, target.protocol)
            message = sanitize_sensitive_text(classification.detail, device)
            raw_hint = sanitize_sensitive_text(str(exc), device)
            if raw_hint:
                app_logger.log_debug(
                    "DEVICE_CONNECTION_TECHNICAL_DETAIL",
                    f"error_type={exc.__class__.__name__}; detail={raw_hint}",
                )
            last_result = ConnectionTestResult(
                False,
                target.protocol,
                target.host,
                target.port,
                message,
                None,
                _elapsed_ms(started),
                target.method,
                classification.status,
                classification.error_type,
                classification.suggestion,
            )
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


def _report_connection_phase(
    callback: ConnectionPhaseCallback | None,
    stage: str,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, message)


def run_netmiko_with_retry(device: Device, operation: Callable[[Any, ConnectionTarget], T]) -> T:
    targets = connection_targets(device)
    if not targets:
        raise RuntimeError("No SSH or Telnet connection is enabled.")
    failures: list[ConnectionAttemptLog] = []
    for target in targets:
        connection: Any | None = None
        try:
            with prepared_connection_target(target) as prepared:
                connection = ConnectHandler(**_netmiko_params(prepared))
                result = operation(connection, prepared)
                failures.append(ConnectionAttemptLog(prepared.method, prepared.host, prepared.port, True))
                return result
        except Exception as exc:
            failures.append(ConnectionAttemptLog(target.method, target.host, target.port, False, classify_connection_exception(exc, target.protocol).detail))
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass
    detail = "; ".join(f"{item.method} {item.host}:{item.port} failed: {item.error_message}" for item in failures if not item.success)
    raise RuntimeError(detail or "All connection attempts failed.")


def check_device_login_with_netmiko(device: Device) -> ConnectionCheckResult:
    started = monotonic()
    targets = connection_targets(device)
    if not targets:
        return ConnectionCheckResult(False, "tcp_failed", "未启用 SSH 或 Telnet 连接方式。", "", device.primary_address, 0, None, "no_connection_target", "请在设备管理中启用 SSH、Telnet 或同时启用两者作为 Auto。")
    last_result: ConnectionCheckResult | None = None
    for target in targets:
        connection: Any | None = None
        try:
            with prepared_connection_target(target) as prepared:
                connection = ConnectHandler(**_netmiko_params(prepared))
                _safe_find_prompt(connection)
                status = "telnet_ok" if prepared.protocol.casefold() == "telnet" else "ok"
                detail = "Telnet 登录成功" if status == "telnet_ok" else "SSH 登录成功"
                return ConnectionCheckResult(True, status, detail, prepared.protocol, prepared.host, prepared.port, float(_elapsed_ms(started)), None, None)
        except Exception as exc:
            classification = classify_connection_exception(exc, target.protocol)
            last_result = ConnectionCheckResult(False, classification.status, classification.detail, target.protocol, target.host, target.port, float(_elapsed_ms(started)), classification.error_type, classification.suggestion)
            if classification.status == "auth_failed":
                break
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass
    return last_result or ConnectionCheckResult(False, "unknown_error", "未知连接异常。", "", device.primary_address, 0, float(_elapsed_ms(started)), "unknown_error", "请检查设备连接配置和运行日志。")


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
    vendor = str(device.device_vendor or "H3C").strip().casefold()
    ssh_device_type = (
        ZTE_NETMIKO_DEVICE_TYPE if vendor == "zte" else H3C_NETMIKO_DEVICE_TYPE
    )
    telnet_device_type = (
        ZTE_TELNET_NETMIKO_DEVICE_TYPE
        if vendor == "zte"
        else H3C_TELNET_NETMIKO_DEVICE_TYPE
    )
    for attempt in ConnectionManager().iter_attempts(device):
        if attempt.protocol.casefold() == "ssh":
            targets.append(
                ConnectionTarget(
                    protocol="SSH",
                    device_type=ssh_device_type,
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
                    device_type=telnet_device_type,
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


def classify_connection_exception(exc: BaseException, protocol: str = "SSH") -> ConnectionErrorClassification:
    text = str(exc or "")
    lowered = text.casefold()
    proto = "Telnet" if str(protocol or "").casefold() == "telnet" else "SSH"
    if isinstance(exc, socket.gaierror) or any(
        part in lowered
        for part in (
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
        )
    ):
        return ConnectionErrorClassification(
            "address_resolution_failed",
            "地址解析失败：无法把设备主机名解析为网络地址。",
            "地址解析失败：请检查设备地址或 DNS",
            exc.__class__.__name__,
            "检查设备地址拼写、DNS 配置和本机网络设置。",
        )
    if isinstance(exc, ConnectionRefusedError) or "connection refused" in lowered:
        return ConnectionErrorClassification(
            "connection_refused",
            f"{proto} 连接被拒绝：目标可达，但端口未监听或被设备主动拒绝。",
            f"{proto} 连接被拒绝：请检查端口和服务状态",
            exc.__class__.__name__,
            f"检查{proto}端口、设备服务状态、防火墙和 ACL。",
        )
    if "error reading ssh protocol banner" in lowered or "ssh protocol banner" in lowered:
        return ConnectionErrorClassification(
            "ssh_banner_failed",
            "SSH握手失败：TCP连接可能已建立，但未收到SSH banner，疑似目标未启用SSH、端口不是SSH、设备只支持Telnet、会话数满或设备主动断开。",
            "SSH握手失败：未收到SSH banner，疑似SSH未启用或端口不是SSH",
            exc.__class__.__name__,
            "检查MR是否启用SSH，确认端口号；如设备只支持Telnet，请在设备配置中启用Telnet或同时启用SSH/Telnet作为Auto。",
        )
    if _is_auth_exception(exc) or "authentication" in lowered or "auth failed" in lowered or "认证" in text:
        return ConnectionErrorClassification(
            "auth_failed",
            f"{proto}认证失败：服务可达，但用户名、密码或认证方式不正确。",
            f"{proto}认证失败：请检查账号密码",
            exc.__class__.__name__,
            f"检查{proto}用户名、密码、认证方式和设备 AAA/VTY 配置。",
        )
    if _is_timeout_exception(exc) or "timed out" in lowered or "timeout" in lowered or "超时" in text:
        if "tcp connection to device failed" in lowered or "connection refused" in lowered or "no route to host" in lowered:
            return ConnectionErrorClassification(
                "tcp_failed",
                f"{proto} TCP连接失败：目标不可达、端口未开放或被中间设备拒绝。",
                "TCP连接失败：目标不可达或端口未开放",
                exc.__class__.__name__,
                f"检查目标地址、{proto}端口、防火墙/ACL、路由和设备服务状态。",
            )
        return ConnectionErrorClassification(
            "timeout",
            f"{proto}连接或握手超时：设备响应慢、会话数满或链路质量异常。",
            f"{proto}连接超时：请检查链路或调大超时",
            exc.__class__.__name__,
            "检查设备负载、会话数和网络质量；老设备可适当调大 banner/auth/read timeout。",
        )
    if _is_tcp_exception(exc) or any(part in lowered for part in ("connection refused", "no route to host", "network is unreachable", "unable to connect to port", "tcp connection to device failed")):
        return ConnectionErrorClassification(
            "tcp_failed",
            f"{proto} TCP连接失败：目标不可达、端口未开放或连接被拒绝。",
            "TCP连接失败：目标不可达或端口未开放",
            exc.__class__.__name__,
            f"检查目标地址、{proto}端口、防火墙/ACL、路由和设备服务状态。",
        )
    return ConnectionErrorClassification(
        "unknown_error",
        f"{proto}未知连接异常：{text}" if text else f"{proto}未知连接异常。",
        f"{proto}未知连接异常",
        exc.__class__.__name__,
        "请结合设备服务状态、账号配置和 NetConsole 运行日志继续排查。",
    )


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


def extract_cli_prompt(output: str) -> str:
    for raw_line in reversed(str(output or "").splitlines()):
        line = PROMPT_TIMESTAMP_PREFIX_RE.sub("", raw_line.strip())
        if not line or is_invalid_prompt_candidate(line):
            continue
        match = PROMPT_RE.search(line)
        if not match:
            continue
        prompt = match.group(1).strip()
        if prompt and not is_invalid_prompt_candidate(prompt):
            return prompt
    return ""


def is_invalid_prompt_candidate(value: str) -> bool:
    return str(value or "").strip().casefold() in INVALID_PROMPT_CANDIDATES


def extract_sysname_from_prompt(prompt: str) -> str | None:
    prompt = extract_cli_prompt(prompt)
    match = PROMPT_SYSNAME_PATTERN.match(prompt)
    if not match:
        return None
    sysname = (match.group(1) or match.group(2) or "").strip()
    return sysname or None


def sanitize_sensitive_text(text: str, device: Device | None = None) -> str:
    safe = text
    secrets = []
    if device is not None:
        secrets.extend(
            [
                device.ssh_password,
                device.telnet_password,
                device.snmp_ro_community,
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
        "conn_timeout": 5,
        "auth_timeout": 8,
        "banner_timeout": 8,
        "encoding": target.encoding,
        "session_log": None,
        "global_delay_factor": 1,
        "fast_cli": False,
    }


def _is_auth_exception(exc: BaseException) -> bool:
    classes = _authentication_exception_types()
    return bool(classes and isinstance(exc, classes))


def _is_timeout_exception(exc: BaseException) -> bool:
    classes = _timeout_exception_types()
    return bool(classes and isinstance(exc, classes)) or isinstance(exc, (TimeoutError, socket.timeout))


def _is_tcp_exception(exc: BaseException) -> bool:
    classes = _tcp_exception_types()
    return bool(classes and isinstance(exc, classes)) or isinstance(exc, OSError)


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
    parsed = extract_cli_prompt(str(prompt or ""))
    return parsed or None


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
