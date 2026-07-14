from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureStatus(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEVELOPMENT = "DEVELOPMENT"
    HIDDEN = "HIDDEN"


@dataclass(frozen=True)
class FeatureItem:
    feature_id: str
    title_key: str
    parent_id: str | None
    item_type: str
    default_visible: bool = True
    default_enabled: bool = True
    default_client_package: bool = True
    internal_only: bool = False
    description_key: str | None = None
    status: FeatureStatus = FeatureStatus.ENABLED


FEATURES: tuple[FeatureItem, ...] = (
    FeatureItem("module.devices", "nav.devices", None, "module"),
    FeatureItem("module.ac", "nav.ac", None, "module"),
    FeatureItem("module.rail_transit", "nav.rail_transit", None, "module"),
    FeatureItem("module.wifi_survey", "nav.wifi_survey", None, "module", status=FeatureStatus.DISABLED),
    FeatureItem("module.config_collection", "nav.config_collection", None, "module"),
    FeatureItem("module.file_management", "nav.file_management", None, "module"),
    FeatureItem("module.snmp_center", "nav.snmp_center", None, "module", status=FeatureStatus.DISABLED),
    FeatureItem("module.network_tools", "nav.network_tools", None, "module"),
    FeatureItem("module.command_reference", "nav.command_reference", None, "module"),
    FeatureItem("module.logs", "nav.logs", None, "module"),
    FeatureItem("module.system_settings", "nav.system_settings", None, "module"),
    FeatureItem("module.feature_switch", "system.feature_flags", None, "module", internal_only=True),
    FeatureItem("web.agent_management", "Agent 管理", None, "page"),
    FeatureItem("devices.external_terminal", "devices.external_terminal", "module.devices", "button"),
    FeatureItem("devices.securecrt_sessions", "devices.generate_crt_sessions", "module.devices", "button"),
    FeatureItem("devices.omnipeek_name_table_export", "导出 OmniPeek 名称表", "module.devices", "button"),
    FeatureItem("rail.train_online", "rail_transit.train_online", "module.rail_transit", "tab"),
    FeatureItem("rail.car_network_diagnostic", "rail_transit.car_network_diagnostic", "module.rail_transit", "tab"),
    FeatureItem("rail.trackside_ap_business", "rail_transit.trackside_ap_service", "module.rail_transit", "tab"),
    FeatureItem("rail.raw_mesh_log_analysis", "mesh_analysis.title", "module.rail_transit", "tab"),
    FeatureItem("rail.online_mr_collection", "rail_transit.online_mr_collection", "module.rail_transit", "tab"),
    FeatureItem("rail.online_mr_analysis", "rail_transit.online_mr_collection_analysis", "module.rail_transit", "tab"),
    FeatureItem("online_mr.analysis_link_details", "online_mr.link_details", "rail.online_mr_analysis", "tab"),
    FeatureItem("online_mr.analysis_fping_1s", "online_mr.fping_1s_summary", "rail.online_mr_analysis", "tab"),
    FeatureItem("online_mr.collection_notes", "online_mr.collection_note", "rail.online_mr_collection", "action"),
    FeatureItem("online_mr.agent_packages", "online_mr.agent_packages.entry", "rail.online_mr_collection", "action"),
    FeatureItem("web.online_mr_realtime", "车载 MR 实时展示", "rail.online_mr_collection", "page"),
    FeatureItem("ac.trackside_ap_plan", "ac.trackside_ap_plan", "module.ac", "tab"),
    FeatureItem("ac.ap_online_overview", "ac.ap_online_overview", "module.ac", "tab"),
    FeatureItem("ac.fit_ap_resources", "ac.fit_ap_resources", "module.ac", "tab"),
    FeatureItem("ac.ac_info_update", "更新AC信息", "module.ac", "button"),
    FeatureItem("ac.ac_actions", "AC动作", "module.ac", "button"),
    FeatureItem("ac.fit_ap_optical", "ac.fit_ap_optical", "module.ac", "tab"),
    FeatureItem("ac.fit_ap_extensions", "ac.fit_ap_extensions", "module.ac", "tab"),
    FeatureItem("ac.omnipeek_name_table_export", "导出 OmniPeek 名称表", "module.ac", "button"),
    FeatureItem("file.mesh_log_download", "file_management.mesh_logs", "module.file_management", "button"),
    FeatureItem("file.mesh_auto_import", "file_management.mesh_auto_import", "module.file_management", "button"),
    FeatureItem("file.external_winscp", "file_management.external_winscp", "module.file_management", "button"),
    FeatureItem("network_tools.toolbox", "network_tools.toolbox", "module.network_tools", "tab"),
    FeatureItem("network_tools.traffic", "network_tools.traffic", "module.network_tools", "page"),
    FeatureItem("network_tools.wireless_scan", "network_tools.wireless_scan", "module.network_tools", "tab"),
    FeatureItem("network_tools.ipop", "network_tools.ipop", "network_tools.toolbox", "button"),
    FeatureItem("online_mr.advanced_ping", "online_mr.high_freq_ping", "rail.online_mr_collection", "action"),
    FeatureItem("online_mr.iperf_test", "online_mr.enable_traffic_test", "rail.online_mr_collection", "action"),
    FeatureItem("mesh.generate_report", "mesh_analysis.generate_report", "rail.raw_mesh_log_analysis", "button"),
    FeatureItem("system.disk_cleanup", "system.disk_cleanup", "module.system_settings", "page"),
    FeatureItem("system.changelog", "system.changelog", "module.system_settings", "page"),
    FeatureItem("system.open_source", "system.open_source", "module.system_settings", "page"),
    FeatureItem("system.web_console", "system.web_console", "module.system_settings", "action"),
    FeatureItem("system.feature_flags", "system.feature_flags", "module.feature_switch", "page", internal_only=True),
)

FEATURE_BY_ID = {item.feature_id: item for item in FEATURES}

PAGE_FEATURE_BY_PAGE_ID = {
    "devices": "module.devices",
    "ac": "module.ac",
    "rail_transit": "module.rail_transit",
    "wifi_survey": "module.wifi_survey",
    "config_collection": "module.config_collection",
    "file_management": "module.file_management",
    "snmp_center": "module.snmp_center",
    "network_tools": "module.network_tools",
    "command_reference": "module.command_reference",
    "logs": "module.logs",
    "system_settings": "module.system_settings",
    "feature_flags": "module.feature_switch",
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
