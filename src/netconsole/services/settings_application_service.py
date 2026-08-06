from __future__ import annotations

import re
from pathlib import Path
from threading import RLock

from netconsole.core.feature_flags import (
    FeatureGate,
    auto_fix_feature_dependencies,
    default_profile,
    engineer_package_enabled,
    feature_dependency_issues,
    load_profile,
    load_runtime_feature_overrides,
    normalize_feature_states,
    profiles_dir,
    save_profile,
    save_runtime_feature_overrides,
    validate_feature_states,
)
from netconsole.core.feature_registry import (
    FEATURE_BY_ID,
    FEATURE_GROUP_TITLE_BY_ID,
    FeatureStatus,
    configuration_layer_of,
    delivery_dependencies_of,
    dependencies_of,
    group_id_of,
    list_features,
)
from netconsole.core.i18n import TRANSLATIONS
from netconsole.core.paths import PathResolver
from netconsole.core.settings import DEFAULT_SETTINGS, SettingsStore
from netconsole.models.api.system_settings import (
    FeatureConfigurationTarget,
    FeatureDependencyIssueDTO,
    FeatureRuntimeStatusDTO,
    FeatureSettingsSnapshotDTO,
    FeatureSettingsUpdateDTO,
    FeatureStateDTO,
    NetworkComponentStatusDTO,
    NetworkComponentsSnapshotDTO,
    NetworkComponentUpdateDTO,
    SystemSettingsSaveDTO,
    SystemSettingsSnapshotDTO,
    SystemSettingsValuesDTO,
)
from netconsole.services.settings_tool_validation import validate_settings_tool_path
from netconsole.services.tool_path_resolver import resolve_network_tool


