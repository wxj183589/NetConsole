from __future__ import annotations

import json
import os
import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any, NamedTuple

from PySide6.QtWidgets import QWidget

from netconsole.core import app_logger
from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureItem, children_of, list_features
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_environment import app_root, is_packaged_runtime


class FeatureDisabledError(RuntimeError):
    pass


PROTECTED_INTERNAL_FEATURE_IDS = {"module.feature_switch", "system.feature_flags"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runtime_dir(root: Path | None = None) -> Path:
    return Path(root or app_root()).resolve() / "runtime"


def profiles_dir(root: Path | None = None) -> Path:
    return project_root() / "profiles" / "features" if root is None else Path(root) / "profiles" / "features"


class BuildInfoResolution(NamedTuple):
    info: dict[str, Any]
    source: str
    embedded_build_info: dict[str, Any]
    embedded_flags: dict[str, Any]
    external_build_info: dict[str, Any]
    embedded_available: bool
    external_runtime_exists: bool


def load_build_info(root: Path | None = None) -> dict[str, Any]:
    return resolve_build_info(root).info


def resolve_build_info(root: Path | None = None) -> BuildInfoResolution:
    app_root_path = Path(root or app_root()).resolve()
    target_runtime = runtime_dir(app_root_path)
    embedded_build_info = _read_embedded_runtime_json(app_root_path, "build_info.json")
    embedded_flags = _read_embedded_runtime_json(app_root_path, "feature_flags.json")
    external_build_info = _read_json(target_runtime / "build_info.json") if (target_runtime / "build_info.json").exists() else {}
    env_info = _env_build_info()
    if env_info:
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
    if source == "dev_default" and is_packaged_runtime():
        app_logger.log_error(
            "FEATURE_GATE_PACKAGED_DEFAULT_FALLBACK_ERROR",
            f"root={app_root_path} runtime_path={target_runtime}",
        )
    return BuildInfoResolution(
        info=info,
        source=source,
        embedded_build_info=embedded_build_info,
        embedded_flags=embedded_flags,
        external_build_info=external_build_info,
        embedded_available=bool(embedded_build_info or embedded_flags),
        external_runtime_exists=target_runtime.exists(),
    )


def is_internal_edition(root: Path | None = None) -> bool:
    return load_build_info(root).get("edition") in {"dev", "internal"}


class FeatureGate:
    def __init__(self, root: Path | None = None, *, allow_local_override: bool | None = None) -> None:
        self.root = Path(root or app_root()).resolve()
        self.resolution = resolve_build_info(self.root)
        self.build_info = self.resolution.info
        self.edition = str(self.build_info.get("edition") or "dev")
        self.allow_local_override = self.edition in {"dev", "internal"} if allow_local_override is None else allow_local_override
        if self.edition == "customer":
            self.allow_local_override = False
        self.base_profile = str(self.build_info.get("feature_profile") or "full")
        self.profile = self.base_profile
        self.features: dict[str, dict[str, bool]] = {}
        self._session_override_profile: str | None = None
        self._session_override_reason = ""
        self._session_override_operator = ""
        self.reload()

    def reload(self) -> None:
        self.profile = self._effective_profile()
        self.features = {
            item.feature_id: {
                "visible": bool(item.default_visible),
                "enabled": bool(item.default_enabled),
            }
            for item in list_features()
        }
        if self._session_override_profile == "full":
            self._merge_data(self._session_full_profile_data())
        elif self.resolution.embedded_flags:
            self._merge_data(self.resolution.embedded_flags)
        if not self.is_session_override_active() and (self.resolution.source == "external_runtime" or self.edition in {"dev", "internal"}):
            self._merge_file(runtime_dir(self.root) / "feature_flags.json")
        if not self.is_session_override_active() and self.allow_local_override:
            self._merge_file(runtime_dir(self.root) / "feature_flags.local.json")
        if not self._internal_only_allowed():
            self._force_internal_only_off()
        self._log_loaded()

    def is_visible(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        if item.internal_only and not self._internal_only_allowed():
            return False
        if self._is_protected_internal_feature(feature_id):
            return True
        return bool(self.features.get(feature_id, {}).get("visible", item.default_visible))

    def is_enabled(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        if item.internal_only and not self._internal_only_allowed():
            return False
        if self._is_protected_internal_feature(feature_id):
            return True
        state = self.features.get(feature_id, {})
        return bool(state.get("visible", item.default_visible)) and bool(state.get("enabled", item.default_enabled))

    def assert_enabled(self, feature_id: str) -> None:
        if not self.is_enabled(feature_id):
            raise FeatureDisabledError(feature_id)

    def visible_children(self, parent_id: str) -> list[FeatureItem]:
        return [item for item in children_of(parent_id) if self.is_visible(item.feature_id)]

    def state_for(self, feature_id: str) -> dict[str, bool]:
        item = FEATURE_BY_ID[feature_id]
        if item.internal_only and not self._internal_only_allowed():
            return {"visible": False, "enabled": False}
        if self._is_protected_internal_feature(feature_id):
            return {"visible": True, "enabled": True}
        state = self.features.get(feature_id, {})
        return {
            "visible": bool(state.get("visible", item.default_visible)),
            "enabled": bool(state.get("enabled", item.default_enabled)),
        }

    def enable_session_full_mode(self, reason: str, operator: str) -> None:
        self._session_override_profile = "full"
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

    def is_session_override_active(self) -> bool:
        return self._session_override_profile is not None

    def current_profile_source(self) -> str:
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
        for feature_id, raw_state in dict(data.get("features") or {}).items():
            if feature_id not in FEATURE_BY_ID or not isinstance(raw_state, dict):
                continue
            state = self.features.setdefault(feature_id, {})
            visible = _bool_override(raw_state.get("visible")) if "visible" in raw_state else None
            enabled = _bool_override(raw_state.get("enabled")) if "enabled" in raw_state else None
            if visible is not None:
                state["visible"] = visible
            if enabled is not None:
                state["enabled"] = enabled
        self._force_internal_only_off() if self.profile == "customer" and not self._internal_only_allowed() else None

    def _force_internal_only_off(self) -> None:
        for item in list_features():
            if item.internal_only:
                self.features[item.feature_id] = {"visible": False, "enabled": False}

    def _session_full_profile_data(self) -> dict[str, Any]:
        data = _read_embedded_runtime_json(self.root, "feature_flags.full.json")
        if data:
            return data
        source = profiles_dir(project_root()) / "full.json"
        return _read_json(source) if source.exists() else default_profile("full")

    def _effective_profile(self) -> str:
        return self._session_override_profile or self.base_profile

    def _internal_only_allowed(self) -> bool:
        return self.edition in {"dev", "internal"} or self.is_session_override_active()

    def _is_protected_internal_feature(self, feature_id: str) -> bool:
        return feature_id in PROTECTED_INTERNAL_FEATURE_IDS and self._internal_only_allowed()

    def _log_loaded(self) -> None:
        app_logger.log_info(
            "FEATURE_GATE_LOADED",
            (
                f"edition={self.edition} feature_profile={self.profile} source={self.current_profile_source()} "
                f"allow_local_override={self.allow_local_override} root={self.root} runtime_path={runtime_dir(self.root)} "
                f"embedded_available={self.resolution.embedded_available} external_runtime_exists={self.resolution.external_runtime_exists}"
            ),
        )


def default_profile(profile: str) -> dict[str, Any]:
    features = {}
    for item in list_features():
        visible = bool(item.default_visible)
        enabled = bool(item.default_enabled)
        if profile == "customer" and item.internal_only:
            visible = False
            enabled = False
        features[item.feature_id] = {"visible": visible, "enabled": enabled}
    return {"schema_version": 1, "profile": profile, "features": features}


def load_profile(path: Path, profile: str) -> dict[str, dict[str, bool]]:
    payload = default_profile(profile)
    data = _read_json(path)
    for feature_id, raw_state in dict(data.get("features") or {}).items():
        if feature_id not in FEATURE_BY_ID or not isinstance(raw_state, dict):
            continue
        state = payload["features"][feature_id]
        visible = _bool_override(raw_state.get("visible")) if "visible" in raw_state else None
        enabled = _bool_override(raw_state.get("enabled")) if "enabled" in raw_state else None
        if visible is not None:
            state["visible"] = visible
        if enabled is not None:
            state["enabled"] = enabled
    if profile == "customer":
        for item in list_features():
            if item.internal_only:
                payload["features"][item.feature_id] = {"visible": False, "enabled": False}
    return payload["features"]


def save_profile(path: Path, profile: str, features: dict[str, dict[str, bool]]) -> None:
    payload = default_profile(profile)
    for item in list_features():
        state = dict(features.get(item.feature_id) or {})
        if profile == "customer" and item.internal_only:
            state = {"visible": False, "enabled": False}
        payload["features"][item.feature_id] = {
            "visible": bool(state.get("visible", item.default_visible)),
            "enabled": bool(state.get("enabled", item.default_enabled)),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def apply_feature_to_widget(feature_gate: FeatureGate, feature_id: str, widget: QWidget, *, hide_when_invisible: bool = True) -> None:
    visible = feature_gate.is_visible(feature_id)
    enabled = feature_gate.is_enabled(feature_id)
    if hide_when_invisible:
        widget.setVisible(visible)
    widget.setEnabled(enabled)
    if visible and not enabled:
        widget.setToolTip("当前版本未开放此功能")


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
    candidates = [
        root / "_internal" / "netconsole" / "assets" / "runtime" / filename,
        root / "netconsole" / "assets" / "runtime" / filename,
    ]
    resource = package_resource_path("assets", "runtime", filename)
    if resource not in candidates:
        candidates.append(resource)
    for path in candidates:
        if path.exists():
            return _read_json(path)
    return {}


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


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
