from __future__ import annotations

import re
from pathlib import Path
from threading import RLock

from netconsole.core.feature_flags import (
    FeatureGate, default_profile, engineer_package_enabled, load_profile,
    normalize_feature_states, save_profile, validate_feature_states,
)
from netconsole.core.feature_registry import FEATURE_BY_ID, list_features
from netconsole.core.i18n import TRANSLATIONS
from netconsole.core.paths import PathResolver
from netconsole.core.settings import DEFAULT_SETTINGS, SettingsStore
from netconsole.models.api.system_settings import (
    FeatureSettingsSnapshotDTO, FeatureSettingsUpdateDTO, FeatureStateDTO,
    SystemSettingsSaveDTO, SystemSettingsSnapshotDTO, SystemSettingsValuesDTO,
)
from netconsole.services.settings_tool_validation import validate_settings_tool_path


_TERMINAL_KEYS = {
    "putty": "external_terminal/putty_path",
    "securecrt": "external_terminal/securecrt_path",
    "xshell": "external_terminal/xshell_path",
}
_TOOL_FIELDS = {
    "iperf3": "iperf_path", "fping": "fping_path", "ipop": "ipop_path",
    "putty": "putty", "securecrt": "securecrt", "xshell": "xshell",
}
_INTERNAL_TITLE_KEY = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$")


def _readable_feature_title(title_key: str) -> str:
    translated = TRANSLATIONS["zh_CN"].get(title_key, title_key)
    if translated != title_key or not _INTERNAL_TITLE_KEY.fullmatch(title_key):
        return translated
    fallback = title_key.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").strip()
    return fallback.title() or "未命名功能"


