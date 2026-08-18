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
    scope: str = "global"
    requires: tuple[str, ...] = ()
    delivery_requires: tuple[str, ...] = ()


FEATURES: tuple[FeatureItem, ...] = (
    FeatureItem("module.devices", "nav.devices", None, "module"),
    FeatureItem("module.ac", "nav.ac", None, "module"),
    FeatureItem("module.rail_transit", "nav.rail_transit", None, "module"),
    FeatureItem("module.config_collection", "nav.config_collection", None, "module"),
    FeatureItem("module.file_management", "nav.file_management", None, "module"),
    FeatureItem("module.network_tools", "nav.network_tools", None, "module"),
    FeatureItem("module.tools", "nav.tools", None, "module"),
    FeatureItem("module.command_reference", "nav.command_reference", None, "module"),
    FeatureItem("module.logs", "nav.logs", None, "module"),
    FeatureItem("module.system_settings", "nav.system_settings", None, "module"),
    FeatureItem(
        "internal.feature_switch",
        "internal.feature_switch",
        None,
        "page",
        default_client_package=False,
        internal_only=True,
    ),
    FeatureItem(
        "internal.task_center",
        "任务中心能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "internal.rail_base_data",
        "轨道交通基础数据能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "internal.rail_task_control",
        "轨道交通任务执行能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "internal.train_online_data",
        "列车在线数据能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "internal.online_mr_analysis",
        "Online MR 分析能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "internal.desktop_bridge",
        "Electron Desktop Bridge 能力",
        None,
        "capability",
        default_visible=False,
    ),
    FeatureItem(
        "module.agent",
        "Agent 管理",
        None,
        "module",
        requires=("internal.task_center",),
        delivery_requires=("internal.task_center",),
    ),
    FeatureItem(
        "module.task_center",
        "任务中心",
        None,
        "module",
        requires=("internal.task_center",),
        delivery_requires=("internal.task_center",),
    ),
    FeatureItem("capability.devices.connection_test", "设备连接测试", "module.devices", "action"),
    FeatureItem(
        "capability.devices.form_connection_test",
        "未保存设备连接测试",
        "module.devices",
        "action",
    ),
    FeatureItem(
        "capability.devices.write",
        "设备管理写操作",
        "module.devices",
        "action",
        requires=("module.devices",),
        delivery_requires=("module.devices",),
    ),
    FeatureItem(
        "capability.devices.collect",
        "设备采集与诊断",
        "module.devices",
        "action",
        requires=("module.devices", "internal.task_center"),
        delivery_requires=("module.devices", "internal.task_center"),
    ),
    FeatureItem("capability.devices.import", "设备导入", "module.devices", "action"),
    FeatureItem("capability.devices.export", "设备导出", "module.devices", "action"),
    FeatureItem("capability.devices.desktop_actions", "设备桌面联动", "module.devices", "action"),
    FeatureItem("capability.config_collection.fetch", "配置采集", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.diff", "配置比较", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.download", "配置文件下载", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.delete", "配置历史删除", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.save_force", "设备保存配置", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.export", "配置报告导出", "module.config_collection", "action"),
    FeatureItem("capability.config_collection.open_directory", "打开配置结果目录", "module.config_collection", "action"),
    FeatureItem("capability.file_management.download", "文件下载", "module.file_management", "action"),
    FeatureItem("capability.file_management.local_write", "本地下载目录写操作", "module.file_management", "action"),
    FeatureItem("capability.file_management.remote", "设备文件浏览与下载", "module.file_management", "action"),
    FeatureItem("capability.file_management.desktop_actions", "文件桌面联动", "module.file_management", "action"),
    FeatureItem("capability.network_tools.toolbox", "小工具与连通性检测", "module.network_tools", "page"),
    FeatureItem(
        "capability.network_tools.wireless_scan",
        "无线扫描",
        "module.network_tools",
        "page",
    ),
    FeatureItem(
        "capability.network_tools.components",
        "网络测试组件",
        "module.network_tools",
        "page",
    ),
    FeatureItem("capability.network_tools.tcp_port_test", "TCP 端口测试", "capability.network_tools.toolbox", "action"),
    FeatureItem("module.fit_ap", "FIT-AP 资源", "module.ac", "module"),
    FeatureItem(
        "capability.ac.online_overview",
        "AP 在线概览",
        "module.ac",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("capability.ac.optical", "光衰", "module.ac", "page"),
    FeatureItem(
        "capability.ac.extensions",
        "AP 扩展信息",
        "module.ac",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("capability.ac.extensions.preview", "AP 扩展导入预览", "capability.ac.extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("capability.ac.extensions.apply", "AP 扩展导入确认", "capability.ac.extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("capability.ac.extensions.rollback", "AP 扩展导入回滚", "capability.ac.extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("capability.ac.extensions.export", "AP 扩展导出", "capability.ac.extensions", "action", default_visible=False, default_enabled=False, default_client_package=False, status=FeatureStatus.DEVELOPMENT),
    FeatureItem("capability.ac.refresh", "AC/FIT-AP 设备更新", "module.ac", "action"),
    FeatureItem("capability.ac.fit_ap.delete", "批量删除 FIT-AP", "module.fit_ap", "action"),
    FeatureItem("capability.ac.fit_ap.metadata_import", "导入 FIT-AP 元数据", "module.fit_ap", "action"),
    FeatureItem("capability.ac.fit_ap.metadata_write", "保存 FIT-AP 元数据", "module.fit_ap", "action"),
    FeatureItem("capability.ac.fit_ap.history", "查看 FIT-AP 历史", "module.fit_ap", "action"),
    FeatureItem("capability.ac.fit_ap.resource_export", "导出 FIT-AP 资源", "module.fit_ap", "action"),
    FeatureItem(
        "capability.ac.external_terminal",
        "打开 FIT-AP 外部终端（Electron）",
        "module.fit_ap",
        "action",
    ),
    FeatureItem("capability.ac.open_management", "打开 AC 管理页面", "module.ac", "action"),
    FeatureItem("capability.ac.dangerous_actions", "AC 高风险动作真实闭环", "module.ac", "action"),
    FeatureItem(
        "capability.ac.config_snapshots",
        "AC 配置快照与对比",
        "module.ac",
        "page",
        default_visible=False,
        default_enabled=False,
        default_client_package=False,
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem(
        "ac.mesh_link.refresh",
        "刷新列车 Mesh-Link",
        "module.train_online",
        "action",
        requires=("internal.train_online_data",),
        delivery_requires=("internal.train_online_data",),
    ),
    FeatureItem("devices.external_terminal", "devices.external_terminal", "module.devices", "button"),
    FeatureItem("devices.securecrt_sessions", "devices.generate_crt_sessions", "module.devices", "button"),
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
    FeatureItem(
        "module.online_mr",
        "车载 MR 实时展示",
        "rail.online_mr_collection",
        "module",
        requires=("internal.task_center", "internal.rail_base_data"),
        delivery_requires=("internal.task_center", "internal.rail_base_data"),
    ),
    FeatureItem("capability.online_mr.report_export", "Online MR 报告导出", "module.online_mr_analysis", "action", requires=("internal.online_mr_analysis",), delivery_requires=("internal.online_mr_analysis",)),
    FeatureItem("capability.online_mr.parse", "Online MR 会话解析", "module.online_mr_analysis", "action", requires=("internal.online_mr_analysis",), delivery_requires=("internal.online_mr_analysis",)),
    FeatureItem("capability.online_mr.open_location", "打开 Online MR 会话本地位置", "module.online_mr_analysis", "action", requires=("internal.online_mr_analysis",), delivery_requires=("internal.online_mr_analysis",)),
    FeatureItem("capability.online_mr.session_delete", "删除 Online MR 历史会话", "module.online_mr_analysis", "action", requires=("internal.online_mr_analysis",), delivery_requires=("internal.online_mr_analysis",)),
    FeatureItem("module.rail_base_data", "轨道交通基础资料", "module.rail_transit", "module", requires=("internal.rail_base_data",), delivery_requires=("internal.rail_base_data",)),
    FeatureItem(
        "module.train_communication",
        "车内通信检测",
        "module.rail_transit",
        "module",
        requires=("internal.rail_base_data", "internal.task_center"),
        delivery_requires=("internal.rail_base_data", "internal.task_center"),
    ),
    FeatureItem(
        "capability.online_mr.local_control",
        "本地 Online MR 受控启停",
        "module.train_communication",
        "action",
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem(
        "capability.online_mr.agent_control",
        "Agent Online MR 受控启停",
        "module.train_communication",
        "action",
        status=FeatureStatus.DEVELOPMENT,
    ),
    FeatureItem("module.mesh_analysis", "Mesh 原始日志分析", "module.rail_transit", "module"),
    FeatureItem("capability.mesh.import", "MESH 原始日志导入", "module.mesh_analysis", "action"),
    FeatureItem("capability.mesh.report_export", "MESH 分析报告导出", "module.mesh_analysis", "action"),
    FeatureItem("capability.mesh.coverage_audit", "MESH AP 覆盖核查", "module.mesh_analysis", "action"),
    FeatureItem("capability.mesh.source_open_location", "打开 MESH 原始日志本地目录", "module.mesh_analysis", "action"),
    FeatureItem("capability.rail_transit.task_control", "轨交任务控制", "module.rail_transit", "action", requires=("internal.rail_task_control",), delivery_requires=("internal.rail_task_control",)),
    FeatureItem("capability.rail_transit.wireless_dashboard", "轨道交通无线看板", "module.rail_transit", "page"),
    FeatureItem("module.train_online", "列车在线情况", "module.rail_transit", "module", requires=("internal.train_online_data",), delivery_requires=("internal.train_online_data",)),
    FeatureItem(
        "module.ground_unattended",
        "地面无人值守",
        "module.rail_transit",
        "page",
        requires=(
            "internal.task_center",
            "internal.rail_base_data",
            "internal.train_online_data",
        ),
        delivery_requires=(
            "internal.task_center",
            "internal.rail_base_data",
            "internal.train_online_data",
        ),
    ),
    FeatureItem("capability.train_online.refresh", "列车在线状态与 AP 映射刷新", "module.train_online", "action"),
    FeatureItem("capability.train_online.collect", "列车在线连续采集", "module.train_online", "action"),
    FeatureItem("capability.train_online.history_export", "列车经过历史导出", "module.train_online", "action"),
    FeatureItem("capability.train_online.mapping_write", "列车 MR 映射保存", "module.train_online", "action"),
    FeatureItem("capability.train_online.mapping_import", "列车 MR 映射导入", "module.train_online", "action"),
    FeatureItem("capability.train_online.mapping_export", "列车 MR 映射模板导出", "module.train_online", "action"),
    FeatureItem("capability.train_communication.diagnostic_execute", "车内通信检测执行", "module.train_communication", "action"),
    FeatureItem("capability.train_communication.point_table_write", "在线列车车内通信点表维护", "module.train_communication", "action"),
    FeatureItem("capability.train_communication.point_table_export", "在线列车车内通信点表导出", "module.train_communication", "action"),
    FeatureItem("module.trackside_ap", "轨旁 AP 业务", "module.rail_transit", "module"),
    FeatureItem("capability.trackside_ap.update", "轨旁 AP 光衰更新", "module.trackside_ap", "action"),
    FeatureItem("capability.trackside_ap.export", "轨旁 AP 业务导出", "module.trackside_ap", "action"),
    FeatureItem(
        "capability.trackside_ap.wps_sync",
        "轨旁 AP 业务 WPS 云同步",
        "module.trackside_ap",
        "action",
        requires=("internal.rail_task_control",),
        delivery_requires=("internal.rail_task_control",),
    ),
    FeatureItem(
        "rail.zte_trackside_switch_adapter",
        "ZTE 轨旁交换机适配",
        "module.trackside_ap",
        "action",
        description_key="ZXR10 C89E-4 Release 已完成只读实机验证；其他型号仍需逐型号复核",
        requires=("internal.rail_task_control",),
        delivery_requires=("internal.rail_task_control",),
    ),
    FeatureItem("capability.trackside_ap.plan", "轨旁 AP 规划（基础资料页签）", "module.rail_base_data", "tab"),
    FeatureItem("capability.trackside_ap.plan_write", "轨旁 AP 规划维护", "capability.trackside_ap.plan", "action"),
    FeatureItem("capability.trackside_ap.plan_export", "轨旁 AP 规划导出", "capability.trackside_ap.plan", "action"),
    FeatureItem("capability.trackside_ap.base_io", "轨旁 AP 基础资料导入导出", "module.rail_base_data", "action"),
    FeatureItem(
        "module.online_mr_analysis",
        "车载 MR 收集分析",
        "module.rail_transit",
        "module",
        requires=("internal.online_mr_analysis",),
        delivery_requires=("internal.online_mr_analysis",),
    ),
    FeatureItem(
        "capability.rail_base_data.write",
        "轨道交通基础资料受控写入",
        "module.rail_base_data",
        "action",
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
    FeatureItem(
        "capability.desktop_native_integration",
        "Electron Desktop 本机桥接",
        "module.system_settings",
        "action",
        requires=("internal.desktop_bridge",),
        delivery_requires=("internal.desktop_bridge",),
    ),
    FeatureItem("capability.logs.export", "日志导出", "module.logs", "action"),
    FeatureItem(
        "module.database_upgrade",
        "数据库升级与备份",
        "module.system_settings",
        "page",
    ),
    FeatureItem("capability.database_upgrade.start", "启动数据库升级", "module.database_upgrade", "action"),
    FeatureItem("capability.database_upgrade.backup_validate", "验证数据库备份", "module.database_upgrade", "action"),
    FeatureItem("capability.database_upgrade.backup_restore", "恢复数据库备份", "module.database_upgrade", "action"),
    FeatureItem("capability.database_upgrade.backup_delete", "删除数据库备份", "module.database_upgrade", "action"),
    FeatureItem("capability.database_upgrade.backup_open_directory", "打开数据库备份目录", "module.database_upgrade", "action"),
    FeatureItem("capability.database_upgrade.legacy_archive_organize", "整理历史数据库归档", "module.database_upgrade", "action"),
)

FEATURE_BY_ID = {item.feature_id: item for item in FEATURES}
if len(FEATURE_BY_ID) != len(FEATURES):
    raise RuntimeError("Feature Registry V2 contains duplicate feature IDs")

FEATURE_GROUPS = (
    ("foundation", "基础与桌面"),
    ("tasks", "任务与 Agent"),
    ("devices", "设备管理"),
    ("ac", "AC 与 FIT-AP"),
    ("configuration", "配置采集与文件"),
    ("rail_base", "轨道交通基础资料"),
    ("trackside_ap", "轨旁 AP"),
    ("train_online", "列车在线与无人值守"),
    ("online_mr", "车载 MR 采集与分析"),
    ("mesh", "MESH 日志分析"),
    ("rail_general", "轨道交通综合"),
    ("network_tools", "网络测试与工具集"),
    ("system", "日志、命令与系统维护"),
    ("internal", "内部与实验功能"),
)
FEATURE_GROUP_TITLE_BY_ID = dict(FEATURE_GROUPS)

PAGE_FEATURE_BY_PAGE_ID = {
    "devices": "module.devices",
    "ac": "module.ac",
    "rail_transit": "module.rail_transit",
    "config_collection": "module.config_collection",
    "file_management": "module.file_management",
    "network_tools": "module.network_tools",
    "tools": "module.tools",
    "command_reference": "module.command_reference",
    "logs": "module.logs",
    "system_settings": "module.system_settings",
    "feature_flags": "internal.feature_switch",
}


def get_feature(feature_id: str) -> FeatureItem:
    if feature_id in REMOVED_FEATURE_IDS:
        raise KeyError(f"Removed feature id: {feature_id}")
    try:
        return FEATURE_BY_ID[feature_id]
    except KeyError as exc:
        raise KeyError(f"Unknown feature id: {feature_id}") from exc


def dependencies_of(feature_id: str) -> tuple[str, ...]:
    """Return runtime requirements only; parent_id is presentation hierarchy."""

    return get_feature(feature_id).requires


def delivery_dependencies_of(feature_id: str) -> tuple[str, ...]:
    return get_feature(feature_id).delivery_requires


def ancestors_of(feature_id: str) -> tuple[str, ...]:
    result: list[str] = []
    parent_id = get_feature(feature_id).parent_id
    while parent_id and parent_id not in result:
        result.append(parent_id)
        parent = FEATURE_BY_ID.get(parent_id)
        parent_id = parent.parent_id if parent else None
    return tuple(result)


def configuration_layer_of(feature_id: str) -> str:
    item = get_feature(feature_id)
    if item.item_type == "capability" or item.internal_only:
        return "technical"
    if item.item_type == "module" or (
        item.item_type == "page"
        and (item.parent_id is None or item.parent_id.startswith("module."))
    ):
        return "business"
    return "operation"


def _lineage_of(feature_id: str) -> set[str]:
    lineage = {feature_id}
    parent_id = FEATURE_BY_ID[feature_id].parent_id
    while parent_id and parent_id not in lineage:
        lineage.add(parent_id)
        parent = FEATURE_BY_ID.get(parent_id)
        parent_id = parent.parent_id if parent else None
    return lineage


def group_id_of(feature_id: str) -> str:
    item = get_feature(feature_id)
    if item.internal_only or item.status in {FeatureStatus.DEVELOPMENT, FeatureStatus.HIDDEN}:
        return "internal"

    lineage = _lineage_of(feature_id)
    if lineage & {"module.agent", "module.task_center"}:
        return "tasks"
    if lineage & {
        "module.trackside_ap",
        "capability.trackside_ap.plan",
        "rail.trackside_ap_business",
        "ac.trackside_ap_plan",
    } or feature_id == "rail.zte_trackside_switch_adapter":
        return "trackside_ap"
    if lineage & {"module.train_online", "module.ground_unattended", "rail.train_online"}:
        return "train_online"
    if lineage & {
        "rail.online_mr_collection",
        "rail.online_mr_analysis",
        "module.online_mr_analysis",
        "module.train_communication",
        "rail.car_network_diagnostic",
    } or any(value.startswith("online_mr.") for value in lineage):
        return "online_mr"
    if lineage & {"rail.raw_mesh_log_analysis", "module.mesh_analysis"} or any(
        value.startswith("mesh.") for value in lineage
    ):
        return "mesh"
    if lineage & {"module.rail_base_data"}:
        return "rail_base"
    if "module.rail_transit" in lineage or any(value.startswith("rail.") for value in lineage):
        return "rail_general"
    if "module.ac" in lineage or "module.ac" in lineage or any(
        value.startswith("ac.") for value in lineage
    ):
        return "ac"
    if "module.devices" in lineage or any(value.startswith("devices.") for value in lineage):
        return "devices"
    if lineage & {"module.config_collection", "module.file_management"} or any(
        value.startswith("file.") for value in lineage
    ):
        return "configuration"
    if lineage & {"module.network_tools", "module.tools"} or any(
        value.startswith("network_tools.") for value in lineage
    ):
        return "network_tools"
    if lineage & {
        "module.logs",
        "module.command_reference",
        "module.system_settings",
    } or any(value.startswith(("system.", "desktop.")) for value in lineage):
        return "system"
    return "foundation"


def list_features() -> tuple[FeatureItem, ...]:
    return FEATURES


def children_of(parent_id: str) -> list[FeatureItem]:
    return [item for item in FEATURES if item.parent_id == parent_id]
