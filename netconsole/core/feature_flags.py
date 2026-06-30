from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QWidget

from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureItem, children_of, list_features
from netconsole.core.runtime_environment import app_root


class FeatureDisabledError(RuntimeError):
    pass


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runtime_dir(root: Path | None = None) -> Path:
    return Path(root or app_root()).resolve() / "runtime"


def profiles_dir(root: Path | None = None) -> Path:
    return project_root() / "profiles" / "features" if root is None else Path(root) / "profiles" / "features"


def load_build_info(root: Path | None = None) -> dict[str, str]:
    path = runtime_dir(root) / "build_info.json"
    if not path.exists():
        return {"edition": "dev", "feature_profile": "full"}
    data = _read_json(path)
    return {
        "edition": str(data.get("edition") or "dev"),
        "feature_profile": str(data.get("feature_profile") or "full"),
    }


def is_internal_edition(root: Path | None = None) -> bool:
    return load_build_info(root).get("edition") in {"dev", "internal"}


class FeatureGate:
    def __init__(self, root: Path | None = None, *, allow_local_override: bool | None = None) -> None:
        self.root = Path(root or app_root()).resolve()
        self.build_info = load_build_info(self.root)
        self.allow_local_override = is_internal_edition(self.root) if allow_local_override is None else allow_local_override
        self.profile = str(self.build_info.get("feature_profile") or "full")
        self.features: dict[str, dict[str, bool]] = {}
        self.reload()

    def reload(self) -> None:
        self.features = {
            item.feature_id: {
                "visible": bool(item.default_visible),
                "enabled": bool(item.default_enabled),
            }
            for item in list_features()
        }
        self._merge_file(runtime_dir(self.root) / "feature_flags.json")
        if self.allow_local_override:
            self._merge_file(runtime_dir(self.root) / "feature_flags.local.json")
        if not is_internal_edition(self.root):
            self._force_internal_only_off()

    def is_visible(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        if item.internal_only and not is_internal_edition(self.root):
            return False
        return bool(self.features.get(feature_id, {}).get("visible", item.default_visible))

    def is_enabled(self, feature_id: str) -> bool:
        item = FEATURE_BY_ID.get(feature_id)
        if item is None:
            return False
        if item.internal_only and not is_internal_edition(self.root):
            return False
        state = self.features.get(feature_id, {})
        return bool(state.get("visible", item.default_visible)) and bool(state.get("enabled", item.default_enabled))

    def assert_enabled(self, feature_id: str) -> None:
        if not self.is_enabled(feature_id):
            raise FeatureDisabledError(feature_id)

    def visible_children(self, parent_id: str) -> list[FeatureItem]:
        return [item for item in children_of(parent_id) if self.is_visible(item.feature_id)]

    def state_for(self, feature_id: str) -> dict[str, bool]:
        item = FEATURE_BY_ID[feature_id]
        state = self.features.get(feature_id, {})
        return {
            "visible": bool(state.get("visible", item.default_visible)),
            "enabled": bool(state.get("enabled", item.default_enabled)),
        }

    def _merge_file(self, path: Path) -> None:
        if not path.exists():
            return
        data = _read_json(path)
        self.profile = str(data.get("profile") or self.profile)
        for feature_id, raw_state in dict(data.get("features") or {}).items():
            if feature_id not in FEATURE_BY_ID or not isinstance(raw_state, dict):
                continue
            state = self.features.setdefault(feature_id, {})
            if "visible" in raw_state:
                state["visible"] = bool(raw_state["visible"])
            if "enabled" in raw_state:
                state["enabled"] = bool(raw_state["enabled"])
        self._force_internal_only_off() if self.profile == "customer" else None

    def _force_internal_only_off(self) -> None:
        for item in list_features():
            if item.internal_only:
                self.features[item.feature_id] = {"visible": False, "enabled": False}


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
        if "visible" in raw_state:
            state["visible"] = bool(raw_state["visible"])
        if "enabled" in raw_state:
            state["enabled"] = bool(raw_state["enabled"])
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


def install_runtime_feature_files(root: Path, *, edition: str, profile: str) -> None:
    target_runtime = runtime_dir(root)
    target_runtime.mkdir(parents=True, exist_ok=True)
    (target_runtime / "build_info.json").write_text(
        json.dumps({"edition": edition, "feature_profile": profile}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source = profiles_dir(project_root()) / f"{profile}.json"
    if source.exists():
        shutil.copy2(source, target_runtime / "feature_flags.json")
    else:
        save_profile(target_runtime / "feature_flags.json", profile, default_profile(profile)["features"])


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
