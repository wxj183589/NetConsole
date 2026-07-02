from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureItem:
    feature_id: str
    title_key: str
    parent_id: str | None
    item_type: str
    default_visible: bool = True
    default_enabled: bool = True
    internal_only: bool = False
    description_key: str | None = None


FEATURES: tuple[FeatureItem, ...] = (
    FeatureItem("module.devices", "nav.devices", None, "module"),
    FeatureItem("module.ac", "nav.ac", None, "module"),
    FeatureItem("module.rail_transit", "nav.rail_transit", None, "module"),
    FeatureItem("module.wifi_survey", "nav.wifi_survey", None, "module"),
    FeatureItem("module.config_collection", "nav.config_collection", None, "module"),
    FeatureItem("module.file_management", "nav.file_management", None, "module"),
    FeatureItem("module.network_tools", "nav.network_tools", None, "module"),
    FeatureItem("module.logs", "nav.logs", None, "module"),
    FeatureItem("module.system_settings", "nav.system_settings", None, "module"),
    FeatureItem("devices.external_terminal", "devices.external_terminal", "module.devices", "button"),
    FeatureItem("devices.securecrt_sessions", "devices.generate_crt_sessions", "module.devices", "button"),
    FeatureItem("rail.train_online", "rail_transit.train_online", "module.rail_transit", "tab"),
    FeatureItem("rail.car_network_diagnostic", "rail_transit.car_network_diagnostic", "module.rail_transit", "tab"),
    FeatureItem("rail.trackside_ap_business", "rail_transit.trackside_ap_service", "module.rail_transit", "tab"),
    FeatureItem("rail.raw_mesh_log_analysis", "mesh_analysis.title", "module.rail_transit", "tab"),
    FeatureItem("rail.online_mr_collection", "rail_transit.online_mr_collection", "module.rail_transit", "tab"),
    FeatureItem("rail.online_mr_analysis", "rail_transit.online_mr_collection_analysis", "module.rail_transit", "tab"),
    FeatureItem("ac.trackside_ap_plan", "ac.trackside_ap_plan", "module.ac", "tab"),
    FeatureItem("ac.ap_online_overview", "ac.ap_online_overview", "module.ac", "tab"),
    FeatureItem("ac.fit_ap_resources", "ac.fit_ap_resources", "module.ac", "tab"),
    FeatureItem("ac.fit_ap_optical", "ac.fit_ap_optical", "module.ac", "tab"),
    FeatureItem("ac.fit_ap_extensions", "ac.fit_ap_extensions", "module.ac", "tab"),
    FeatureItem("file.mesh_log_download", "file_management.mesh_logs", "module.file_management", "button"),
    FeatureItem("file.mesh_auto_import", "file_management.mesh_auto_import", "module.file_management", "button"),
    FeatureItem("file.external_winscp", "file_management.external_winscp", "module.file_management", "button"),
    FeatureItem("online_mr.collect_config_once", "online_mr.collect_config_once", "rail.online_mr_collection", "button"),
    FeatureItem("online_mr.advanced_ping", "online_mr.high_freq_ping", "rail.online_mr_collection", "action"),
    FeatureItem("online_mr.iperf_test", "online_mr.enable_traffic_test", "rail.online_mr_collection", "action"),
    FeatureItem("mesh.generate_report", "mesh_analysis.generate_report", "rail.raw_mesh_log_analysis", "button"),
    FeatureItem("system.feature_flags", "system.feature_flags", "module.system_settings", "page", internal_only=True),
)

FEATURE_BY_ID = {item.feature_id: item for item in FEATURES}

PAGE_FEATURE_BY_PAGE_ID = {
    "devices": "module.devices",
    "ac": "module.ac",
    "rail_transit": "module.rail_transit",
    "wifi_survey": "module.wifi_survey",
    "config_collection": "module.config_collection",
    "file_management": "module.file_management",
    "network_tools": "module.network_tools",
    "logs": "module.logs",
    "feature_flags": "system.feature_flags",
}


def get_feature(feature_id: str) -> FeatureItem:
    try:
        return FEATURE_BY_ID[feature_id]
    except KeyError as exc:
        raise KeyError(f"Unknown feature id: {feature_id}") from exc


def list_features() -> tuple[FeatureItem, ...]:
    return FEATURES


def children_of(parent_id: str) -> list[FeatureItem]:
    return [item for item in FEATURES if item.parent_id == parent_id]
