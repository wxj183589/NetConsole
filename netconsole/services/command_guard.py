from __future__ import annotations

import re

from netconsole.core import app_logger


SAFE_DEVICE_COMMANDS = {
    "screen-length d",
    "screen-length disable",
    "display current-configuration | include sysname",
    "display version",
    "display device",
    "display device manuinfo",
    "display boot-loader",
    "display interface",
    "display interface brief",
    "display transceiver interface",
    "display transceiver manuinfo interface",
    "display transceiver diagnosis interface",
    "display lldp neighbor-information list",
    "display lldp neighbor-information verbose",
}

SAFE_AC_COMMANDS = SAFE_DEVICE_COMMANDS | {
    "display wlan ap all",
    "display wlan ap all address",
    "display wlan ap all radio",
    "display wlan ap unauthenticated",
    "display wlan ap all radio verbose filter bbssid",
    "display wlan ap all lldp",
    "display cpu-usage",
    "display memory",
    "display ip https | include port",
    "display ip https",
}

SAFE_AC_FIT_AP_RESOURCE_COLLECT_COMMANDS = {
    "screen-length disable",
    "display wlan ap all",
    "display wlan ap all address",
    "display wlan ap all radio",
    "display wlan ap unauthenticated",
    "display wlan ap all radio verbose filter bbssid",
    "display wlan ap all lldp",
}

SAFE_AC_INFO_COLLECT_COMMANDS = {
    "screen-length disable",
    "display cpu-usage",
    "display memory",
    "display version",
    "display device",
    "display device manuinfo",
    "display ip https",
    "display ip https | include port",
}

SAFE_FIT_AP_COMMANDS = {
    "screen-length d",
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver interface",
    "display transceiver manuinfo interface",
    "display transceiver diagnosis interface",
    "display interface brief",
}

SAFE_FIT_AP_OPTICAL_COMMANDS = {
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
}

SAFE_OPTICAL_REFRESH_COMMANDS = {
    "screen-length d",
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
    "display interface",
    "display interface brief",
}

SAFE_CONFIG_LIFECYCLE_COMMANDS = {
    "screen-length d",
    "screen-length disable",
    "save force",
    "display current-configuration",
    "display saved-configuration",
}

SAFE_DIAGNOSTIC_DOWNLOAD_COMMANDS = {
    "screen-length d",
    "screen-length disable",
    "display diagnostic-information",
    "n",
}

SAFE_FILE_MANAGEMENT_COMMANDS = {
    "dir flash:/",
    "dir flash:/diagfile/",
}

SAFE_ENABLE_AP_CONSOLE_COMMANDS = {
    "system-view",
    "probe",
    "wlan ap-execute all exec-console enable",
    "return",
    "quit",
}

SAFE_PERSIST_AUTO_AP_COMMANDS = {
    "system-view",
    "wlan auto-ap persistent all",
    "return",
    "quit",
}

CONTEXT_COMMANDS = {
    "device_collect": SAFE_DEVICE_COMMANDS,
    "ac_collect": SAFE_AC_COMMANDS,
    "ac_fit_ap_resource_collect": SAFE_AC_FIT_AP_RESOURCE_COLLECT_COMMANDS,
    "ac_info_collect": SAFE_AC_INFO_COLLECT_COMMANDS,
    "fit_ap_collect": SAFE_FIT_AP_COMMANDS,
    "fit_ap_optical_collect": SAFE_FIT_AP_OPTICAL_COMMANDS,
    "optical_refresh": SAFE_OPTICAL_REFRESH_COMMANDS,
    "config_lifecycle": SAFE_CONFIG_LIFECYCLE_COMMANDS,
    "diagnostic_download": SAFE_DIAGNOSTIC_DOWNLOAD_COMMANDS,
    "file_management": SAFE_FILE_MANAGEMENT_COMMANDS,
    "ac_enable_ap_console": SAFE_ENABLE_AP_CONSOLE_COMMANDS,
    "ac_persist_auto_ap": SAFE_PERSIST_AUTO_AP_COMMANDS,
    "ac_enable_ap_remote_login": SAFE_ENABLE_AP_CONSOLE_COMMANDS,
}

DANGEROUS_PATTERNS = (
    r"\bundo\b",
    r"\breboot\b",
    r"\bno\s+shutdown\b",
    r"\bshutdown\b",
    r"\bsave\b",
    r"\breset\b",
    r"\bdelete\b",
    r"\bformat\b",
    r"\berase\b",
    r"\bcopy\b",
    r"\bmove\b",
    r"\brename\b",
    r"\brestore\b",
    r"\binstall\b",
    r"\bupgrade\b",
    r"\bboot-loader\b",
    r"\bstartup\b",
    r"\blicense\b",
    r"\bpatch\b",
    r"\blocal-user\b",
    r"\bpassword\b",
    r"\bacl\b",
    r"\bvlan\b",
    r"\binterface\b",
    r"\bip\s+route-static\b",
    r"\bftp\b",
    r"\btftp\b",
    r"\bpublic-key\b",
)

PIPE_ALLOWLIST = {
    "display current-configuration | include sysname",
    "display ip https | include port",
    "display wlan ap all radio verbose filter bbssid",
}
DANGEROUS_ALLOWLIST_EXCEPTIONS = {
    "display boot-loader",
    "display interface",
    "display interface brief",
    "display transceiver interface",
    "display transceiver manuinfo interface",
    "display transceiver diagnosis interface",
    "save force",
}


class CommandRejected(ValueError):
    pass


def normalize_command(command: str) -> str:
    return " ".join(str(command or "").strip().split()).casefold()


def command_reject_reason(command: str, context: str) -> str | None:
    normalized = normalize_command(command)
    if not normalized:
        return "empty command"
    if ";" in normalized:
        return "semicolon is not allowed"
    if "|" in normalized and normalized not in PIPE_ALLOWLIST:
        return "pipe is not allowed for this command"
    if normalized not in DANGEROUS_ALLOWLIST_EXCEPTIONS:
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, normalized):
                return f"dangerous command keyword matched: {pattern}"
    allowed = CONTEXT_COMMANDS.get(context)
    if allowed is None:
        return f"unknown command context: {context}"
    if normalized not in allowed:
        return f"command is not in whitelist for context: {context}"
    return None


def is_command_allowed(command: str, context: str) -> bool:
    return command_reject_reason(command, context) is None


def validate_command_list(commands: list[str] | tuple[str, ...], context: str) -> None:
    for command in commands:
        reason = command_reject_reason(command, context)
        if reason:
            log_command_rejected(command, context, reason)
            raise CommandRejected(f"{command}: {reason}")
        app_logger.log_info("COMMAND_ALLOWED", f"context={context}, command={normalize_command(command)}")


def log_command_rejected(command: str, context: str, reason: str) -> None:
    app_logger.log_error("COMMAND_REJECTED", f"context={context}, command={normalize_command(command)}, reason={reason}")