_TERMINAL_KEYS = {
    "putty": "external_terminal/putty_path",
    "securecrt": "external_terminal/securecrt_path",
    "xshell": "external_terminal/xshell_path",
}
_TERMINAL_FIELDS = {
    "putty": "putty", "securecrt": "securecrt", "xshell": "xshell",
}
_NETWORK_COMPONENT_KEYS = {
    "iperf3": ("network_tools/iperf_path", "network_components/iperf3_mode", "iperf_path"),
    "fping": ("online_mr.fping_path", "network_components/fping_mode", "fping_path"),
}
_INTERNAL_TITLE_KEY = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$")
_CONFIGURATION_NAMES: dict[FeatureConfigurationTarget, str] = {
    "full": "完整版默认配置",
    "customer": "客户版交付配置",
}
_SAVE_EFFECTS: dict[FeatureConfigurationTarget, str] = {
    "full": "仅更新 full.json；当前实例不变，下次构建完整版时生效。",
    "customer": "仅更新 customer.json；当前实例不变，下次构建客户版时生效。",
}


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
                "external_tools/ipop_path": values["ipop_path"],
                "external_terminal/type": values["terminal_type"],
                "external_terminal/securecrt_sessions_root": values["securecrt_sessions_root"],
                "external_terminal/default_ssh_port": values["ssh_port"],
                "external_terminal/default_telnet_port": values["telnet_port"],
                "external_terminal/crt_encoding": values["crt_encoding"],
                **{key: terminal_paths[name] for name, key in _TERMINAL_KEYS.items()},
            }
            updates.update(self._legacy_component_updates(payload, self._settings))
            self._settings.update_explicit(updates, expected_version=payload.expected_version)
            return self._snapshot()

    def reload(self) -> SystemSettingsSnapshotDTO:
        with self._lock:
            self._settings = SettingsStore(self.paths)
            return self._snapshot()

    def network_components(self) -> NetworkComponentsSnapshotDTO:
        with self._lock:
            self._settings = SettingsStore(self.paths)
            return self._network_components_snapshot(self._settings)

    def save_network_component(
        self,
        component_name: str,
        payload: NetworkComponentUpdateDTO,
    ) -> NetworkComponentsSnapshotDTO:
        if component_name not in _NETWORK_COMPONENT_KEYS:
            raise ValueError("不支持的网络测试组件")
        with self._lock:
            self._settings = SettingsStore(self.paths)
            path_key, mode_key, _field = _NETWORK_COMPONENT_KEYS[component_name]
            custom_path = payload.custom_path.strip()
            if payload.mode == "custom":
                if not custom_path:
                    raise ValueError("选择自定义组件时必须提供可执行文件")
                custom_path = str(validate_settings_tool_path(component_name, custom_path))
            else:
                custom_path = ""
            self._settings.update_explicit(
                {path_key: custom_path, mode_key: payload.mode},
                expected_version=payload.expected_version,
            )
            return self._network_components_snapshot(self._settings)

    def feature_settings(
        self,
        target: FeatureConfigurationTarget = "customer",
    ) -> FeatureSettingsSnapshotDTO:
        return self._feature_snapshot(target=target)

    def save_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        if not payload.confirmed:
            raise ValueError("保存功能配置前必须确认")
        target = payload.target
        features = self._feature_map(payload, target=target)
        self._validate_target_states(target, features)
        normalized = normalize_feature_states(features)
        self._save_profile_states(target, normalized)
        return self._feature_snapshot(target=target)

    def check_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        features = normalize_feature_states(self._feature_map(payload, target=payload.target))
        return self._feature_snapshot(target=payload.target, features=features)

    def auto_fix_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        features = normalize_feature_states(self._feature_map(payload, target=payload.target))
        fixed = auto_fix_feature_dependencies(features, target=payload.target)
        return self._feature_snapshot(target=payload.target, features=fixed)

    def preview_features(self, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
        if not payload.confirmed:
            raise ValueError("预览功能配置前必须确认")
        target = payload.target
        features = self._feature_map(payload, target=target)
        self._validate_target_states(target, features)
        normalized = normalize_feature_states(features)
        self.feature_gate.enable_session_runtime_preview(
            normalized,
            reason=f"web-settings-{target}-preview",
        )
        return self._feature_snapshot(target=target, features=normalized)

    def exit_feature_preview(
        self,
        target: FeatureConfigurationTarget = "customer",
    ) -> FeatureSettingsSnapshotDTO:
        self.feature_gate.disable_session_runtime_preview(reason="web-settings-exit")
        return self._feature_snapshot(target=target)

    def restore_features(
        self,
        *,
        confirmed: bool,
        target: FeatureConfigurationTarget = "customer",
    ) -> FeatureSettingsSnapshotDTO:
        if not confirmed:
            raise ValueError("恢复功能配置前必须确认")
        self.feature_gate.disable_session_runtime_preview(reason="web-settings")
        defaults = normalize_feature_states(default_profile(target)["features"])
        self._save_profile_states(target, defaults)
        return self._feature_snapshot(target=target)

    def runtime_feature_status(self) -> FeatureRuntimeStatusDTO:
        local_override_count = len(
            load_runtime_feature_overrides(self._runtime_override_path())
        )
        preview_active = self.feature_gate.is_runtime_preview_active()
        session_override_active = self.feature_gate.is_session_override_active()
        state = (
            "session_preview"
            if preview_active
            else "customer_unlocked"
            if session_override_active
            else "normal"
        )
        return FeatureRuntimeStatusDTO(
            edition=self.feature_gate.edition,
            base_profile=self.feature_gate.base_profile,
            active_profile=self.feature_gate.profile,
            state=state,
            preview_active=preview_active,
            session_override_active=session_override_active,
            local_override_count=local_override_count,
            configuration_available=self.feature_gate.is_feature_configuration_available(),
        )

    def clear_runtime_feature_overrides(self) -> FeatureRuntimeStatusDTO:
        if (
            self.feature_gate.is_feature_configuration_available()
            and self.feature_gate.is_runtime_preview_active()
        ):
            self.feature_gate.disable_session_runtime_preview(
                reason="web-settings-clear-overrides"
            )
        save_runtime_feature_overrides(self._runtime_override_path(), {})
        self.feature_gate.reload()
        return self.runtime_feature_status()

    def reload_feature_gate(self) -> FeatureRuntimeStatusDTO:
        self.feature_gate.reload()
        return self.runtime_feature_status()

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

    def _network_components_snapshot(self, store: SettingsStore) -> NetworkComponentsSnapshotDTO:
        components: list[NetworkComponentStatusDTO] = []
        for component_name in ("iperf3", "fping"):
            resolution = resolve_network_tool(component_name, self.paths, settings=store)
            effective_path = resolution.effective_path
            components.append(
                NetworkComponentStatusDTO(
                    component_name=component_name,
                    mode=resolution.mode,
                    source=resolution.source,
                    configured_path=resolution.configured_path,
                    effective_path=str(effective_path or ""),
                    available=resolution.available,
                    file_exists=bool(effective_path and effective_path.is_file()),
                    fallback_used=resolution.fallback_used,
                    fallback_reason=resolution.fallback_reason,
                    validation_message=resolution.validation_message,
                )
            )
        return NetworkComponentsSnapshotDTO(version=store.version, components=components)

    def _validate_paths(self, payload: SystemSettingsSaveDTO) -> None:
        values = payload.model_dump()
        terminal_paths = values["terminal_paths"]
        for tool_id, field in _TERMINAL_FIELDS.items():
            value = terminal_paths[field]
            if value:
                validate_settings_tool_path(tool_id, value)
        root = payload.securecrt_sessions_root
        if root:
            path = Path(root)
            if not path.is_absolute() or not path.is_dir() or path.is_symlink():
                raise ValueError("SecureCRT 会话根目录必须是已存在的绝对目录")

    @staticmethod
    def _legacy_component_updates(
        payload: SystemSettingsSaveDTO,
        store: SettingsStore,
    ) -> dict[str, object]:
        updates: dict[str, object] = {}
        for component_name, (path_key, mode_key, field) in _NETWORK_COMPONENT_KEYS.items():
            requested = str(getattr(payload, field) or "").strip()
            current = str(store.get_value(path_key, "") or "").strip()
            if requested == current:
                continue
            if requested:
                requested = str(validate_settings_tool_path(component_name, requested))
                updates.update({path_key: requested, mode_key: "custom"})
            else:
                updates.update({path_key: "", mode_key: "builtin"})
        return updates

    def _profile_path(self, target: FeatureConfigurationTarget) -> Path:
        if target not in {"full", "customer"}:
            raise ValueError(f"{target}: 不是打包 Profile")
        return profiles_dir(self.paths.app_root) / f"{target}.json"

    def _customer_profile_path(self) -> Path:
        return self._profile_path("customer")

    def _runtime_override_path(self) -> Path:
        return self.paths.runtime_dir / "feature_flags.local.json"

    def _profile_states(
        self,
        target: FeatureConfigurationTarget,
    ) -> dict[str, dict[str, bool]]:
        path = self._profile_path(target)
        if path.exists():
            return load_profile(path, target)
        return normalize_feature_states(default_profile(target)["features"])

    def _save_profile_states(
        self,
        target: FeatureConfigurationTarget,
        features: dict[str, dict[str, bool]],
    ) -> None:
        path = self._profile_path(target)
        save_profile(
            path,
            target,
            features,
            build_options={
                "engineer_package": engineer_package_enabled(path)
                if target == "customer"
                else False
            },
        )

    def _feature_map(
        self,
        payload: FeatureSettingsUpdateDTO,
        *,
        target: FeatureConfigurationTarget,
    ) -> dict[str, dict[str, bool]]:
        expected = set(FEATURE_BY_ID)
        actual = {item.feature_id for item in payload.items}
        if actual != expected or len(actual) != len(payload.items):
            raise ValueError("功能配置列表必须完整且不能重复")

        baseline = self._profile_states(target)
        result = {feature_id: dict(state) for feature_id, state in baseline.items()}

        for update in payload.items:
            item = FEATURE_BY_ID[update.feature_id]
            requested = {"visible": update.visible, "enabled": update.enabled}
            if item.status is FeatureStatus.DISABLED and update.enabled:
                raise ValueError(f"{update.feature_id}: 已停用功能不能启用")

            result[update.feature_id].update(requested)
            if target == "customer":
                included = bool(update.package_included)
                if included and (
                    item.internal_only
                    or item.status is not FeatureStatus.ENABLED
                ):
                    raise ValueError(f"{update.feature_id}: 内部或非正式功能不能进入客户版")
                result[update.feature_id]["client_package"] = included
                if not included:
                    result[update.feature_id].update(visible=False, enabled=False)
        return result

    def _validate_target_states(
        self,
        target: FeatureConfigurationTarget,
        features: dict[str, dict[str, bool]],
    ) -> None:
        error = validate_feature_states(features)
        if error:
            raise ValueError(error)
        issues = feature_dependency_issues(features, target=target)
        if issues:
            raise ValueError(issues[0].message)

    def _feature_snapshot(
        self,
        *,
        target: FeatureConfigurationTarget = "customer",
        features: dict[str, dict[str, bool]] | None = None,
    ) -> FeatureSettingsSnapshotDTO:
        customer_states = self._profile_states("customer")
        inherited = normalize_feature_states(default_profile(target)["features"])
        configured = features or self._profile_states(target)
        overridden_ids = {
            feature_id
            for feature_id, state in configured.items()
            if any(
                state[key] != inherited[feature_id][key]
                for key in ("visible", "enabled", "client_package", "internal_only")
            )
        }
        issues = feature_dependency_issues(configured, target=target)

        return FeatureSettingsSnapshotDTO(
            items=[
                FeatureStateDTO(
                    feature_id=item.feature_id,
                    title=_readable_feature_title(item.title_key),
                    group_id=group_id_of(item.feature_id),
                    group_title=FEATURE_GROUP_TITLE_BY_ID[group_id_of(item.feature_id)],
                    parent_id=item.parent_id,
                    item_type=item.item_type,
                    configuration_layer=configuration_layer_of(item.feature_id),
                    scope="global",
                    visible=configured[item.feature_id]["visible"],
                    enabled=configured[item.feature_id]["enabled"],
                    inherited_visible=inherited[item.feature_id]["visible"],
                    inherited_enabled=inherited[item.feature_id]["enabled"],
                    client_package=customer_states[item.feature_id]["client_package"],
                    package_included=(
                        configured[item.feature_id]["client_package"]
                        if target == "customer"
                        else customer_states[item.feature_id]["client_package"]
                    ),
                    package_editable=(
                        target == "customer"
                        and not item.internal_only
                        and item.status is FeatureStatus.ENABLED
                        and configuration_layer_of(item.feature_id) != "technical"
                    ),
                    internal_only=configured[item.feature_id]["internal_only"],
                    package_range=self._package_range(item, customer_states[item.feature_id]),
                    status=item.status.value,
                    dependencies=list(dependencies_of(item.feature_id)),
                    delivery_dependencies=list(delivery_dependencies_of(item.feature_id)),
                    locked=self._feature_locked(item, target),
                    lock_reason=self._feature_lock_reason(item, target),
                    overridden=item.feature_id in overridden_ids,
                )
                for item in list_features()
            ],
            target=target,
            preview_active=self.feature_gate.is_runtime_preview_active(),
            configuration_name=_CONFIGURATION_NAMES[target],
            inherited_profile="registry_defaults",
            applies_immediately=False,
            save_effect=_SAVE_EFFECTS[target],
            dependency_issues=[
                FeatureDependencyIssueDTO(
                    feature_id=issue.feature_id,
                    feature_title=_readable_feature_title(
                        FEATURE_BY_ID[issue.feature_id].title_key
                    ),
                    dependency_id=issue.dependency_id,
                    dependency_title=_readable_feature_title(
                        FEATURE_BY_ID[issue.dependency_id].title_key
                    ),
                    issue_type=issue.issue_type,
                    message=issue.message,
                    auto_fix=issue.auto_fix,
                )
                for issue in issues
            ],
        )

    @staticmethod
    def _feature_locked(item, target: FeatureConfigurationTarget) -> bool:
        if item.status is FeatureStatus.DISABLED:
            return True
        if configuration_layer_of(item.feature_id) == "technical":
            return True
        if target == "customer":
            return item.internal_only or item.status is not FeatureStatus.ENABLED
        return False

    @staticmethod
    def _feature_lock_reason(item, target: FeatureConfigurationTarget) -> str:
        if item.status is FeatureStatus.DISABLED:
            return "功能已停用"
        if configuration_layer_of(item.feature_id) == "technical":
            return "技术能力由业务功能和依赖自动带出"
        if target == "customer" and item.internal_only:
            return "内部专用功能不能进入客户版"
        if target == "customer" and item.status is not FeatureStatus.ENABLED:
            return "非正式功能不能进入客户版"
        return ""

    @staticmethod
    def _package_range(item, release_state: dict[str, bool]) -> str:
        if item.status is FeatureStatus.DISABLED:
            return "not_included"
        if item.internal_only:
            return "internal_only"
        if release_state["client_package"]:
            return "customer_internal"
        return "internal"


__all__ = ["SettingsApplicationService"]
