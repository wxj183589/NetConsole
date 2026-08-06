from __future__ import annotations

import json
import os
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from netconsole.core import app_logger
from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.feature_registry import (
    FEATURE_BY_ID,
    FeatureItem,
    FeatureStatus,
    ancestors_of,
    children_of,
    delivery_dependencies_of,
    dependencies_of,
    list_features,
)
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_environment import app_root, data_root, is_packaged_runtime


class FeatureDisabledError(RuntimeError):
    pass


PROTECTED_INTERNAL_FEATURE_IDS = {"module.feature_switch", "system.feature_flags"}
PACKAGED_CORE_FEATURE_IDS = frozenset(
    {
        "module.logs",
        "module.system_settings",
        "web.job_center",
        "web.logs",
        "web.system_settings",
    }
)
PACKAGED_PRODUCTION_FEATURE_IDS = PACKAGED_CORE_FEATURE_IDS | frozenset(
    {
        "desktop.native_bridge",
        "devices.securecrt_sessions",
        "module.ac",
        "module.command_reference",
        "module.config_collection",
        "module.devices",
        "module.file_management",
        "module.network_tools",
        "module.rail_transit",
        "network_tools.traffic",
        "online_mr.advanced_ping",
        "online_mr.agent_packages",
        "online_mr.analysis_fping_1s",
        "online_mr.analysis_link_details",
        "online_mr.collection_notes",
        "online_mr.iperf_test",
        "rail.online_mr_analysis",
        "rail.online_mr_collection",
        "web.ac_fit_ap_resources",
        "web.ac_management",
        "web.command_reference",
        "web.config_collection",
        "web.config_collection_fetch",
        "web.device_connection_test",
        "web.device_form_connection_test",
        "web.device_management",
        "web.device_management_collect",
        "web.device_management_desktop",
        "web.device_management_export",
        "web.device_management_import",
        "web.device_management_write",
        "web.file_management",
        "web.file_management_desktop_actions",
        "web.file_management_download",
        "web.file_management_remote",
        "web.mesh_analysis",
        "web.mesh_analysis_import",
        "web.mesh_analysis_report_export",
        "web.network_tools",
        "web.online_mr_analysis",
        "web.online_mr_parse",
        "web.online_mr_realtime",
        "web.online_mr_report_export",
        "web.rail_trackside_ap_business",
        "web.rail_trackside_ap_business_export",
        "web.rail_trackside_ap_plan",
        "web.rail_trackside_ap_plan_export",
        "web.rail_trackside_ap_plan_write",
        "web.rail_train_online_collect",
        "web.rail_train_online_history_export",
        "web.rail_train_online_mapping_export",
        "web.rail_train_online_mapping_import",
        "web.rail_train_online_mapping_write",
        "web.rail_train_online_refresh",
        "web.rail_transit_base_data",
        "web.rail_transit_base_data_write",
        "web.train_communication_monitoring",
        "mesh.generate_report",
    }
)
PACKAGED_ENABLED_ONLY_FEATURE_IDS = frozenset(
    {"web.rail_task_control", "web.rail_train_online"}
)
FEATURE_STATE_KEYS = ("visible", "enabled", "client_package", "internal_only")
FEATURE_PROFILE_SCHEMA_VERSION = 2
LEGACY_FORMALIZED_FEATURE_IDS = frozenset(
    {
        "web.ac_dangerous_actions",
        "web.ac_fit_ap_external_terminal",
        "web.rail_trackside_ap_business",
        "web.rail_trackside_ap_business_update",
    }
)


@dataclass(frozen=True)
class FeatureDependencyIssue:
    feature_id: str
    dependency_id: str
    issue_type: str
    message: str
    auto_fix: str | None


def project_root() -> Path:
    return app_root()


def runtime_dir(root: Path | None = None) -> Path:
    target = Path(root or app_root()).resolve()
    if not is_packaged_runtime() and target == app_root():
        return data_root() / "runtime"
    return target / "runtime"


def profiles_dir(root: Path | None = None) -> Path:
    return project_root() / "config" / "profiles" / "features" if root is None else Path(root) / "config" / "profiles" / "features"


class BuildInfoResolution(NamedTuple):
    info: dict[str, Any]
    source: str
    embedded_build_info: dict[str, Any]
    embedded_flags: dict[str, Any]
    external_build_info: dict[str, Any]
    embedded_available: bool
    external_runtime_exists: bool
    embedded_build_info_status: str
    embedded_flags_status: str


