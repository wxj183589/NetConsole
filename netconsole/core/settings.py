from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from netconsole.core.paths import PathResolver


DEFAULT_SETTINGS = {
    "theme": "dark",
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
    "app/close_behavior": "ask",
    "app/tray_notice_shown": False,
    "app/startup_mode": "preload_all",
}
VALID_THEMES = {"light", "dark"}
VALID_CLOSE_BEHAVIORS = {"ask", "minimize_to_tray", "exit"}
VALID_STARTUP_MODES = {"preload_all", "fast_start"}


@dataclass
class SettingsStore:
    paths: PathResolver
    values: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = {**DEFAULT_SETTINGS, **self._read()}
        if self.theme not in VALID_THEMES:
            self.values["theme"] = DEFAULT_SETTINGS["theme"]

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
        return mode if mode in VALID_STARTUP_MODES else "preload_all"

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
