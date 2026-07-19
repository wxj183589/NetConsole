from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureStatus(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEVELOPMENT = "DEVELOPMENT"
    HIDDEN = "HIDDEN"


REMOVED_FEATURE_IDS = frozenset({"module.snmp_center", "module.wifi_survey"})


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
    FeatureItem("module.config_collection", "nav.config_collection", None, "module"),
    FeatureItem("module.file_management", "nav.file_management", None, "module"),
    FeatureItem("module.network_tools", "nav.network_tools", None, "module"),
    FeatureItem("module.command_reference", "nav.command_reference", None, "module"),
    FeatureItem("module.logs", "nav.logs", None, "module"),
    FeatureItem("module.system_settings", "nav.system_settings", None, "module"),
    FeatureItem("module.feature_switch", "system.feature_flags", None, "module", internal_only=True),
    FeatureItem("web.agent_management", "Agent 管理", None, "page"),
    FeatureItem("web.job_center", "任务中心", None, "page"),
    FeatureItem("web.device_management", "设备管理（Web）", "module.devices", "page"),
    FeatureItem("web.device_connection_test", "设备连接测试（Web）", "web.device_management", "action"),
    FeatureItem(
        "web.device_form_connection_test",
        "未保存表单连接测试（Web）",
        "web.device_management",
        "action",
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.device_management_write", "设备管理写操作（Web）", "web.device_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.device_management_collect", "设备采集与诊断（Web）", "web.device_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.device_management_import", "设备导入（Web）", "web.device_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.device_management_export", "设备导出（Web）", "web.device_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.device_management_desktop", "设备桌面联动（Web）", "web.device_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.config_collection", "配置采集中心（Web）", "module.config_collection", "page"),
    FeatureItem("web.config_collection_fetch", "配置采集（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_diff", "配置比较（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_download", "配置文件下载（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_delete", "配置历史删除（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_save_force", "设备保存配置（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_export", "配置报告导出（Web）", "web.config_collection", "action"),
    FeatureItem("web.config_collection_open_directory", "打开配置结果目录（Web）", "web.config_collection", "action"),
    FeatureItem("web.file_management", "设备文件下载（Web）", "module.file_management", "page"),
    FeatureItem("web.file_management_download", "文件下载（Web）", "web.file_management", "action"),
    FeatureItem("web.file_management_local_write", "本地下载目录写操作（Web）", "web.file_management", "action"),
    FeatureItem("web.file_management_remote", "设备文件浏览与下载（Web）", "web.file_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.file_management_desktop_actions", "文件桌面联动（Web）", "web.file_management", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.network_tools", "网络工具（Web）", "module.network_tools", "page"),
    FeatureItem("web.network_tools_toolbox", "小工具与连通性检测（Web）", "web.network_tools", "page"),
    FeatureItem(
        "web.network_tools_wireless_scan",
        "无线扫描（Web）",
        "web.network_tools",
        "page",
    ),
    FeatureItem("web.network_tools_tcp_port_test", "TCP 端口测试（Web）", "web.network_tools_toolbox", "action"),
    FeatureItem("web.ac_management", "AC 管理（Web）", "module.ac", "page"),
    FeatureItem("web.ac_fit_ap_resources", "FIT-AP 资源（Web）", "web.ac_management", "page"),
    FeatureItem(
        "web.ac_online_overview",
        "AP 在线概览（Web）",
        "web.ac_management",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.ac_optical", "光衰（Web）", "web.ac_management", "page"),
    FeatureItem(
        "web.ac_extensions",
        "AP 扩展信息（Web）",
        "web.ac_management",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.ac_extensions_preview", "AP 扩展导入预览（Web）", "web.ac_extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.ac_extensions_apply", "AP 扩展导入确认（Web）", "web.ac_extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.ac_extensions_rollback", "AP 扩展导入回滚（Web）", "web.ac_extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.ac_extensions_export", "AP 扩展导出（Web）", "web.ac_extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.ac_refresh", "AC/FIT-AP 设备更新（Web）", "web.ac_management", "action"),
    FeatureItem("web.ac_fit_ap_delete", "批量删除 FIT-AP（Web）", "web.ac_fit_ap_resources", "action"),
    FeatureItem("web.ac_fit_ap_metadata_import", "导入 FIT-AP 元数据（Web）", "web.ac_fit_ap_resources", "action"),
    FeatureItem("web.ac_fit_ap_metadata_write", "保存 FIT-AP 元数据（Web）", "web.ac_fit_ap_resources", "action"),
    FeatureItem("web.ac_fit_ap_history", "查看 FIT-AP 历史（Web）", "web.ac_fit_ap_resources", "action"),
    FeatureItem("web.ac_open_web", "打开 AC Web 管理（Electron）", "web.ac_management", "action"),
    FeatureItem("web.ac_dangerous_actions", "AC 高风险动作真实闭环（Web）", "web.ac_management", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem(
        "web.ac_config_snapshots",
        "AC 配置快照与对比（Web）",
        "web.ac_management",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.ac_mesh_links", "Mesh-Link 在线监控与真实刷新（Web）", "module.ac", "page"),
    FeatureItem("ac.mesh_link.refresh", "刷新 Mesh-Link", "web.ac_mesh_links", "action"),
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
    FeatureItem("web.online_mr_report_export", "Online MR 报告导出（Web）", "web.online_mr_analysis", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.online_mr_parse", "Online MR 会话解析（Web）", "web.online_mr_analysis", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_transit_base_data", "轨道交通基础资料", "module.rail_transit", "page"),
    FeatureItem("web.train_communication_monitoring", "在线列车通信检测", "module.rail_transit", "page"),
    FeatureItem(
        "web.online_mr_local_control",
        "Web 本地 Online MR 受控启停",
        "web.train_communication_monitoring",
        "action",
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem(
        "web.online_mr_agent_control",
        "Web Agent Online MR 受控启停",
        "web.train_communication_monitoring",
        "action",
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.mesh_analysis", "Mesh 原始日志分析", "module.rail_transit", "page"),
    FeatureItem("web.mesh_analysis_import", "MESH 原始日志导入（Web）", "web.mesh_analysis", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.mesh_analysis_report_export", "MESH 分析报告导出（Web）", "web.mesh_analysis", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_task_control", "轨交 Web 任务控制", "module.rail_transit", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_transit_wireless_dashboard", "轨道交通无线看板", "module.rail_transit", "page"),
    FeatureItem("web.rail_train_online", "列车在线情况（Web）", "module.rail_transit", "page", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_refresh", "列车在线状态与 AP 映射刷新（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_collect", "列车在线连续采集（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_history_export", "列车经过历史导出（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_mapping_write", "列车 MR 映射保存（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_mapping_import", "列车 MR 映射导入（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_train_online_mapping_export", "列车 MR 映射模板导出（Web）", "web.rail_train_online", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem(
        "web.rail_car_network_diagnostic",
        "车内通信检测（Web）",
        "module.rail_transit",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("web.rail_car_network_diagnostic_execute", "车内通信检测执行（Web）", "web.rail_car_network_diagnostic", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_car_network_point_table_write", "车内通信点表维护（Web）", "web.rail_car_network_diagnostic", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_car_network_point_table_export", "车内通信点表导出（Web）", "web.rail_car_network_diagnostic", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_business", "轨旁 AP 业务（Web）", "module.rail_transit", "page", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_business_update", "轨旁 AP 光衰更新（Web）", "web.rail_trackside_ap_business", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_business_export", "轨旁 AP 业务导出（Web）", "web.rail_trackside_ap_business", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_plan", "轨旁 AP 规划（基础资料页签）", "web.rail_transit_base_data", "tab", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_plan_write", "轨旁 AP 规划维护（Web）", "web.rail_trackside_ap_plan", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem("web.rail_trackside_ap_plan_export", "轨旁 AP 规划导出（Web）", "web.rail_trackside_ap_plan", "action", status=FeatureStatus.DEVELOPMENT),
    FeatureItem(
        "web.online_mr_analysis",
        "车载 MR 收集分析（Web）",
        "module.rail_transit",
        "page",
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem(
        "web.rail_transit_base_data_write",
        "轨道交通基础资料受控写入",
        "web.rail_transit_base_data",
        "action",
        status=FeatureStatus.DEVELOPMENT,
    ),
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
    FeatureItem(
        "desktop.native_bridge",
        "Electron Desktop 本机桥接",
        "module.system_settings",
        "action",
    ),
    FeatureItem("system.feature_flags", "system.feature_flags", "module.feature_switch", "page", internal_only=True),
    FeatureItem(
        "web.command_reference",
        "命令说明（Web）",
        "module.command_reference",
        "page",
    ),
    FeatureItem(
        "web.logs",
        "日志中心（Web）",
        "module.logs",
        "page",
    ),
    FeatureItem("web.logs_export", "日志导出（Web）", "web.logs", "action"),
    FeatureItem(
        "web.system_settings",
        "系统设置（Web）",
        "module.system_settings",
        "page",
    ),
    FeatureItem(
        "web.feature_switch",
        "功能开关配置（Web）",
        "system.feature_flags",
        "page",
        default_visible=True,
        default_enabled=True,
        default_client_package=False,
        internal_only=True,
        status=FeatureStatus.DEVELOPMENT,
    ),
)

FEATURE_BY_ID = {item.feature_id: item for item in FEATURES}

PAGE_FEATURE_BY_PAGE_ID = {
    "devices": "module.devices",
    "ac": "module.ac",
    "rail_transit": "module.rail_transit",
    "config_collection": "module.config_collection",
    "file_management": "module.file_management",
    "network_tools": "module.network_tools",
    "command_reference": "module.command_reference",
    "logs": "module.logs",
    "system_settings": "module.system_settings",
    "feature_flags": "module.feature_switch",
}


def get_feature(feature_id: str) -> FeatureItem:
    if feature_id in REMOVED_FEATURE_IDS:
        raise KeyError(f"Removed feature id: {feature_id}")
    try:
        return FEATURE_BY_ID[feature_id]
    except KeyError as exc:
        raise KeyError(f"Unknown feature id: {feature_id}") from exc


def list_features() -> tuple[FeatureItem, ...]:
    return FEATURES


def children_of(parent_id: str) -> list[FeatureItem]:
    return [item for item in FEATURES if item.parent_id == parent_id]
