from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from netconsole.models.device import Device
from netconsole.services.netmiko_connection import ConnectionTarget, connection_targets, sanitize_sensitive_text


class ExternalTerminalType:
    SECURECRT = "securecrt"
    XSHELL = "xshell"
    PUTTY = "putty"
    POWERSHELL = "powershell"


TERMINAL_LABELS = {
    ExternalTerminalType.SECURECRT: "SecureCRT",
    ExternalTerminalType.XSHELL: "Xshell",
    ExternalTerminalType.PUTTY: "PuTTY",
    ExternalTerminalType.POWERSHELL: "PowerShell",
}


TERMINAL_SETTING_KEYS = {
    ExternalTerminalType.SECURECRT: "external_terminal/securecrt_path",
    ExternalTerminalType.XSHELL: "external_terminal/xshell_path",
    ExternalTerminalType.PUTTY: "external_terminal/putty_path",
    ExternalTerminalType.POWERSHELL: "external_terminal/powershell_path",
}


@dataclass(frozen=True)
class ExternalTerminalConfig:
    terminal_type: str = ExternalTerminalType.SECURECRT
    exe_path: str = ""
    include_password: bool = False
    legacy_ssh_compatibility: bool = True
    legacy_ssh_extended_compatibility: bool = False


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
    legacy_ssh_compatibility = bool(settings.get_value("external_terminal/legacy_ssh_compatibility", True))
    legacy_ssh_extended_compatibility = bool(settings.get_value("external_terminal/legacy_ssh_extended_compatibility", False))
    for terminal_type, key in TERMINAL_SETTING_KEYS.items():
        path = str(settings.get_value(key, "") or "").strip()
        resolved = _resolve_terminal_exe(terminal_type, path)
        if resolved:
            configs.append(
                ExternalTerminalConfig(
                    terminal_type=terminal_type,
                    exe_path=resolved,
                    include_password=include_password,
                    legacy_ssh_compatibility=legacy_ssh_compatibility,
                    legacy_ssh_extended_compatibility=legacy_ssh_extended_compatibility,
                )
            )
    return configs


def _resolve_terminal_exe(terminal_type: str, configured_path: str) -> str:
    path = str(configured_path or "").strip()
    if path and Path(path).is_file():
        return path
    if str(terminal_type or "").casefold() == ExternalTerminalType.POWERSHELL:
        return shutil.which("powershell") or ""
    return ""


def resolve_windows_ssh_exe() -> str:
    resolved = shutil.which("ssh")
    if resolved:
        return resolved
    system_ssh = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
    if system_ssh.is_file():
        return str(system_ssh)
    raise ValueError("未找到系统 ssh.exe，请安装 Windows OpenSSH 客户端")


def powershell_quote_single(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_powershell_ssh_command(ssh_exe: str, ssh_args: list[str]) -> str:
    quoted_args = ",".join(powershell_quote_single(arg) for arg in ssh_args)
    return f"& {{ & {powershell_quote_single(ssh_exe)} @({quoted_args}) }}"


def build_legacy_ssh_options(enabled: bool = True, extended: bool = False) -> list[str]:
    if not enabled:
        return []
    options = ["-oHostKeyAlgorithms=+ssh-rsa"]
    if extended:
        options.extend(
            [
                "-oKexAlgorithms=+diffie-hellman-group14-sha1",
                "-oCiphers=+aes128-cbc",
            ]
        )
    return options


def build_external_terminal_command(
    device: Device,
    target: ConnectionTarget,
    terminal_type: str,
    exe_path: str,
    include_password: bool = False,
    legacy_ssh_compatibility: bool = True,
    legacy_ssh_extended_compatibility: bool = False,
) -> list[str]:
    terminal = str(terminal_type or ExternalTerminalType.SECURECRT).casefold()
    exe = str(exe_path or "").strip()
    if not exe:
        raise ValueError("未配置外部终端路径，请先到外部终端设置中配置。")
    protocol = str(target.protocol or "").casefold()
    host = target.host
    port = str(int(target.port))
    username = str(target.username or "").strip()
    password = str(target.password or "")
    ssh_options = build_legacy_ssh_options(legacy_ssh_compatibility, legacy_ssh_extended_compatibility)
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
        if terminal == ExternalTerminalType.POWERSHELL:
            ssh_exe = resolve_windows_ssh_exe()
            command = build_powershell_ssh_command(ssh_exe, [*ssh_options, "-p", port, login_host])
            return [exe, "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
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
        if terminal == ExternalTerminalType.POWERSHELL:
            command = f"telnet {host} {port}"
            return [exe, "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        raise ValueError(f"不支持的外部终端类型: {terminal_type}")
    raise ValueError(f"不支持的连接协议: {target.protocol}")


def launch_external_terminal(device: Device, config: ExternalTerminalConfig) -> ExternalTerminalLaunchResult:
    exe = Path(str(config.exe_path or "").strip())
    if not exe.is_file():
        label = TERMINAL_LABELS.get(config.terminal_type, "外部终端")
        return ExternalTerminalLaunchResult(False, f"未找到 {label}，请在外部终端设置中配置程序路径", [])
    targets = connection_targets(device)
    if not targets:
        return ExternalTerminalLaunchResult(False, "未启用 SSH/Telnet", [])
    target = targets[0]
    if target.via_tunnel:
        return ExternalTerminalLaunchResult(False, "外部终端暂不支持内部临时隧道，请使用直连地址或先配置外部终端可访问的地址。", [])
    try:
        args = build_external_terminal_command(
            device,
            target,
            config.terminal_type,
            str(exe),
            config.include_password,
            config.legacy_ssh_compatibility,
            config.legacy_ssh_extended_compatibility,
        )
        subprocess.Popen(args, shell=False)
    except Exception as exc:
        return ExternalTerminalLaunchResult(False, sanitize_sensitive_text(str(exc), device), [])
    message = "已启动外部终端"
    if config.terminal_type == ExternalTerminalType.POWERSHELL and config.include_password:
        message = "已启动外部终端。PowerShell SSH 不支持安全传递密码，请在终端中手动输入。"
    return ExternalTerminalLaunchResult(True, message, args, _safe_command(args, device))


def _safe_command(args: list[str], device: Device) -> str:
    text = " ".join(sanitize_sensitive_text(str(item), device) for item in args)
    for password in (getattr(device, "ssh_password", ""), getattr(device, "telnet_password", ""), getattr(device, "password", "")):
        raw = str(password or "")
        if raw:
            text = text.replace(raw, "***")
            text = text.replace(quote(raw), "***")
    return text
