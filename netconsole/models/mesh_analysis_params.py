from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping


MESH_ANALYSIS_PARAMS_METADATA_KEY = "mesh_analysis_params"
SERVICE_TYPE_CHOICES = ("PIS", "信号", "其他")
WIFI_TYPE_CHOICES = ("WiFi5", "WiFi6", "其他")


@dataclass(frozen=True)
class MeshAnalysisParams:
    main_link_switch_time_ms: int = 2500
    short_link_tolerance_ms: int = 500
    merge_same_physical_ap_dual_radio: bool = True
    include_log_boundary_segments: bool = False
    sample_interval_ms: int | None = None
    service_type: str = "PIS"
    wifi_type: str = "WiFi6"

    @property
    def short_link_threshold_ms(self) -> int:
        return max(int(self.main_link_switch_time_ms) - int(self.short_link_tolerance_ms), 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "main_link_switch_time_ms": int(self.main_link_switch_time_ms),
            "short_link_tolerance_ms": int(self.short_link_tolerance_ms),
            "merge_same_physical_ap_dual_radio": bool(self.merge_same_physical_ap_dual_radio),
            "include_log_boundary_segments": bool(self.include_log_boundary_segments),
            "sample_interval_ms": int(self.sample_interval_ms) if self.sample_interval_ms else None,
            "service_type": self.service_type if self.service_type in SERVICE_TYPE_CHOICES else "其他",
            "wifi_type": self.wifi_type if self.wifi_type in WIFI_TYPE_CHOICES else "其他",
        }


DEFAULT_MESH_ANALYSIS_PARAMS = MeshAnalysisParams()


def normalize_mesh_analysis_params(value: object | None) -> MeshAnalysisParams:
    if isinstance(value, MeshAnalysisParams):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            value = {}
    data = value if isinstance(value, Mapping) else {}
    default = DEFAULT_MESH_ANALYSIS_PARAMS
    return MeshAnalysisParams(
        main_link_switch_time_ms=_positive_int(data.get("main_link_switch_time_ms"), default.main_link_switch_time_ms),
        short_link_tolerance_ms=_non_negative_int(data.get("short_link_tolerance_ms"), default.short_link_tolerance_ms),
        merge_same_physical_ap_dual_radio=_bool(data.get("merge_same_physical_ap_dual_radio"), default.merge_same_physical_ap_dual_radio),
        include_log_boundary_segments=_bool(data.get("include_log_boundary_segments"), default.include_log_boundary_segments),
        sample_interval_ms=_optional_positive_int(data.get("sample_interval_ms")),
        service_type=_choice(data.get("service_type"), SERVICE_TYPE_CHOICES, default.service_type),
        wifi_type=_choice(data.get("wifi_type"), WIFI_TYPE_CHOICES, default.wifi_type),
    )


def mesh_analysis_params_to_json(params: MeshAnalysisParams | Mapping[str, object] | str | None) -> str:
    return json.dumps(normalize_mesh_analysis_params(params).to_dict(), ensure_ascii=False, separators=(",", ":"))


def mesh_analysis_params_from_json(value: object | None) -> MeshAnalysisParams:
    return normalize_mesh_analysis_params(value)


def _positive_int(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _non_negative_int(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(number, 0)


def _optional_positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "开启"}:
            return True
        if text in {"0", "false", "no", "off", "关闭"}:
            return False
    if value in (0, 1):
        return bool(value)
    return default


def _choice(value: object, choices: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip()
    return text if text in choices else default