class SettingsApplicationService:
    def __init__(self, paths: PathResolver, feature_gate: FeatureGate, site_name: str) -> None:
        self.paths = paths
        self.feature_gate = feature_gate
        self.site_name = site_name
        self._lock = RLock()
        self._settings: SettingsStore | None = None

    def get(self) -> SystemSettingsSnapshotDTO:
        with self._lock:
            self._settings = SettingsStore(self.paths)
            return self._snapshot()

    def save(self, payload: SystemSettingsSaveDTO) -> SystemSettingsSnapshotDTO:
        with self._lock:
            self._settings = SettingsStore(self.paths)
            self._validate_paths(payload)
            values = payload.model_dump(exclude={"expected_version"})
            terminal_paths = values.pop("terminal_paths")
            updates = {
                "theme": values["theme"], "language": values["language"],
                "theme_color": values["theme_color"],
                "network_tools/iperf_path": values["iperf_path"],
                "online_mr.fping_path": values["fping_path"],
                "external_tools/ipop_path": values["ipop_path"],
                "external_terminal/type": values["terminal_type"],
                "external_terminal/securecrt_sessions_root": values["securecrt_sessions_root"],
                "external_terminal/default_ssh_port": values["ssh_port"],
                "external_terminal/default_telnet_port": values["telnet_port"],
                "external_terminal/crt_encoding": values["crt_encoding"],
                **{key: terminal_paths[name] for name, key in _TERMINAL_KEYS.items()},
            }
            self._settings.update_explicit(updates, expected_version=payload.expected_version)
            return self._snapshot()

    def reload(self) -> SystemSettingsSnapshotDTO:
        with self._lock:
            self._settings = SettingsStore(self.paths)
            return self._snapshot()

    def feature_settings(self) -> FeatureSettingsSnapshotDTO:
        return self._feature_snapshot()

    def save_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        if not payload.confirmed:
            raise ValueError("保存功能开关前必须确认")
        features = self._feature_map(payload)
        error = validate_feature_states(features)
        if error:
            raise ValueError(error)
        normalized = normalize_feature_states(features)
        self._save_customer_profile(normalized)
        self.feature_gate.reload()
        return self._feature_snapshot(normalized)

    def preview_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        if not payload.confirmed:
            raise ValueError("预览客户配置前必须确认")
        features = self._feature_map(payload)
        error = validate_feature_states(features)
        if error:
            raise ValueError(error)
        normalized = normalize_feature_states(features)
        self.feature_gate.enable_session_customer_preview(normalized, reason="web-settings")
        return self._feature_snapshot(normalized)

    def restore_features(self, *, confirmed: bool) -> FeatureSettingsSnapshotDTO:
        if not confirmed:
            raise ValueError("恢复功能开关前必须确认")
        self.feature_gate.disable_session_customer_preview(reason="web-settings")
        defaults = default_profile("customer")["features"]
        self._save_customer_profile(defaults)
        self.feature_gate.reload()
        return self._feature_snapshot(defaults)

    def _snapshot(self) -> SystemSettingsSnapshotDTO:
        if self._settings is None:
            self._settings = SettingsStore(self.paths)
        return SystemSettingsSnapshotDTO(
            version=self._settings.version, values=self._values(self._settings),
            defaults=self._values(self._settings, defaults=True),
            current_site_name=self.site_name,
            current_site_path=str(self.paths.site_dir(self.site_name)),
        )

    def _values(self, store: SettingsStore, *, defaults: bool = False) -> SystemSettingsValuesDTO:
        source = DEFAULT_SETTINGS if defaults else store.values
        return SystemSettingsValuesDTO(
            theme=str(source["theme"]), language=str(source["language"]),
            theme_color=str(source["theme_color"]),
            iperf_path=str(source.get("network_tools/iperf_path", "") or ""),
            fping_path=str(source.get("online_mr.fping_path", "") or ""),
            ipop_path=str(source.get("external_tools/ipop_path", "") or ""),
            terminal_type=str(source["external_terminal/type"]),
            terminal_paths={name: str(source.get(key, "") or "") for name, key in _TERMINAL_KEYS.items()},
            securecrt_sessions_root=str(source.get("external_terminal/securecrt_sessions_root", "") or ""),
            ssh_port=int(source["external_terminal/default_ssh_port"]),
            telnet_port=int(source["external_terminal/default_telnet_port"]),
            crt_encoding=str(source["external_terminal/crt_encoding"]),
        )

    def _validate_paths(self, payload: SystemSettingsSaveDTO) -> None:
        values = payload.model_dump()
        terminal_paths = values["terminal_paths"]
        for tool_id, field in _TOOL_FIELDS.items():
            value = terminal_paths[field] if tool_id in _TERMINAL_KEYS else values[field]
            if value:
                validate_settings_tool_path(tool_id, value)
        root = payload.securecrt_sessions_root
        if root:
            path = Path(root)
            if not path.is_absolute() or not path.is_dir() or path.is_symlink():
                raise ValueError("SecureCRT 会话根目录必须是已存在的绝对目录")

    def _customer_profile_path(self) -> Path:
        return self.paths.app_root / "config" / "profiles" / "features" / "customer.json"

    def _save_customer_profile(self, features: dict[str, dict[str, bool]]) -> None:
        path = self._customer_profile_path()
        save_profile(
            path,
            "customer",
            features,
            build_options={"engineer_package": engineer_package_enabled(path)},
        )

    def _feature_map(self, payload: FeatureSettingsUpdateDTO) -> dict[str, dict[str, bool]]:
        expected = set(FEATURE_BY_ID)
        actual = {item.feature_id for item in payload.items}
        if actual != expected or len(actual) != len(payload.items):
            raise ValueError("功能开关列表必须完整且不能重复")
        return {item.feature_id: item.model_dump(include={"visible", "enabled", "client_package", "internal_only"}) for item in payload.items}

    def _feature_snapshot(self, features: dict[str, dict[str, bool]] | None = None) -> FeatureSettingsSnapshotDTO:
        if features is None:
            path = self._customer_profile_path()
            features = load_profile(path, "customer") if path.exists() else default_profile("customer")["features"]
        return FeatureSettingsSnapshotDTO(
            items=[
                FeatureStateDTO(
                    feature_id=item.feature_id,
                    title=_readable_feature_title(item.title_key),
                    **features[item.feature_id],
                )
                for item in list_features()
            ],
            preview_active=self.feature_gate.is_customer_preview_active(),
        )


__all__ = ["SettingsApplicationService"]
