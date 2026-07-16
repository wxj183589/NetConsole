# Qt/Web 功能对等矩阵

## 口径

本矩阵以当前生产代码、Feature Registry 和自动化测试为事实来源。Web 聚合页只代表其明确展示或受控操作的范围，不能自动视为替代 Qt 页面。当前所有目标模块均保持 `dual`：Qt 是稳定生产/回退入口，Web 只有达到 `REPLACE_READY` 后才允许改为默认入口。

长期模块总览见 [Web 迁移矩阵](WEB_MIGRATION_MATRIX.md)，最终桌面与业务分层目标见 [下一代架构](ARCHITECTURE_NEXT.md)。

业务页面对等状态只使用：`NOT_STARTED`、`READ_ONLY`、`PREVIEW_ONLY`、`CONTROLLED_WRITE`、`FAKE_ACCEPTED`、`REAL_ACCEPTED`、`REPLACE_READY`、`EXCLUDED`。宿主与基础设施可在长期总览中单独使用 `FOUNDATION_READY`，该状态不表示任何业务页面达到替换条件。本轮 Electron 受管下载和 `shutdown_ack -> exit` 退出屏障仍属于宿主基础；Online MR 完整操作闭环迁移状态不变。

- `FAKE_ACCEPTED` 不等于真实设备验收。
- “写操作”包括创建/取消 Task、修改配置或数据、执行设备动作；受控下载不计为业务写入。
- SNMP Center 和无线勘测固定为 `EXCLUDED`；`network_tools.wireless_scan` 是网络工具能力，不在排除范围。
- 未实现页面可以登记规划 Feature 和导航归属，但不得注册占位业务路由或显示为已完成。

## 对等矩阵