class PackagedRuntimeFeaturePolicy:
    """正式包只执行不可编辑的生产基线，并保护桌面核心能力。"""

    def __init__(self, active: bool) -> None:
        self.active = bool(active)

    @property
    def feature_configuration_available(self) -> bool:
        return not self.active

    def apply(self, item: FeatureItem, state: dict[str, bool]) -> dict[str, bool]:
        if not self.active:
            return state
        effective = dict(state)
        if item.feature_id in PACKAGED_CORE_FEATURE_IDS and item.status is FeatureStatus.ENABLED:
            defaults = default_feature_state(item)
            effective.update(visible=defaults["visible"], enabled=defaults["enabled"])
        if (
            item.internal_only
            or item.feature_id in PROTECTED_INTERNAL_FEATURE_IDS
            or item.status in {FeatureStatus.DISABLED, FeatureStatus.HIDDEN, FeatureStatus.DEVELOPMENT}
        ):
            effective.update(visible=False, enabled=False, client_package=False)
        return effective


def load_build_info(root: Path | None = None) -> dict[str, Any]:
    return resolve_build_info(root).info


def resolve_build_info(
    root: Path | None = None,
    *,
    packaged_runtime: bool | None = None,
    runtime_path: Path | None = None,
) -> BuildInfoResolution:
    app_root_path = Path(root or app_root()).resolve()
    target_runtime = (
        Path(runtime_path).resolve()
        if runtime_path is not None
        else runtime_dir(app_root_path)
    )
    packaged = is_packaged_runtime() if packaged_runtime is None else bool(packaged_runtime)
    embedded_build_info, embedded_build_info_status = _resolve_embedded_runtime_json(app_root_path, "build_info.json")
    embedded_flags, embedded_flags_status = _resolve_embedded_runtime_json(app_root_path, "feature_flags.json")
    external_build_info = _read_json(target_runtime / "build_info.json") if (target_runtime / "build_info.json").exists() else {}
    env_info = _env_build_info()
    if packaged and embedded_build_info:
        source = "embedded"
        info = _normalized_build_info(embedded_build_info, "customer", "production")
    elif packaged:
        source = "packaged_registry_fallback"
        info = {"edition": "customer", "feature_profile": "production"}
        app_logger.log_warning(
            "PACKAGED_FEATURE_POLICY_FALLBACK",
            f"component=build_info reason={embedded_build_info_status}",
        )
    elif env_info:
        source = "env_override"
        info = env_info
    elif embedded_build_info:
        source = "embedded"
        info = _normalized_build_info(embedded_build_info, "dev", "full")
    elif external_build_info:
        source = "external_runtime"
        info = _normalized_build_info(external_build_info, "dev", "full")
    else:
        source = "dev_default"
        info = {"edition": "dev", "feature_profile": "full"}
    return BuildInfoResolution(
        info=info,
        source=source,
        embedded_build_info=embedded_build_info,
        embedded_flags=embedded_flags,
        external_build_info=external_build_info,
        embedded_available=bool(embedded_build_info or embedded_flags),
        external_runtime_exists=target_runtime.exists(),
        embedded_build_info_status=embedded_build_info_status,
        embedded_flags_status=embedded_flags_status,
    )


def is_internal_edition(root: Path | None = None) -> bool:
    return load_build_info(root).get("edition") in {"dev", "internal", "engineer"}


