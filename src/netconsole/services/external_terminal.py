from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Protocol
from urllib.parse import quote

from netconsole.models.device import Device
from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.services.netmiko_connection import ConnectionTarget, connection_targets, prepared_connection_target, sanitize_sensitive_text
from netconsole.services.settings_tool_validation import SettingsToolPathError, validate_settings_tool_path


class ExternalTerminalType:
    SECURECRT = "securecrt"
    XSHELL = "xshell"
    PUTTY = "putty"
    WINSCP = "winscp"


TERMINAL_LABELS = {
    ExternalTerminalType.SECURECRT: "SecureCRT",
    ExternalTerminalType.XSHELL: "Xshell",
    ExternalTerminalType.PUTTY: "PuTTY",
    ExternalTerminalType.WINSCP: "WinSCP",
}


TERMINAL_SETTING_KEYS = {
    ExternalTerminalType.SECURECRT: "external_terminal/securecrt_path",
    ExternalTerminalType.XSHELL: "external_terminal/xshell_path",
    ExternalTerminalType.PUTTY: "external_terminal/putty_path",
}

WINSCP_SETTING_KEY = "external_terminal/winscp_path"
WINSCP_COMMON_PATHS = (
    r"C:\Program Files (x86)\WinSCP\WinSCP.exe",
    r"C:\Program Files\WinSCP\WinSCP.exe",
)


@dataclass(frozen=True)
class ExternalTerminalConfig:
    terminal_type: str = ExternalTerminalType.SECURECRT
    exe_path: str = ""
    include_password: bool = False


@dataclass(frozen=True)
class ExternalTerminalLaunchResult:
    success: bool
    message: str
    args: list[str]
    safe_command: str = ""


@dataclass(frozen=True)
class WinScpLaunchResult:
    success: bool
    message: str
    args: list[str]
    safe_command: str = ""


class SettingsLike(Protocol):
    def get_value(self, key: str, default: object = None) -> object: ...


def available_external_terminal_configs(settings: SettingsLike) -> list[ExternalTerminalConfig]:
    configs: list[ExternalTerminalConfig] = []
    include_password = bool(settings.get_value("external_terminal/pass_password", False))
    for terminal_type, key in TERMINAL_SETTING_KEYS.items():
        path = str(settings.get_value(key, "") or "").strip()
        if not path:
            continue
        try:
            validated_path = validate_settings_tool_path(terminal_type, path)
        except SettingsToolPathError:
            continue
        configs.append(ExternalTerminalConfig(terminal_type=terminal_type, exe_path=str(validated_path), include_password=include_password))
    return configs


def build_external_terminal_command(
    device: Device,
    target: ConnectionTarget,
    terminal_type: str,
    exe_path: str,
    include_password: bool = False,
) -> list[str]:
    terminal = str(terminal_type or ExternalTerminalType.SECURECRT).casefold()
    exe = str(exe_path or "").strip()
    if not exe:
        raise ValueError("未配置外部终端路径，请先到外部终端配置中设置程序路径。")
    protocol = str(target.protocol or "").casefold()
    host = target.host
    port = str(int(target.port))
    username = str(target.username or "").strip()
    password = str(target.password or "")
    login_host = f"{username}@{host}" if username else host

    if protocol == "ssh":
        if terminal == ExternalTerminalType.SECURECRT:
            args = [exe, "/SSH2", "/P", port, "/L", username, host]
            if include_password and password:
                args.extend(["/PASSWORD", password])
            return args
        if terminal == ExternalTerminalType.XSHELL:
            if include_password and username and password:
                return [exe, "-url", f"ssh://{quote(username)}:{quote(password)}@{host}:{port}"]
            return [exe, "-url", f"ssh://{login_host}:{port}"]
        if terminal == ExternalTerminalType.PUTTY:
            args = [exe, "-ssh", login_host, "-P", port]
            if include_password and password:
                args.extend(["-pw", password])
            return args
        raise ValueError(f"不支持的外部终端类型: {terminal_type}")

    if protocol == "telnet":
        if terminal == ExternalTerminalType.SECURECRT:
            return [exe, "/TELNET", host, port]
        if terminal == ExternalTerminalType.XSHELL:
            return [exe, "-url", f"telnet://{host}:{port}"]
        if terminal == ExternalTerminalType.PUTTY:
            args = [exe, "-telnet", host, "-P", port]
            if include_password and password:
                args.extend(["-pw", password])
            return args
        raise ValueError(f"不支持的外部终端类型: {terminal_type}")

    raise ValueError(f"不支持的连接协议: {target.protocol}")


def find_winscp_exe(settings: SettingsLike | None = None) -> str:
    configured = ""
    if settings is not None:
        configured = str(settings.get_value(WINSCP_SETTING_KEY, "") or "").strip()
    if configured and _is_winscp_exe(configured):
        return configured
    path_candidate = shutil.which("WinSCP.exe") or shutil.which("winscp.exe")
    if path_candidate and _is_winscp_exe(path_candidate):
        return path_candidate
    for candidate in WINSCP_COMMON_PATHS:
        if _is_winscp_exe(candidate):
            return candidate
    return ""