| Qt 一级模块 | Qt 页面或 Tab | Qt 动作 | Qt Feature ID | Web 模块 | Web Route | Web Feature ID | 复用的 Service | 当前 Web 状态 | 是否有写操作 | Fake 验收状态 | 真实验收状态 | 是否达到替换条件 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 全局 | 无对应 Qt Dashboard | 全局只读摘要与快捷入口 | — | Dashboard | `/` | — | 尚未建立全局聚合 Service | `NOT_STARTED` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 当前仅占位；不能替代轨道交通无线看板。 |
| 设备管理 | 设备列表/详情 | 搜索、筛选、分组查看、详情 | `module.devices` | 设备管理 | `/network/devices` | `web.device_management` | `DeviceManagementWebService`、Device Repository | `READ_ONLY` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 与 Qt 读取同一局点数据。 |
| 设备管理 | 连接测试 | SSH/Telnet 等后台测试 | `module.devices` | 设备管理 | `/network/devices` | `web.device_connection_test` | `DeviceManagementWebService`、Task Application Service | `CONTROLLED_WRITE` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 创建受控 Task，不向浏览器返回凭据。 |
| 设备管理 | 编辑设备 | 编辑表单与校验 | `module.devices` | 设备管理 | `/network/devices` | `web.device_edit_preview` | 既有设备表单规则、Device Repository | `PREVIEW_ONLY` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 仅生成预览，尚未正式落库。 |
| 设备管理 | 设备与分组管理 | 新增、复制、正式编辑、设置分组、批量删除 | `module.devices` | 设备管理 | `/network/devices` | `web.device_management_write` | `DeviceManagementWebService`、Device Repository、统一审计 | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；Router 只调用共享 Service。 |
| 设备管理 | 批量与导入导出 | 批量更新、诊断下载、CSV/模板/OmniPeek 导出 | `module.devices`、`devices.omnipeek_name_table_export` | 设备管理 | `/network/devices` | `web.device_management_collect`、`web.device_management_import`、`web.device_management_export` | Job Center、Export Process | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 大批量动作进入 Task/Export；导入要求预览和确认。 |
| 设备管理 | 外部工具 | 外部终端、SecureCRT 会话 | `devices.external_terminal`、`devices.securecrt_sessions` | 设备管理 | `/network/devices` | `web.device_management_desktop` | 白名单 Desktop Action/受控导出 | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；只允许业务 ID、已登记终端和服务端生成参数。 |
| AC 管理 | 轨旁 AP 规划 | 规划查看与维护 | `ac.trackside_ap_plan` | AC 管理 | `/ac-management/trackside-plan` | `web.ac_trackside_ap_plan` | 现有轨旁 AP 规划 Service | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 固定属于 AC，不得移入轨道交通。 |
| AC 管理 | AP 上线情况概览 | 在线状态查看 | `ac.ap_online_overview` | AC 管理 | `/ac-management/online-overview` | `web.ac_online_overview` | 现有 AC/AP Query | `NOT_STARTED` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 规划 Feature 默认关闭。 |
| AC 管理 | FIT-AP 资源 | AP、Radio、LLDP、历史与详情 | `ac.fit_ap_resources` | AC 管理 | `/ac-management/fit-aps` | `web.ac_fit_ap_resources` | `AcManagementQueryService`、AC Repository | `READ_ONLY` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 旧 `/ac-management` 兼容重定向到此路由。 |
| AC 管理 | FIT-AP 光衰 | 光衰查看与历史 | `ac.fit_ap_optical` | AC 管理 | `/ac-management/optical` | `web.ac_optical` | `AcManagementQueryService` | `NOT_STARTED` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 当前聚合页含部分光衰字段，不代表独立 Tab 对等。 |
| AC 管理 | FIT-AP 扩展信息 | 查看、导入预览、受控写入 | `ac.fit_ap_extensions` | AC 管理 | `/ac-management/extensions` | `web.ac_extensions`、`web.ac_extensions_preview`、`web.ac_extensions_apply`、`web.ac_extensions_rollback`、`web.ac_extensions_export` | 现有 FIT-AP 扩展 Service、Task/Export | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；正式写入要求预览、确认、Task 和审计。 |
| AC 管理 | Mesh-Link 在线监控 | 查看、固定只读命令刷新 | `module.ac`、`ac.mesh_link.refresh` | AC 管理 | `/ac-management/mesh-links` | `web.ac_mesh_links` | `AcMeshLinkQueryService`、`AcMeshLinkRefreshApplicationService` | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 刷新只接受 AC 标识和固定布尔参数。 |
| AC 管理 | 配置快照与对比 | 配置查看、历史、差异 | `module.ac` | AC 管理 | `/ac-management/config` | `web.ac_config_snapshots` | `AcManagementQueryService` | `NOT_STARTED` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 当前 FIT-AP 聚合页有部分只读快照能力，尚非独立对等页面。 |
| AC 管理 | AC 受控动作 | 信息刷新、固化新 AP、`save force`、开启 AP 远程登入 | `ac.ac_info_update`、`ac.ac_actions` | AC 管理 | `/ac-management/extensions` 内动作 | `web.ac_refresh`、`web.ac_dangerous_actions` | AC Application Service、Task、审计 | `FAKE_ACCEPTED` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭且当前只允许 Fake 计划；禁止任意命令输入和 Vue 拼命令。 |
| 轨道交通 | 轨道交通无线看板 | 聚合基础设施、列车、任务、Agent、Mesh | `module.rail_transit` | 轨道交通 | `/rail-transit/wireless-dashboard` | `web.rail_transit_wireless_dashboard` | `WirelessDashboardQueryService` | `READ_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 是轨交看板，不是全局 Dashboard。 |
| 轨道交通 | 基础资料 | 站点/区间、AP 点位、列车/MR、质量检查 | `module.rail_transit` | 轨道交通 | `/rail-transit/base-data` | `web.rail_transit_base_data` | `RailTransitBaseDataQueryService`、Import Preview Service | `PREVIEW_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 正式写入 Feature 默认关闭，真实局点未授权。 |
| 轨道交通 | 列车在线情况 | 查看/刷新列车与 MR 在线状态 | `rail.train_online` | 轨道交通 | `/rail-transit/train-online` | `web.rail_train_online` | Vehicle MR Online Service | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 通信聚合页不能自动替代该 Qt Tab。 |
| 轨道交通 | 车内通信检测 | 检测、进度、结果与导出 | `rail.car_network_diagnostic` | 轨道交通 | `/rail-transit/car-network-diagnostic` | `web.rail_car_network_diagnostic`、`web.rail_car_network_diagnostic_execute`、`web.rail_task_control` | Car Network Diagnostic Service、Job/Export | `FAKE_ACCEPTED` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；与在线列车车地通信检测是不同业务。 |
| 轨道交通 | 在线列车车地通信检测 | 聚合 MR、Mesh、Traffic、Task 与采集包 | `module.rail_transit` | 轨道交通 | `/rail-transit/train-communication` | `web.train_communication_monitoring` | `TrainCommunicationQueryService` | `READ_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 不等同“列车在线情况”或“车内通信检测”。 |
| 轨道交通 | 轨旁 AP 业务 | 采集、解析、查看、报告 | `rail.trackside_ap_business` | 轨道交通 | `/rail-transit/trackside-ap-business` | `web.rail_trackside_ap_business` | Trackside AP Business Service、Job/Export | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 固定属于轨道交通，不得放入 AC。 |
| 轨道交通 | MR 原始 MESH 日志分析 | 既有结果查看 | `rail.raw_mesh_log_analysis` | 轨道交通 | `/rail-transit/mesh-analysis` | `web.mesh_analysis` | `MeshAnalysisQueryService` | `READ_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 只读既有分析库。 |
| 轨道交通 | MR 原始 MESH 日志分析 | 文件选择、导入、重建、分析、取消、报告 | `rail.raw_mesh_log_analysis`、`mesh.generate_report` | 轨道交通 | `/rail-transit/car-network-diagnostic` 与 `/rail-transit/mesh-analysis` | `web.mesh_analysis_import`、`web.mesh_analysis_report_export`、`web.rail_task_control` | 正式 Mesh parser、Job Center、Export Process | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；已完成导入、任务恢复、取消和报告闭环，真实日志未验收。 |
| 轨道交通 | 车载 MR 实时收集 | LOCAL/AGENT 启动、状态、正常停止、Traffic、包与恢复 | `rail.online_mr_collection`、`online_mr.advanced_ping`、`online_mr.iperf_test` | 轨道交通 | `/rail-transit/online-mr` | `web.online_mr_realtime`、控制动作 Feature | `OnlineMrApplicationService`、Agent Controller、Traffic、Task/Session Mapping | `FAKE_ACCEPTED` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 无 Web 强停；Agent→真实 MR 与真实供电环境仍冻结。 |
| 轨道交通 | 车载 MR 收集分析 | Session、链路明细、fping 汇总、图表、报告、导出 | `rail.online_mr_analysis` | 轨道交通 | `/rail-transit/online-mr-analysis` | `web.online_mr_analysis` | Online MR Query/Analysis、Export Process | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 不得用 MeshAnalysisView 代替。 |
| 配置采集中心 | 运行中/已保存/差异 | 设备选择、批量采集、快照查看与比较 | `module.config_collection` | 配置采集中心 | `/config-center` | `web.config_collection`、`web.config_collection_fetch`、`web.config_collection_diff` | `ConfigCollectionApplicationService`、Config Lifecycle/Snapshot、Task | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 已复用正式采集/比较链，不重新实现采集器。 |
| 配置采集中心 | 保存、下载与导出 | 保存配置、任意快照比较、多设备比较、批量导出、目录、删除历史 | `module.config_collection` | 配置采集中心 | `/config-center` | `web.config_collection_download`、`web.config_collection_delete`、`web.config_collection_save_force`、`web.config_collection_export`、`web.config_collection_open_directory` | Config Lifecycle、Export Process、Runtime Adapter 受控下载与目录动作 | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 扩展动作默认关闭；删除与 `save force` 必须确认。 |
| 文件管理 | 本地文件 | 局点文件浏览、分类和下载 | `module.file_management` | 文件管理 | `/file-manager` | `web.file_management`、`web.file_management_download` | `FileManagementApplicationService` | `READ_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 仅白名单本地文件；不是 Qt 双窗格完整对等。 |
| 文件管理 | 设备文件/传输队列 | 连接、断开、导航、下载、进度、取消、Mesh 筛选 | `module.file_management`、`file.mesh_log_download` | 文件管理 | `/file-manager` | `web.file_management_remote`、`web.file_management_download` | 既有只读 SFTP/File Service、Task、Artifact | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 默认关闭；只读下载，不提供上传、删除、重命名。 |
| 文件管理 | 外部 WinSCP | 启动已配置 WinSCP | `file.external_winscp` | 文件管理 | `/file-manager` | — | 不在初始 Native Bridge 白名单 | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 迁移期留在 Qt；未来需要单独安全立项。 |
| 网络工具 | IPERF 带宽测试 | iPerf Server/Client、fping、LOCAL/Agent、停止与重试 | `network_tools.traffic` | 网络工具 | `/network-tools/traffic` | `network_tools.traffic` | `TrafficTestApplicationService`、Traffic Repository/Supervisor | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 通用 Traffic 固定属于网络工具。 |
| 网络工具 | 小工具 | IPv4/IPv6、VLSM、子网、汇总、反掩码 | `network_tools.toolbox` | 网络工具 | `/network-tools/toolbox` | `web.network_tools_toolbox` | 既有 Network Toolbox Service | `READ_ONLY` | 否 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 旧 `/network-tools/overview` 兼容重定向。 |
| 网络工具 | 连通性检测 | 单/持续/批量/网段/TCP Ping、端口测试、停止、进度、导出 | `network_tools.toolbox` | 网络工具 | `/network-tools/toolbox` | `web.network_tools_toolbox`、`web.network_tools_tcp_port_test` | Network Toolbox、Task/Export | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 已覆盖 Ping/fping/TCP、批量/网段、恢复、取消、分页和导出。 |
| 网络工具 | 无线扫描 | 扫描、项目、结果与导出 | `network_tools.wireless_scan` | 网络工具 | `/network-tools/toolbox` 内默认隐藏 Tab | `web.network_tools_wireless_scan` | Wireless Scan Service、Job/Export | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 与无线勘测不同；默认关闭，真实硬件验收延期。 |
| 网络工具 | IPOP | 启动已登记工具 | `network_tools.ipop` | 网络工具 | `/network-tools/toolbox` | — | 不在初始 Native Bridge 白名单 | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 迁移期留在 Qt；未来需要单独安全立项。 |
| 任务中心 | 无 Qt 一级入口 | 列表、详情、日志、协作取消 | — | 任务中心 | `/tasks` | `web.job_center` | `TaskApplicationService`、`JobCenterQueryService`、Task Repository | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | 复用同一 Task 状态机。 |
| Agent 管理 | 无 Qt 一级入口 | Profile、健康、工具、任务、包、远程 MR 控制入口 | — | Agent 管理 | `/agents` | `web.agent_management` | `AgentControllerService`、Agent Repository/Client | `CONTROLLED_WRITE` | 是 | `FAKE_ACCEPTED` | `NOT_STARTED` | `NOT_STARTED` | Agent 只管理执行端，不接管 Online MR 业务归属。 |
| 命令说明 | 命令说明页 | 搜索、筛选、详情、复制、导出 Markdown、刷新 | `module.command_reference` | 命令说明 | `/command-reference` | `web.command_reference` | Command Reference 资源与 Service、Export Process | `NOT_STARTED` | 否 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 页面不得直接执行命令。 |
| 日志中心 | 应用日志页 | 分页、筛选、搜索、详情、实时刷新、导出、清理、打开目录 | `module.logs` | 日志中心 | `/logs` | `web.logs` | App Log Service、Export/Native Bridge（规划） | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 清理动作必须 Desktop、确认、Gate、审计。 |
| 系统设置 | 设置页 | 主题、语言、局点、路径、工具、清理、变更记录、开源声明 | `module.system_settings`、`system.*` | 系统设置 | `/settings` | `web.system_settings` | SettingsStore、SiteManager、Native Bridge（规划） | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 浏览器偏好与本机设置必须分层。 |
| 功能开关 | 功能开关页 | Registry、profile、session override、customer preview、保存与恢复 | `module.feature_switch`、`system.feature_flags` | 功能开关配置 | `/feature-flags` | `web.feature_switch` | `FeatureGate` | `NOT_STARTED` | 是 | `NOT_STARTED` | `NOT_STARTED` | `NOT_STARTED` | 仅源码 dev Desktop；所有冻结包均隐藏并拒绝。 |
| SNMP Center | 全部页面与动作 | MIB/OID、采集、监控、Trap、拓扑 | `module.snmp_center` | 不注册 | — | — | 现有 SNMP Core 保留 | `EXCLUDED` | — | `EXCLUDED` | `EXCLUDED` | `EXCLUDED` | 本轮明确排除，Registry 保持 `DISABLED`。 |
| 无线勘测 | 全部页面与动作 | 勘测、热力图、导出、硬件适配 | `module.wifi_survey` | 不注册 | — | — | 现有无线勘测 Core 保留 | `EXCLUDED` | — | `EXCLUDED` | `EXCLUDED` | `EXCLUDED` | 本轮明确排除，不能据此隐藏无线扫描。 |

## 当前替换判断

- 当前没有模块达到 `REPLACE_READY`，Qt 页面不得隐藏或删除。
- 本轮已补齐设备正式 CRUD/导入导出、配置扩展动作、设备远程文件只读下载、网络连通性与无线扫描、AP 扩展及部分 AC/轨交 Fake 闭环；这些高风险能力默认关闭，仍未达到真实验收或 Qt 替换条件。
- 真实 AC/MR/Agent/无线硬件验证均保持 `NOT_STARTED`；列车下电期间的 Fake 结果不得升级为 `REAL_ACCEPTED`。
