from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from netconsole.core.paths import PathResolver


DEFAULT_SETTINGS = {
    "theme": "light",
    "language": "zh_CN",
    "theme_color": "#0078D4",
    "mica_enabled": False,
    "compact_table": False,
    "default_concurrency": 10,
    "command_timeout": 30,
    "log_retention_days": 30,
    "raw_echo_log": True,
    "download_dir": "",
    "backup_dir": "",
    "report_dir": "",
    "network_tools/iperf_path": "",
    "online_mr.fping_path": "",
    "mib_dir": "",
    "last_export_path": "",
    "file_transfer_max_concurrency": 1,
    "trackside_ap/max_device_concurrency": 1000,
    "trackside_ap/max_switch_concurrency": 1000,
    "trackside_ap/max_fit_ap_concurrency": 1000,
    "trackside_ap/connection_timeout_seconds": 10,
    "trackside_ap/command_timeout_seconds": 20,
    "trackside_ap/adaptive_concurrency_enabled": True,
    "trackside_ap/adaptive_retry_enabled": True,
    "trackside_ap/retry_count": 2,
    "trackside_ap/retry_concurrency_floor": 100,
    "trackside_ap/retry_concurrency_ratio": 0.5,
    "external_terminal/type": "securecrt",
    "external_terminal/securecrt_path": "",
    "external_terminal/xshell_path": "",
    "external_terminal/putty_path": "",
    "external_terminal/winscp_path": "",
    "external_terminal/pass_password": False,
    "external_terminal/securecrt_sessions_root": "",
    "external_terminal/securecrt_template_ini": "",
    "external_terminal/default_ssh_port": 22,
    "external_terminal/default_telnet_port": 23,
    "external_terminal/crt_encoding": "UTF-8",
    "app/close_behavior": "ask",
    "app/tray_notice_shown": False,
    "app/startup_mode": "fast_start",
}
VALID_THEMES = {"light", "dark", "auto"}
VALID_LANGUAGES = {"zh_CN", "en_US"}
VALID_CLOSE_BEHAVIORS = {"ask", "minimize_to_tray", "exit"}
VALID_STARTUP_MODES = {"preload_all", "fast_start"}
VALID_EXTERNAL_TERMINAL_TYPES = {"putty", "securecrt", "xshell"}


def normalize_external_terminal_type(value: object) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    mapping = {
        "putty": "putty",
        "securecrt": "securecrt",
        "secure_crt": "securecrt",
        "xshell": "xshell",
        "windows_terminal": "securecrt",
        "windowsterminal": "securecrt",
        "custom": "securecrt",
        "自定义": "securecrt",
    }
    return mapping.get(normalized, "securecrt")


@dataclass
class SettingsStore:
    paths: PathResolver
    values: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = {**DEFAULT_SETTINGS, **self._read()}
        changed = False
        if self.theme not in VALID_THEMES:
            self.values["theme"] = DEFAULT_SETTINGS["theme"]
            changed = True
        if self.language not in VALID_LANGUAGES:
            self.values["language"] = DEFAULT_SETTINGS["language"]
            changed = True
        if self.values.get("app/startup_mode") == "preload_all":
            self.values["app/startup_mode"] = DEFAULT_SETTINGS["app/startup_mode"]
            changed = True
        terminal_type = normalize_external_terminal_type(self.values.get("external_terminal/type"))
        if self.values.get("external_terminal/type") != terminal_type:
            self.values["external_terminal/type"] = terminal_type
            changed = True
        if changed and self.path.exists():
            self.save()

    @property
    def path(self) -> Path:
        return self.paths.settings_path

    @property
    def theme(self) -> str:
        return str(self.values.get("theme") or DEFAULT_SETTINGS["theme"])

    def set_theme(self, theme: str) -> None:
        if theme not in VALID_THEMES:
            raise ValueError(f"unsupported theme: {theme}")
        self.values["theme"] = theme
        self.save()

    @property
    def language(self) -> str:
        language = str(self.values.get("language") or DEFAULT_SETTINGS["language"])
        if language == "zh":
            return "zh_CN"
        if language == "en":
            return "en_US"
        return language if language in VALID_LANGUAGES else str(DEFAULT_SETTINGS["language"])

    def set_language(self, language: str) -> None:
        if language == "zh":
            language = "zh_CN"
        elif language == "en":
            language = "en_US"
        if language not in VALID_LANGUAGES:
            raise ValueError(f"unsupported language: {language}")
        self.values["language"] = language
        self.save()

    @property
    def theme_color(self) -> str:
        value = str(self.values.get("theme_color") or DEFAULT_SETTINGS["theme_color"])
        return value if value.startswith("#") and len(value) == 7 else str(DEFAULT_SETTINGS["theme_color"])

    def set_theme_color(self, color: str) -> None:
        self.values["theme_color"] = color if str(color).startswith("#") else DEFAULT_SETTINGS["theme_color"]
        self.save()

    @property
    def mica_enabled(self) -> bool:
        return bool(self.values.get("mica_enabled"))

    def set_mica_enabled(self, enabled: bool) -> None:
        self.values["mica_enabled"] = bool(enabled)
        self.save()

    @property
    def compact_table(self) -> bool:
        return bool(self.values.get("compact_table"))

    def set_compact_table(self, enabled: bool) -> None:
        self.values["compact_table"] = bool(enabled)
        self.save()

    def int_value(self, key: str, default: int, minimum: int = 1, maximum: int = 99999) -> int:
        try:
            return max(minimum, min(maximum, int(self.values.get(key, default))))
        except (TypeError, ValueError):
            return default

    def set_int_value(self, key: str, value: int, minimum: int = 1, maximum: int = 99999) -> None:
        self.values[key] = max(minimum, min(maximum, int(value)))
        self.save()

    @property
    def last_export_path(self) -> str:
        return str(self.values.get("last_export_path") or "")

    @property
    def file_transfer_max_concurrency(self) -> int:
        try:
            return max(1, int(self.values.get("file_transfer_max_concurrency") or 1))
        except (TypeError, ValueError):
            return 1

    @property
    def close_behavior(self) -> str:
        behavior = str(self.values.get("app/close_behavior") or DEFAULT_SETTINGS["app/close_behavior"])
        return behavior if behavior in VALID_CLOSE_BEHAVIORS else "ask"

    def set_close_behavior(self, behavior: str) -> None:
        if behavior not in VALID_CLOSE_BEHAVIORS:
            raise ValueError(f"unsupported close behavior: {behavior}")
        self.values["app/close_behavior"] = behavior
        self.save()

    @property
    def tray_notice_shown(self) -> bool:
        return bool(self.values.get("app/tray_notice_shown"))

    def set_tray_notice_shown(self, shown: bool) -> None:
        self.values["app/tray_notice_shown"] = bool(shown)
        self.save()

    @property
    def startup_mode(self) -> str:
        mode = str(self.values.get("app/startup_mode") or DEFAULT_SETTINGS["app/startup_mode"])
        return mode if mode in VALID_STARTUP_MODES else "fast_start"

    def set_startup_mode(self, mode: str) -> None:
        if mode not in VALID_STARTUP_MODES:
            raise ValueError(f"unsupported startup mode: {mode}")
        self.values["app/startup_mode"] = mode
        self.save()

    def set_last_export_path(self, path: str | Path) -> None:
        self.values["last_export_path"] = str(path)
        self.save()

    def get_value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        if key == "external_terminal/type":
            value = normalize_external_terminal_type(value)
        self.values[key] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
