from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
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
    "external_tools/ipop_path": "",
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
_MISSING_VERSION = "missing"


class SettingsError(RuntimeError):
    pass


class SettingsFileInvalidError(SettingsError):
    pass


class SettingsConflictError(SettingsError):
    pass


def _version(raw: bytes | None) -> str:
    return _MISSING_VERSION if raw is None else hashlib.sha256(raw).hexdigest()


def _read_settings_file(path: Path) -> tuple[dict[str, object], bytes | None, str]:
    if not path.exists():
        return {}, None, _MISSING_VERSION
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SettingsFileInvalidError(f"设置文件不可读：{exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SettingsFileInvalidError("设置文件已损坏，已保留原文件并拒绝覆盖") from exc
    if not isinstance(data, dict):
        raise SettingsFileInvalidError("设置文件根节点必须是 JSON object，已保留原文件并拒绝覆盖")
    return data, raw, _version(raw)


def _atomic_write_json(path: Path, values: Mapping[str, object]) -> bytes:
    payload = json.dumps(values, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(path, payload, replace=os.replace)
    return payload


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
    _baseline: dict[str, object] = field(init=False, default_factory=dict, repr=False)
    _dirty_keys: set[str] = field(init=False, default_factory=set, repr=False)
    _version: str = field(init=False, default=_MISSING_VERSION, repr=False)

    def __post_init__(self) -> None:
        persisted, _raw, self._version = _read_settings_file(self.path)
        self.values = {**DEFAULT_SETTINGS, **persisted}
        self._baseline = dict(self.values)
        changed = False
        if self.theme not in VALID_THEMES:
            self.values["theme"] = DEFAULT_SETTINGS["theme"]
            changed = True
        normalized_language = self.language
        if self.values.get("language") != normalized_language:
            self.values["language"] = normalized_language
            changed = True
        if self.values.get("app/startup_mode") == "preload_all":
            self.values["app/startup_mode"] = DEFAULT_SETTINGS["app/startup_mode"]
            changed = True
        terminal_type = normalize_external_terminal_type(self.values.get("external_terminal/type"))
        if self.values.get("external_terminal/type") != terminal_type:
            self.values["external_terminal/type"] = terminal_type
            changed = True
        if changed and self.path.exists():
            self._dirty_keys.update(
                key for key, value in self.values.items() if self._baseline.get(key) != value
            )
            self.save()

    @property
    def path(self) -> Path:
        return self.paths.settings_path

    @property
    def version(self) -> str:
        return self._version

    @property
    def dirty_keys(self) -> frozenset[str]:
        return frozenset(self._dirty_keys)

    @property
    def theme(self) -> str:
        return str(self.values.get("theme") or DEFAULT_SETTINGS["theme"])

    def set_theme(self, theme: str) -> None:
        if theme not in VALID_THEMES:
            raise ValueError(f"unsupported theme: {theme}")
        self._set_and_save("theme", theme)

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
        self._set_and_save("language", language)

    @property
    def theme_color(self) -> str:
        value = str(self.values.get("theme_color") or DEFAULT_SETTINGS["theme_color"])
        return value if value.startswith("#") and len(value) == 7 else str(DEFAULT_SETTINGS["theme_color"])

    def set_theme_color(self, color: str) -> None:
        value = color if str(color).startswith("#") else DEFAULT_SETTINGS["theme_color"]
        self._set_and_save("theme_color", value)

    @property
    def mica_enabled(self) -> bool:
        return bool(self.values.get("mica_enabled"))

    def set_mica_enabled(self, enabled: bool) -> None:
        self._set_and_save("mica_enabled", bool(enabled))

    @property
    def compact_table(self) -> bool:
        return bool(self.values.get("compact_table"))

    def set_compact_table(self, enabled: bool) -> None:
        self._set_and_save("compact_table", bool(enabled))

    def int_value(self, key: str, default: int, minimum: int = 1, maximum: int = 99999) -> int:
        try:
            return max(minimum, min(maximum, int(self.values.get(key, default))))
        except (TypeError, ValueError):
            return default

    def set_int_value(self, key: str, value: int, minimum: int = 1, maximum: int = 99999) -> None:
        self._set_and_save(key, max(minimum, min(maximum, int(value))))

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
        self._set_and_save("app/close_behavior", behavior)

    @property
    def tray_notice_shown(self) -> bool:
        return bool(self.values.get("app/tray_notice_shown"))

    def set_tray_notice_shown(self, shown: bool) -> None:
        self._set_and_save("app/tray_notice_shown", bool(shown))

    @property
    def startup_mode(self) -> str:
        mode = str(self.values.get("app/startup_mode") or DEFAULT_SETTINGS["app/startup_mode"])
        return mode if mode in VALID_STARTUP_MODES else "fast_start"

    def set_startup_mode(self, mode: str) -> None:
        if mode not in VALID_STARTUP_MODES:
            raise ValueError(f"unsupported startup mode: {mode}")
        self._set_and_save("app/startup_mode", mode)

    def set_last_export_path(self, path: str | Path) -> None:
        self._set_and_save("last_export_path", str(path))

    def get_value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        if key == "external_terminal/type":
            value = normalize_external_terminal_type(value)
        self._set_and_save(key, value)

    def update_explicit(
        self,
        values: Mapping[str, object],
        *,
        expected_version: str | None = None,
    ) -> None:
        previous_values = dict(self.values)
        previous_dirty = set(self._dirty_keys)
        try:
            for key, value in values.items():
                if key == "external_terminal/type":
                    value = normalize_external_terminal_type(value)
                self.values[key] = value
                self._dirty_keys.add(key)
            self.save(expected_version=expected_version)
        except Exception:
            self.values = previous_values
            self._dirty_keys = previous_dirty
            raise

    def save(self, *, expected_version: str | None = None) -> None:
        dirty = set(self._dirty_keys)
        dirty.update(
            key
            for key, value in self.values.items()
            if self._baseline.get(key, object()) != value
        )
        if not dirty:
            return
        try:
            with locked_file(self.path):
                persisted, _raw, current_version = _read_settings_file(self.path)
                if expected_version is not None and expected_version != current_version:
                    raise SettingsConflictError("设置版本已过期，请重载后重试")
                if current_version != self._version:
                    conflicts = {
                        key
                        for key in dirty
                        if persisted.get(key, DEFAULT_SETTINGS.get(key))
                        != self._baseline.get(key, DEFAULT_SETTINGS.get(key))
                    }
                    if conflicts:
                        names = ", ".join(sorted(conflicts))
                        raise SettingsConflictError(f"设置已被其他实例修改：{names}")
                merged = {**DEFAULT_SETTINGS, **persisted}
                merged.update({key: self.values[key] for key in dirty})
                raw = _atomic_write_json(self.path, merged)
        except Exception:
            self.values = dict(self._baseline)
            self._dirty_keys.clear()
            raise
        self.values = merged
        self._baseline = dict(merged)
        self._dirty_keys.clear()
        self._version = _version(raw)

    def reload(self) -> None:
        persisted, _raw, version = _read_settings_file(self.path)
        self.values = {**DEFAULT_SETTINGS, **persisted}
        self._baseline = dict(self.values)
        self._dirty_keys.clear()
        self._version = version

    def _read(self) -> dict[str, object]:
        data, _raw, _file_version = _read_settings_file(self.path)
        return data

    def _set_and_save(self, key: str, value: object) -> None:
        previous_values = dict(self.values)
        previous_dirty = set(self._dirty_keys)
        self.values[key] = value
        self._dirty_keys.add(key)
        try:
            self.save()
        except Exception:
            self.values = previous_values
            self._dirty_keys = previous_dirty
            raise
