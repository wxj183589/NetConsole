from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Protocol
from urllib.parse import quote

from netconsole.models.device import Device
from netconsole.services.netmiko_connection import ConnectionTarget, connection_targets, sanitize_sensitive_text


class ExternalTerminalType:
    SECURECRT = "securecrt"
    XSHELL = "xshell"
    PUTTY = "putty"


TERMINAL_LABELS = {
    ExternalTerminalType.SECURECRT: "SecureCRT",
    ExternalTerminalType.XSHELL: "Xshell",
    ExternalTerminalType.PUTTY: "PuTTY",
}


TERMINAL_SETTING_KEYS = {
    ExternalTerminalType.SECURECRT: "external_terminal/securecrt_path",
    ExternalTerminalType.XSHELL: "external_terminal/xshell_path",
    ExternalTerminalType.PUTTY: "external_terminal/putty_path",
}


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


class SettingsLike(Protocol):
    def get_value(self, key: str, default: object = None) -> object: ...


def available_external_terminal_configs(settings: SettingsLike) -> list[ExternalTerminalConfig]:
    configs: list[ExternalTerminalConfig] = []
    include_password = bool(settings.get_value("external_terminal/pass_password", False))
    for terminal_type, key in TERMINAL_SETTING_KEYS.items():
        path = str(settings.get_value(key, "") or "").strip()
        if path and Path(path).is_file():
            configs.append(ExternalTerminalConfig(terminal_type=terminal_type, exe_path=path, include_password=include_password))
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
        subprocess.Popen(args, shell=False)
    except Exception as exc:
        return ExternalTerminalLaunchResult(False, sanitize_sensitive_text(str(exc), device), [])
    return ExternalTerminalLaunchResult(True, "已启动外部终端", args, _safe_command(args, device))


def _safe_command(args: list[str], device: Device) -> str:
    text = " ".join(sanitize_sensitive_text(str(item), device) for item in args)
    for password in (getattr(device, "ssh_password", ""), getattr(device, "telnet_password", ""), getattr(device, "password", "")):
        raw = str(password or "")
        if raw:
            text = text.replace(raw, "***")
            text = text.replace(quote(raw), "***")
    return text