class FeatureGate:
    def __init__(
        self,
        root: Path | None = None,
        *,
        allow_local_override: bool | None = None,
        packaged_runtime: bool | None = None,
        runtime_path: Path | None = None,
    ) -> None:
        self.root = Path(root or app_root()).resolve()
        self.runtime_path = (
            Path(runtime_path).resolve()
            if runtime_path is not None
            else runtime_dir(self.root)
        )
        self.packaged_policy = PackagedRuntimeFeaturePolicy(
            is_packaged_runtime() if packaged_runtime is None else packaged_runtime
        )
        self.resolution = resolve_build_info(
            self.root,
            packaged_runtime=self.packaged_policy.active,
            runtime_path=self.runtime_path,
        )
        self.build_info = self.resolution.info
        self.edition = str(self.build_info.get("edition") or "dev")
        self.allow_local_override = self.edition in {"dev", "internal", "engineer"} if allow_local_override is None else allow_local_override
        if self.edition == "customer" or self.packaged_policy.active:
            self.allow_local_override = False
        self.base_profile = str(self.build_info.get("feature_profile") or "full")
        self.profile = self.base_profile
        self.features: dict[str, dict[str, bool]] = {}
        self._session_override_profile: str | None = None
        self._session_customer_preview_features: dict[str, dict[str, bool]] | None = None
        self._session_override_reason = ""
        self._session_override_operator = ""
        self.reload()

    def reload(self) -> None:
        self.profile = self._effective_profile()
        self.features = {item.feature_id: default_feature_state(item) for item in list_features()}
        if self.packaged_policy.active:
            if self.resolution.embedded_flags:
                self._merge_data(self.resolution.embedded_flags)
                app_logger.log_info(
                    "PACKAGED_FEATURE_POLICY_LOADED",
                    f"source=embedded profile={self.profile} feature_count={len(self.features)}",
                )
            else:
                app_logger.log_warning(
                    "PACKAGED_FEATURE_POLICY_FALLBACK",
                    f"component=feature_flags reason={self.resolution.embedded_flags_status} source=registry_defaults",
                )
        elif self._session_customer_preview_features is not None:
            self._merge_data({"features": self._session_customer_preview_features})
        elif self._session_override_profile == "full":
            self._merge_data(self._session_full_profile_data())
        elif self.resolution.embedded_flags:
            self._merge_data(self.resolution.embedded_flags)
        if (
            not self.packaged_policy.active
            and not self.is_session_override_active()
            and not self.is_customer_preview_active()
            and (self.resolution.source == "external_runtime" or self.edition in {"dev", "internal", "engineer"})
        ):
            self._merge_file(self.runtime_path / "feature_flags.json")
        if not self.is_session_override_active() and not self.is_customer_preview_active() and self.allow_local_override:
            self._merge_file(self.runtime_path / "feature_flags.local.json")
        self._log_loaded()

    def is_visible(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        return self._effective_state(feature_id)["visible"]

    def is_enabled(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        return self._effective_state(feature_id)["enabled"]

    def assert_enabled(self, feature_id: str) -> None:
        if not self.is_enabled(feature_id):
            raise FeatureDisabledError(feature_id)

    def visible_children(self, parent_id: str) -> list[FeatureItem]:
        return [item for item in children_of(parent_id) if self.is_visible(item.feature_id)]

    def state_for(self, feature_id: str) -> dict[str, bool]:
        item = FEATURE_BY_ID[feature_id]
        return dict(self._effective_state(item.feature_id))

    def configured_state_for(self, feature_id: str) -> dict[str, bool]:
        item = FEATURE_BY_ID[feature_id]
        return normalize_feature_state(item, self.features.get(feature_id))

    def status_for(self, feature_id: str) -> FeatureStatus:
        return FEATURE_BY_ID[feature_id].status

    def is_in_client_package(self, feature_id: str) -> bool:
        if feature_id not in FEATURE_BY_ID:
            return False
        return self._effective_state(feature_id)["client_package"]

    def enable_session_full_mode(self, reason: str, operator: str) -> None:
        self._assert_feature_configuration_available()
        self._session_override_profile = "full"
        self._session_customer_preview_features = None
        self._session_override_reason = reason
        self._session_override_operator = operator
        self.reload()
        app_logger.log_info(
            "FEATURE_GATE_SESSION_OVERRIDE_ENABLED",
            (
                f"base_edition={self.edition} base_profile={self.base_profile} override_profile=full "
                f"operator={operator} reason={reason} source={self.current_profile_source()} started_at={_now_iso()}"
            ),
        )

    def disable_session_override(self, reason: str = "manual") -> None:
        self._assert_feature_configuration_available()
        if not self._session_override_profile:
            return
        self._session_override_profile = None
        self._session_override_reason = ""
        self._session_override_operator = ""
        self.reload()
        app_logger.log_info(
            "FEATURE_GATE_SESSION_OVERRIDE_DISABLED",
            f"base_edition={self.edition} base_profile={self.base_profile} reason={reason}",
        )

    def enable_session_runtime_preview(self, features: dict[str, dict[str, bool]], *, reason: str = "preview") -> None:
        self._assert_feature_configuration_available()
        self._session_customer_preview_features = normalize_feature_states(features)
        self._session_override_profile = None
        self._session_override_reason = reason
        self._session_override_operator = ""
        self.reload()
        app_logger.log_info("FEATURE_GATE_RUNTIME_PREVIEW_ENABLED", f"reason={reason} feature_count={len(self.features)}")
        _feature_switch_log("runtime preview: on")

    def enable_session_customer_preview(self, features: dict[str, dict[str, bool]], *, reason: str = "preview") -> None:
        self.enable_session_runtime_preview(features, reason=reason)

    def disable_session_runtime_preview(self, reason: str = "manual") -> None:
        self._assert_feature_configuration_available()
        if self._session_customer_preview_features is None:
            return
        self._session_customer_preview_features = None
        self._session_override_reason = ""
        self.reload()
        app_logger.log_info("FEATURE_GATE_RUNTIME_PREVIEW_DISABLED", f"reason={reason}")
        _feature_switch_log("runtime preview: off")

    def disable_session_customer_preview(self, reason: str = "manual") -> None:
        self.disable_session_runtime_preview(reason=reason)

    def is_session_override_active(self) -> bool:
        return self._session_override_profile is not None

    def is_customer_preview_active(self) -> bool:
        return self._session_customer_preview_features is not None

    def is_runtime_preview_active(self) -> bool:
        return self._session_customer_preview_features is not None

    def is_feature_configuration_available(self) -> bool:
        return self.packaged_policy.feature_configuration_available

    def _assert_feature_configuration_available(self) -> None:
        if self.is_feature_configuration_available():
            return
        app_logger.log_warning("FEATURE_CONFIGURATION_DISABLED", "runtime=packaged")
        raise FeatureDisabledError("feature_configuration")

    def current_profile_source(self) -> str:
        if self.is_customer_preview_active():
            return f"{self.resolution.source}+runtime_preview"
        return f"{self.resolution.source}+session_override" if self.is_session_override_active() else self.resolution.source

    def is_admin_unlock_configured(self) -> bool:
        return bool(
            self.build_info.get("admin_unlock_enabled")
            and self.build_info.get("admin_unlock_hash")
            and self.build_info.get("admin_unlock_salt")
        )

    def verify_admin_unlock_password(self, password: str) -> bool:
        if not self.is_admin_unlock_configured():
            app_logger.log_info("FEATURE_GATE_ADMIN_UNLOCK_FAILED", f"source={self.current_profile_source()} reason=not_configured")
            return False
        if verify_admin_unlock_password(self.build_info, password):
            return True
        app_logger.log_info("FEATURE_GATE_ADMIN_UNLOCK_FAILED", f"source={self.current_profile_source()} reason=invalid_password")
        return False

    def _merge_file(self, path: Path) -> None:
        if not path.exists():
            return
        self._merge_data(_read_json(path))

    def _merge_data(self, data: dict[str, Any]) -> None:
        self.profile = str(data.get("profile") or self.profile)
        try:
            schema_version = int(data.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
        normalized_count = 0
        for feature_id, raw_state in dict(data.get("features") or {}).items():
            if feature_id not in FEATURE_BY_ID or not isinstance(raw_state, dict):
                continue
            missing = [key for key in FEATURE_STATE_KEYS if key not in raw_state or _bool_override(raw_state.get(key)) is None]
            if missing:
                normalized_count += len(missing)
            current = self.features.get(feature_id) or default_feature_state(
                FEATURE_BY_ID[feature_id]
            )
            self.features[feature_id] = normalize_feature_state(
                FEATURE_BY_ID[feature_id],
                {
                    **current,
                    **_migrate_legacy_formalized_feature_state(
                        feature_id,
                        raw_state,
                        schema_version=schema_version,
                    ),
                },
            )
        if normalized_count:
            _feature_switch_log(f"normalized missing booleans: {normalized_count}")

    def _force_internal_only_off(self) -> None:
        for item in list_features():
            if item.internal_only:
                state = dict(self.features.get(item.feature_id) or default_feature_state(item))
                state.update({"visible": False, "enabled": False, "client_package": False, "internal_only": True})
                self.features[item.feature_id] = state

    def _session_full_profile_data(self) -> dict[str, Any]:
        data = _read_embedded_runtime_json(self.root, "feature_flags.full.json")
        if data:
            return data
        source = profiles_dir(project_root()) / "full.json"
        return _read_json(source) if source.exists() else default_profile("full")

    def _effective_profile(self) -> str:
        return self._session_override_profile or self.base_profile

    def _internal_only_allowed(self) -> bool:
        return self.edition in {"dev", "internal", "engineer"} or self.is_session_override_active()

    def _is_protected_internal_feature(self, feature_id: str) -> bool:
        return feature_id in PROTECTED_INTERNAL_FEATURE_IDS and self._internal_only_allowed()

    def _is_customer_mode(self) -> bool:
        return self.profile == "customer"

    def _effective_state(self, feature_id: str, seen: set[str] | None = None) -> dict[str, bool]:
        item = FEATURE_BY_ID[feature_id]
        state = normalize_feature_state(item, self.features.get(feature_id))
        if feature_id in PROTECTED_INTERNAL_FEATURE_IDS and self.packaged_policy.active:
            state.update({"visible": False, "enabled": False, "client_package": False, "internal_only": True})
        if self._is_protected_internal_feature(feature_id) and not self._is_customer_mode():
            if not self.packaged_policy.active:
                state.update({"visible": True, "enabled": True, "client_package": False, "internal_only": True})
        for dependency_id in dependencies_of(feature_id):
            seen = set(seen or ())
            if dependency_id in seen:
                app_logger.log_error(
                    "FEATURE_GATE_DEPENDENCY_CYCLE",
                    f"feature={feature_id} dependency={dependency_id}",
                )
            elif dependency_id in FEATURE_BY_ID:
                seen.add(feature_id)
                dependency_state = self._effective_state(dependency_id, seen)
                if dependency_id == item.parent_id:
                    state["visible"] = state["visible"] and dependency_state["visible"]
                state["enabled"] = state["enabled"] and dependency_state["enabled"]
                state["internal_only"] = (
                    state["internal_only"] or dependency_state["internal_only"]
                )
                state["client_package"] = (
                    state["client_package"]
                    and dependency_state["client_package"]
                    and not state["internal_only"]
                    and not dependency_state["internal_only"]
                )
        if (
            not self.packaged_policy.active
            and self._is_customer_mode()
            and (state["internal_only"] or not state["client_package"])
        ):
            state["visible"] = False
            state["enabled"] = False
        if item.status is FeatureStatus.DISABLED:
            state.update({"visible": False, "enabled": False, "client_package": False})
        elif item.status is FeatureStatus.HIDDEN:
            state.update({"visible": False, "enabled": False})
        elif item.status is FeatureStatus.DEVELOPMENT:
            development_allowed = self.edition in {"dev", "internal", "engineer"} and not self.packaged_policy.active
            state.update(
                {
                    "visible": state["visible"] and development_allowed,
                    "enabled": state["enabled"] and development_allowed,
                    "client_package": False,
                }
            )
        state = self.packaged_policy.apply(item, state)
        if not state["enabled"]:
            state["visible"] = False
        return state

    def _log_loaded(self) -> None:
        if self.packaged_policy.active:
            app_logger.log_info(
                "FEATURE_GATE_LOADED",
                (
                    f"runtime=packaged edition={self.edition} feature_profile={self.profile} "
                    f"source={self.current_profile_source()} allow_local_override=false"
                ),
            )
            _feature_switch_log(f"loaded features: {len(self.features)}")
            _feature_switch_log(f"effective state calculated: {len(self.features)}")
            return
        app_logger.log_info(
            "FEATURE_GATE_LOADED",
            (
                f"edition={self.edition} feature_profile={self.profile} source={self.current_profile_source()} "
                f"allow_local_override={self.allow_local_override} root={self.root} runtime_path={self.runtime_path} "
                f"embedded_available={self.resolution.embedded_available} external_runtime_exists={self.resolution.external_runtime_exists}"
            ),
        )
        _feature_switch_log(f"loaded features: {len(self.features)}")
        _feature_switch_log(f"effective state calculated: {len(self.features)}")


def default_feature_state(item: FeatureItem) -> dict[str, bool]:
    internal_only = bool(item.internal_only)
    return normalize_feature_state(
        item,
        {
            "visible": bool(item.default_visible),
            "enabled": bool(item.default_enabled),
            "client_package": bool(item.default_client_package) and not internal_only,
            "internal_only": internal_only,
        },
    )


def _migrate_legacy_formalized_feature_state(
    feature_id: str,
    raw_state: dict[str, Any],
    *,
    schema_version: int = 1,
) -> dict[str, Any]:
    if schema_version >= FEATURE_PROFILE_SCHEMA_VERSION or feature_id not in LEGACY_FORMALIZED_FEATURE_IDS:
        return raw_state
    values = {key: _bool_override(raw_state.get(key)) for key in FEATURE_STATE_KEYS}
    if values["internal_only"] is True or values["client_package"] not in {False, None}:
        return raw_state
    old_disabled_default = values["visible"] is False and values["enabled"] is False
    old_development_default = values["visible"] is True and values["enabled"] is True
    if not (old_disabled_default or old_development_default):
        return raw_state
    return {**raw_state, **default_feature_state(FEATURE_BY_ID[feature_id])}


def normalize_feature_state(item: FeatureItem, raw_state: dict[str, Any] | None = None) -> dict[str, bool]:
    state = {
        "visible": bool(item.default_visible),
        "enabled": bool(item.default_enabled),
        "client_package": bool(item.default_client_package) and not bool(item.internal_only),
        "internal_only": bool(item.internal_only),
    }
    for key in FEATURE_STATE_KEYS:
        if raw_state is None or key not in raw_state:
            continue
        value = _bool_override(raw_state.get(key))
        if value is not None:
            state[key] = value
    if item.internal_only:
        state["internal_only"] = True
    if state["client_package"] and not item.internal_only:
        state["internal_only"] = False
    if state["internal_only"]:
        if state["client_package"]:
            _feature_switch_log(f"[WARN] invalid state fixed: feature={item.feature_id} reason=internal_only_and_client_package")
        state["client_package"] = False
    if not state["enabled"]:
        state["visible"] = False
    if item.status is FeatureStatus.DISABLED:
        state.update({"visible": False, "enabled": False, "client_package": False})
    elif item.status is FeatureStatus.HIDDEN:
        state.update({"visible": False, "enabled": False})
    elif item.status is FeatureStatus.DEVELOPMENT:
        state["client_package"] = False
    return {key: bool(state[key]) for key in FEATURE_STATE_KEYS}


def normalize_feature_states(features: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, bool]]:
    raw_features = features or {}
    normalized: dict[str, dict[str, bool]] = {}
    normalized_missing = 0
    for item in list_features():
        raw_state = raw_features.get(item.feature_id)
        if isinstance(raw_state, dict):
            normalized_missing += sum(1 for key in FEATURE_STATE_KEYS if key not in raw_state or _bool_override(raw_state.get(key)) is None)
            normalized[item.feature_id] = normalize_feature_state(item, raw_state)
        else:
            normalized_missing += len(FEATURE_STATE_KEYS)
            normalized[item.feature_id] = default_feature_state(item)
    if normalized_missing:
        _feature_switch_log(f"normalized missing booleans: {normalized_missing}")
    return normalized


def validate_feature_states(features: dict[str, dict[str, bool]]) -> str:
    for item in list_features():
        raw_state = features.get(item.feature_id) or {}
        raw_internal_only = _bool_override(raw_state.get("internal_only"))
        raw_client_package = _bool_override(raw_state.get("client_package"))
        raw_visible = _bool_override(raw_state.get("visible"))
        raw_enabled = _bool_override(raw_state.get("enabled"))
        if raw_internal_only is True and raw_client_package is True:
            return f"{item.feature_id}: 内部专用功能不能进入客户版打包"
        if raw_enabled is False and raw_visible is True:
            return f"{item.feature_id}: 已禁用功能不能显示入口"
        if raw_client_package is True and raw_internal_only is True:
            return f"{item.feature_id}: 客户版打包功能不能为内部专用"
        state = normalize_feature_state(item, raw_state)
        if state["internal_only"] and state["client_package"]:
            return f"{item.feature_id}: 内部专用功能不能进入客户版打包"
        if not state["enabled"] and state["visible"]:
            return f"{item.feature_id}: 已禁用功能不能显示入口"
        if state["client_package"] and state["internal_only"]:
            return f"{item.feature_id}: 客户版打包功能不能为内部专用"
        if state["enabled"]:
            for dependency_id in dependencies_of(item.feature_id):
                dependency = normalize_feature_state(
                    FEATURE_BY_ID[dependency_id], features.get(dependency_id)
                )
                if not dependency["enabled"]:
                    return f"{item.feature_id}: 依赖功能 {dependency_id} 未启用"
    return ""


def feature_dependency_issues(
    features: dict[str, dict[str, bool]],
    *,
    target: str,
) -> list[FeatureDependencyIssue]:
    normalized = normalize_feature_states(features)
    issues: list[FeatureDependencyIssue] = []
    seen: set[tuple[str, str, str]] = set()

    def append(
        item: FeatureItem,
        dependency_id: str,
        issue_type: str,
        message: str,
        *,
        delivery: bool,
    ) -> None:
        key = (item.feature_id, dependency_id, issue_type)
        if key in seen:
            return
        seen.add(key)
        dependency = FEATURE_BY_ID[dependency_id]
        fixable = not (
            dependency.internal_only
            or dependency.status is not FeatureStatus.ENABLED
        )
        issues.append(
            FeatureDependencyIssue(
                feature_id=item.feature_id,
                dependency_id=dependency_id,
                issue_type=issue_type,
                message=message,
                auto_fix=(
                    "include_dependency_hidden"
                    if delivery and fixable
                    else "enable_dependency_hidden"
                    if fixable
                    else None
                ),
            )
        )

    for item in list_features():
        state = normalized[item.feature_id]
        if state["enabled"]:
            for dependency_id in dependencies_of(item.feature_id):
                if normalized[dependency_id]["enabled"]:
                    continue
                append(
                    item,
                    dependency_id,
                    "runtime_dependency_disabled",
                    f"{item.feature_id} 需要已启用的 {dependency_id}",
                    delivery=False,
                )

        if target != "customer" or not state["client_package"]:
            continue
        if item.internal_only or item.status is not FeatureStatus.ENABLED:
            append(
                item,
                item.feature_id,
                "forbidden_feature_delivery",
                f"{item.feature_id} 是内部或非正式功能，不能进入客户版",
                delivery=True,
            )
            continue
        for parent_id in ancestors_of(item.feature_id):
            if normalized[parent_id]["client_package"]:
                continue
            append(
                item,
                parent_id,
                "delivery_parent_missing",
                f"{item.feature_id} 的交付父级 {parent_id} 未纳入客户版",
                delivery=True,
            )
        for dependency_id in delivery_dependencies_of(item.feature_id):
            if normalized[dependency_id]["client_package"]:
                continue
            append(
                item,
                dependency_id,
                "delivery_dependency_missing",
                f"{item.feature_id} 的交付依赖 {dependency_id} 未纳入客户版",
                delivery=True,
            )
    return issues


def auto_fix_feature_dependencies(
    features: dict[str, dict[str, bool]],
    *,
    target: str,
) -> dict[str, dict[str, bool]]:
    fixed = normalize_feature_states(features)
    for _attempt in range(len(FEATURE_BY_ID) + 1):
        issues = feature_dependency_issues(fixed, target=target)
        fixable = [issue for issue in issues if issue.auto_fix]
        if not fixable:
            return fixed
        changed = False
        for issue in fixable:
            dependency = fixed[issue.dependency_id]
            if issue.auto_fix == "include_dependency_hidden":
                requested = {
                    "visible": False,
                    "enabled": True,
                    "client_package": True,
                }
            else:
                requested = {"visible": False, "enabled": True}
            if any(dependency[key] != value for key, value in requested.items()):
                dependency.update(requested)
                changed = True
        if not changed:
            return fixed
    raise ValueError("功能依赖自动修复未能收敛")


def load_runtime_feature_overrides(path: Path) -> dict[str, dict[str, bool]]:
    data = _read_json(path) if path.exists() else {}
    result: dict[str, dict[str, bool]] = {}
    for feature_id, raw_state in dict(data.get("features") or {}).items():
        if feature_id not in FEATURE_BY_ID or not isinstance(raw_state, dict):
            continue
        values = {
            key: value
            for key in ("visible", "enabled")
            if (value := _bool_override(raw_state.get(key))) is not None
        }
        if values:
            result[feature_id] = values
    return result


def save_runtime_feature_overrides(
    path: Path, features: dict[str, dict[str, bool]]
) -> None:
    payload = {
        "schema_version": FEATURE_PROFILE_SCHEMA_VERSION,
        "features": {
            feature_id: {
                "visible": bool(state["visible"]),
                "enabled": bool(state["enabled"]),
            }
            for feature_id, state in sorted(features.items())
            if feature_id in FEATURE_BY_ID
        },
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with locked_file(path):
        atomic_write_bytes(path, encoded)


def default_profile(profile: str) -> dict[str, Any]:
    features = {}
    for item in list_features():
        features[item.feature_id] = default_feature_state(item)
    return {"schema_version": FEATURE_PROFILE_SCHEMA_VERSION, "profile": profile, "features": features}


def validate_feature_profile_payload(
    payload: dict[str, Any],
    *,
    profile: str,
) -> list[str]:
    errors: list[str] = []
    if payload.get("profile") != profile:
        errors.append(
            f"profile identity mismatch: expected={profile} actual={payload.get('profile')!r}"
        )
    raw_features = payload.get("features")
    if not isinstance(raw_features, dict):
        return [*errors, "features must be an object"]
    unknown = sorted(set(raw_features) - set(FEATURE_BY_ID))
    errors.extend(f"unknown feature: {feature_id}" for feature_id in unknown)
    for feature_id, raw_state in raw_features.items():
        if feature_id not in FEATURE_BY_ID:
            continue
        if not isinstance(raw_state, dict):
            errors.append(f"{feature_id}: state must be an object")
            continue
        for key in FEATURE_STATE_KEYS:
            if not isinstance(raw_state.get(key), bool):
                errors.append(f"{feature_id}: {key} must be boolean")
        item = FEATURE_BY_ID[feature_id]
        if raw_state.get("client_package") is True and (
            item.internal_only or item.status is not FeatureStatus.ENABLED
        ):
            errors.append(
                f"{feature_id}: internal/development/disabled feature leaked into customer delivery"
            )
    if errors:
        return errors
    normalized = normalize_feature_states(raw_features)
    state_error = validate_feature_states(normalized)
    if state_error:
        errors.append(state_error)
    errors.extend(
        issue.message
        for issue in feature_dependency_issues(normalized, target=profile)
    )
    return errors


def load_profile(path: Path, profile: str) -> dict[str, dict[str, bool]]:
    data = _read_json(path)
    features = normalize_feature_states(data.get("features") if isinstance(data.get("features"), dict) else None)
    _feature_switch_log(f"loaded features: {len(features)}")
    return features


def save_profile(
    path: Path,
    profile: str,
    features: dict[str, dict[str, bool]],
    *,
    build_options: dict[str, bool] | None = None,
) -> None:
    normalized = normalize_feature_states(features)
    error = validate_feature_states(normalized)
    if error:
        _feature_switch_log(f"validation error: {error}")
        raise ValueError(error)
    _feature_switch_log("validation passed")
    payload = {
        "schema_version": FEATURE_PROFILE_SCHEMA_VERSION,
        "profile": profile,
        "build_options": {"engineer_package": bool(dict(build_options or {}).get("engineer_package", False))},
        "features": normalized,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with locked_file(path):
        atomic_write_bytes(path, encoded)
    _feature_switch_log(f"saved customer config: {path}")


def engineer_package_enabled(path: Path | None = None) -> bool:
    source = path or (project_root() / "config" / "profiles" / "features" / "customer.json")
    data = _read_json(source) if source.exists() else {}
    options = data.get("build_options") if isinstance(data.get("build_options"), dict) else {}
    return bool(options.get("engineer_package", False))


def install_runtime_feature_files(root: Path, *, edition: str, profile: str, admin_unlock_password: str | None = None) -> None:
    target_runtime = runtime_dir(root)
    target_runtime.mkdir(parents=True, exist_ok=True)
    build_info: dict[str, Any] = {"edition": edition, "feature_profile": profile, "admin_unlock_enabled": False}
    if edition == "customer" and admin_unlock_password:
        build_info.update(hash_admin_unlock_password(admin_unlock_password))
    (target_runtime / "build_info.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source = profiles_dir(project_root()) / f"{profile}.json"
    if source.exists():
        feature_flags = _read_json(source)
    else:
        feature_flags = default_profile(profile)
    if profile == "customer":
        feature_flags["features"] = load_profile(source, "customer") if source.exists() else default_profile("customer")["features"]
    (target_runtime / "feature_flags.json").write_text(json.dumps(feature_flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    full_source = profiles_dir(project_root()) / "full.json"
    session_full_flags = _read_json(full_source) if full_source.exists() else default_profile("full")
    install_embedded_feature_files(root, build_info=build_info, feature_flags=feature_flags, session_full_flags=session_full_flags)


def install_embedded_feature_files(
    root: Path,
    *,
    build_info: dict[str, Any],
    feature_flags: dict[str, Any],
    session_full_flags: dict[str, Any] | None = None,
) -> None:
    target = embedded_runtime_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    (target / "build_info.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "feature_flags.json").write_text(json.dumps(feature_flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if session_full_flags is not None:
        (target / "feature_flags.full.json").write_text(
            json.dumps(session_full_flags, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def embedded_runtime_dir(root: Path | None = None) -> Path:
    base = Path(root or app_root()).resolve()
    internal = base / "_internal"
    if internal.exists() or root is not None:
        return internal / "netconsole" / "assets" / "runtime"
    return package_resource_path("assets", "runtime")


def default_feature_gate() -> FeatureGate:
    root = Path(os.environ.get("NETCONSOLE_APP_ROOT") or app_root()).resolve()
    return FeatureGate(root)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_embedded_runtime_json(root: Path, filename: str) -> dict[str, Any]:
    return _resolve_embedded_runtime_json(root, filename)[0]


def _resolve_embedded_runtime_json(root: Path, filename: str) -> tuple[dict[str, Any], str]:
    candidates = [
        root / "_internal" / "netconsole" / "assets" / "runtime" / filename,
        root / "netconsole" / "assets" / "runtime" / filename,
    ]
    resource = package_resource_path("assets", "runtime", filename)
    if resource not in candidates:
        candidates.append(resource)
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}, "invalid"
            return (data, "valid") if isinstance(data, dict) else ({}, "invalid")
    return {}, "missing"


def _normalized_build_info(data: dict[str, Any], default_edition: str, default_profile: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "edition": str(data.get("edition") or default_edition),
        "feature_profile": str(data.get("feature_profile") or default_profile),
    }
    for key in ("admin_unlock_enabled", "admin_unlock_hash", "admin_unlock_salt", "admin_unlock_iterations"):
        if key in data:
            info[key] = data[key]
    return info


def _env_build_info() -> dict[str, str]:
    edition = os.environ.get("NETCONSOLE_EDITION")
    profile = os.environ.get("NETCONSOLE_FEATURE_PROFILE")
    if not edition and not profile:
        return {}
    return {
        "edition": str(edition or "dev"),
        "feature_profile": str(profile or ("customer" if edition == "customer" else "full")),
    }


def hash_admin_unlock_password(password: str, *, salt: str | None = None, iterations: int = 200_000) -> dict[str, Any]:
    selected_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), selected_salt.encode("utf-8"), iterations).hex()
    return {
        "admin_unlock_enabled": True,
        "admin_unlock_hash": digest,
        "admin_unlock_salt": selected_salt,
        "admin_unlock_iterations": iterations,
    }


def verify_admin_unlock_password(build_info: dict[str, Any], password: str) -> bool:
    try:
        salt = str(build_info["admin_unlock_salt"])
        expected = str(build_info["admin_unlock_hash"])
        iterations = int(build_info.get("admin_unlock_iterations") or 200_000)
    except (KeyError, TypeError, ValueError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return hmac.compare_digest(digest, expected)


def _bool_override(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable", "显示", "启用"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "disabled", "disable", "隐藏", "停用"}:
            return False
        return None
    return None


def _feature_switch_log(message: str) -> None:
    print(f"[FeatureSwitch] {message}")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