def _is_winscp_exe(path: str) -> bool:
    candidate = Path(path)
    return candidate.name.casefold() == "winscp.exe" and candidate.is_file()


def build_winscp_command(
    device: Device,
    target: ConnectionTarget,
    exe_path: str,
    *,
    include_password: bool = True,
) -> list[str]:
    exe = str(exe_path or "").strip()
    if not exe:
        raise ValueError("未找到 WinSCP，请先配置 WinSCP.exe 路径。")
    if str(target.protocol or "").casefold() != "ssh":
        raise ValueError("当前设备未配置 SSH/SFTP 登录信息。")
    username = quote(str(target.username or ""), safe="")
    password = quote(str(target.password or ""), safe="") if include_password else ""
    auth = username
    if password:
        auth = f"{username}:{password}"
    url = f"sftp://{auth}@{target.host}:{int(target.port)}/" if auth else f"sftp://{target.host}:{int(target.port)}/"
    return [exe, url, "/newinstance"]


def launch_winscp(
    device: Device,
    settings: SettingsLike | None = None,
    sessions: list[object] | None = None,
    *,
    include_password: bool = True,
    preferred_target: ConnectionTarget | None = None,
) -> WinScpLaunchResult:
    exe = find_winscp_exe(settings)
    if not exe:
        return WinScpLaunchResult(False, "未找到 WinSCP，请先配置 WinSCP.exe 路径。", [])
    target = preferred_target or next(
        (item for item in connection_targets(device) if str(item.protocol or "").casefold() == "ssh"),
        None,
    )
    if target is None or not str(target.username or "").strip():
        return WinScpLaunchResult(False, "当前设备未配置 SSH/SFTP 登录信息。", [])
    if include_password and not str(target.password or ""):
        return WinScpLaunchResult(False, "当前设备未配置 SSH 密码，无法自动登录 WinSCP。", [])
    if target.via_tunnel:
        tunnel = ExitStack()
        try:
            prepared = tunnel.enter_context(prepared_connection_target(target))
            args = build_winscp_command(device, prepared, exe, include_password=include_password)
            process = subprocess.Popen(args, shell=False)
            shutdown_manager.register_process(process, "WinSCP", kind="external_tool", shutdown_policy="ignore")
        except Exception as exc:
            tunnel.close()
            return WinScpLaunchResult(False, sanitize_sensitive_text(str(exc), device), [])
        thread = threading.Thread(target=_wait_winscp_via_tunnel, args=(process, tunnel), daemon=True)
        if sessions is not None:
            sessions.append(process)
            sessions.append(thread)
        thread.start()
        return WinScpLaunchResult(True, "已启动 WinSCP。", args, _safe_command(args, device))
    try:
        args = build_winscp_command(device, target, exe, include_password=include_password)
        process = subprocess.Popen(args, shell=False)
        shutdown_manager.register_process(process, "WinSCP", kind="external_tool", shutdown_policy="ignore")
    except Exception as exc:
        return WinScpLaunchResult(False, sanitize_sensitive_text(str(exc), device), [])
    return WinScpLaunchResult(True, "已启动 WinSCP。", args, _safe_command(args, device))


def _wait_winscp_via_tunnel(process: subprocess.Popen[bytes], tunnel: ExitStack) -> None:
    try:
        process.wait()
    finally:
        shutdown_manager.unregister_process(process)
        tunnel.close()


def launch_external_terminal(device: Device, config: ExternalTerminalConfig) -> ExternalTerminalLaunchResult:
    exe = Path(str(config.exe_path or "").strip())
    if not exe.is_file():
        label = TERMINAL_LABELS.get(config.terminal_type, "外部终端")
        return ExternalTerminalLaunchResult(False, f"未找到 {label}，请在外部终端配置中设置程序路径。", [])
    targets = connection_targets(device)
    if not targets:
        return ExternalTerminalLaunchResult(False, "未启用 SSH/Telnet", [])
    target = targets[0]
    if target.via_tunnel:
        return ExternalTerminalLaunchResult(False, "外部终端暂不支持内部临时隧道，请使用直连地址或先配置外部终端可访问的地址。", [])
    try:
        args = build_external_terminal_command(device, target, config.terminal_type, str(exe), config.include_password)
        process = subprocess.Popen(args, shell=False)
        shutdown_manager.register_process(process, TERMINAL_LABELS.get(config.terminal_type, "external_terminal"), kind="external_tool", shutdown_policy="ignore")
    except Exception as exc:
        return ExternalTerminalLaunchResult(False, sanitize_sensitive_text(str(exc), device), [])
    return ExternalTerminalLaunchResult(True, "已启动外部终端", args, _safe_command(args, device))


def _safe_command(args: list[str], device: Device) -> str:
    text = " ".join(sanitize_sensitive_text(str(item), device) for item in args)
    for password in (getattr(device, "ssh_password", ""), getattr(device, "telnet_password", ""), getattr(device, "password", "")):
        raw = str(password or "")
        if raw:
            text = text.replace(raw, "***")
            text = text.replace(quote(raw, safe=""), "***")
    return text
