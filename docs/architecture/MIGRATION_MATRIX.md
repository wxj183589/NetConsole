# Qt → Electron 最终迁移矩阵

## 事实范围

本矩阵以当前生产代码、Feature/Navigation Registry、测试和 Git 删除提交为事实来源。`2d0bdbd5` 删除了 `src/netconsole/ui/` 下 153 个受跟踪 Qt 文件；`59fb5908` 删除旧 `apps/desktop/` Shell，其他 Electron-only 提交删除 Qt probe、Adapter、运行依赖和测试环境。历史原文由 Git 保存，不在活动源码中恢复。

正式产品架构为 `Electron Main/Preload + Vue + FastAPI/Python Core`；Browser 只保留本机开发、自动测试和 API 诊断用途。

迁移处置只使用 `MIGRATED`、`REMOVED`、`HIDDEN_PENDING_MIGRATION`、`BLOCKED`。产品验收状态词汇固定为 `NOT_STARTED`、`UI_ONLY`、`READ_ONLY`、`FAKE`、`PARTIAL`、`IMPLEMENTED_UNVERIFIED`、`REAL_DEVICE_PENDING`、`COMPLETE`、`BLOCKED`；其中 `FAKE` 只能说明协议/测试替身覆盖，不能替代真实设备验收。迁移处置与产品验收不能互相替代。

## 已删除路径分类

| 原 Qt 路径/代表类与入口 | 分类 | 永久位置 | 主要自动证据 | 删除依据 |
| --- | --- | --- | --- | --- |
| `src/netconsole/ui/main_window.py`、`app_fluent_window.py`、`app_window_factory.py`、`navigation.py`、`shell/**` | `ADAPTER_REPLACED` | `apps/desktop_electron/src/main`、`preload`；`apps/web/src/App.vue`、导航 Registry | Electron lifecycle/security、Vue navigation 测试 | Electron 是唯一桌面宿主；无业务规则留在窗口壳 |
| `src/netconsole/ui/components/**`、`widgets/**`、`table/**`、`theme/**`、`icons/**` | `PURE_UI` | Vue/Element Plus/ECharts 与 NetConsole Design Token | Vue 组件、布局和主题测试 | Qt 控件/Delegate/绘制代码无永久业务职责 |
| `job_process_manager.py`、`background_process_bridge.py`、`job_action_helper.py`、`export_process_manager.py`、`export_action_helper.py` | `ADAPTER_REPLACED` | `services/job_center/runtime`、`LocalProcessAdapter`、Task Center、Export Process、Electron Artifact Bridge | `test_job_center*`、`test_export_process_framework.py`、Electron 任务窗口测试 | 状态、取消、事件和 Artifact 已由纯 Python/桌面白名单承担 |
| `device_management_page.py`、`device_dialog.py`、`device_detail_dialog.py`、`device_group_dialog.py`、连接/批量/诊断 Worker | `BUSINESS_MOVED` | `device_management_web_service.py`、Device Router/DTO、Device Vue、领域 handlers | `test_device_management_web_api.py`、`test_device_management_table_rules.py` | CRUD、分组、连接、诊断、导入导出进入永久链；现场仍待验收 |
| `ac_management_page.py`、FIT-AP/AP/光衰历史对话框、AC/光衰/轨旁 Worker | `BUSINESS_MOVED` | `services/ac/**`、`h3c_ac_collect_service.py`、AC Router/Vue、AC handlers | `test_ac_management*`、Mesh-Link/光衰/identity 测试 | 采集、资源、历史和受控写入进入永久链；未完成入口保持隐藏 |
| `rail_transit_page.py`、`vehicle_mr_online_page.py`、`online_mr_*page.py`、`mesh_log_analysis_page.py`、轨旁/车内页面及 Worker | `BUSINESS_MOVED` | `services/rail_transit/**`、`services/online_mr/**`、Mesh Service、Rail/Online MR Router/Vue | Rail、Online MR、MESH 定向测试 | 采集/解析/展示/报告进入永久链；真实车辆与设备验收未完成 |
| `config_collection_center_page.py`、`config_lifecycle_worker.py`、`config_diff_viewer.py` | `BUSINESS_MOVED` | `ConfigCollectionApplicationService`、Config Router/Vue、config handlers | `test_config_collection_web_api.py`、config lifecycle/export 测试 | 采集、保存、比较、历史和导出进入永久链 |
| `file_management_page.py`、相关下载/连接 UI | `BUSINESS_MOVED` | `FileManagementApplicationService`、File Router/Vue、file handlers、受控 Electron Bridge | `test_file_management_service.py`、`test_file_management_page.py`、File API/Bridge 测试 | 双栏、SFTP、队列和本机动作进入永久链 |
| `network_tools_page.py`、`network_toolbox_page.py`、`iperf_bandwidth_page.py`、无线扫描页面/Worker | `BUSINESS_MOVED` | `services/network_tools/**`、`services/traffic/**`、Network/Traffic Router/WS/Vue | `test_network_tools*`、`test_traffic*` | 工具与流量测试共用永久 Service；无线扫描独立保留 |
| `settings_page.py`、`feature_flags_page.py`、`command_reference_page.py`、`app_log_page.py`、About/Notice/清理对话框 | `BUSINESS_MOVED` | System Settings/Feature/Command/Logs API 与 Vue；Electron 白名单动作 | 对应 Web API、Feature、日志、Desktop Action 测试 | 设置、日志、许可和本机动作不再依赖 Qt |
| `snmp_center_page.py`、`snmp_*page.py`、`mib_*page.py`、`oid_template_page.py`、`snmp_workers.py` 及 MIB/OID/SNMP Center Service/资源 | `FEATURE_REMOVED` | 无活动替代；设备管理仅保留 SNMP v1/v2c 基础识别 | removed-feature、依赖/发布 Guard | 用户批准删除 SNMP Center、通用 MIB/OID 平台和 SNMPv3 |
| `wifi_survey_page.py` 及 `services/wifi_survey/**` | `FEATURE_REMOVED` | 无；`network_tools.wireless_scan` 是不同能力 | removed-feature、Feature/route 测试 | 用户批准删除无线勘测，不能用无线扫描冒充 |
| `apps/desktop/web_shell.py`、`launcher/qt_probe.py`、`infrastructure/desktop/qt_adapter.py` | `ADAPTER_REPLACED` | `main.py` Electron 编排、Electron Runtime/Main/Preload | launcher/electron runtime/package Guard | Qt Shell、probe 和 Native Adapter 无活动调用者 |
| 纯 Qt 页面、窗口、Delegate、offscreen 测试和无调用 mock | `DEAD_CODE` 或 `PURE_UI` | 无；业务覆盖保留在非 Qt Service/API/Vue 测试 | Qt-free import/package Guard、定向业务测试 | 不再维护第二套宿主或 UI 测试运行时 |

分类词 `PURE_UI`、`BUSINESS_MOVED`、`ADAPTER_REPLACED`、`DEAD_CODE`、`FEATURE_REMOVED` 仅解释删除路径；上表路径模式按最具体行优先，覆盖 `src/netconsole/ui/**` 全部 153 个历史文件。单个历史函数需要追溯时使用 `git show 2d0bdbd5^:<path>`，不得把旧文件复制回活动树。

## 模块最终去向与当前验收

| 模块 | 迁移处置 | 当前产品状态 | 事实入口 | 仍需完成 |
| --- | --- | --- | --- | --- |
| Electron 桌面宿主 | `MIGRATED` | `COMPLETE`（架构） | Electron Main/Preload、受管 Backend、唯一 Vue | 托盘/签名/升级是后续产品能力，不恢复 Qt |
| 设备管理 | `MIGRATED` | `IMPLEMENTED_UNVERIFIED` | `/network/devices`、Device Service/API/Vue | Electron 人工、真实设备连接和导入导出验收 |
| 设备详情（快速抽屉 + 完整页） | `MIGRATED` | `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING` | 设备列表快速抽屉与 `/devices/:deviceId` 共用 Device Detail Application/Query Service、DTO/API/Vue | 定向 Python/Vue/架构验证已通过；Electron 视觉/交互及真实设备采集仍待验收；全量门禁因用户 CPU 限制延后 |
| AC 管理 / FIT-AP | `HIDDEN_PENDING_MIGRATION` | `PARTIAL / REAL_DEVICE_PENDING` | `/ac-management/*`、AC Service/API/Vue | FIT-AP 已合并光衰入口、拓扑默认排序、LLDP 站点建议和 Mesh 两侧收光；真实 AC、危险动作与导出验收待完成 |
| 轨道交通/Online MR/MESH | `HIDDEN_PENDING_MIGRATION` | `PARTIAL` | `/rail-transit/*`、Rail/Online MR/MESH 永久层 | 基础资料已成为默认锁定的站点/区间/AP/MR/规划统一维护入口，使用 revision 与单事务保存；旧规划路由仅重定向。在线列车通信已收口为 TC1/TC2 固定六节点拓扑并复用车内诊断 Task；真实局点写入、SW/SRV 关联、VRRP、跨 TC 及真实列车/MR/Agent/报告仍待现场验收 |
| 配置采集中心 | `MIGRATED` | `IMPLEMENTED_UNVERIFIED` | `/config-center`、Config Service/API/Vue | 真实设备保存、双栏比较、Artifact 人工验收 |
| 设备文件下载（原文件管理） | `MIGRATED` | `IMPLEMENTED_UNVERIFIED` | `/device-files`（旧 `/file-manager`、`/file-management` 仅重定向）、File Service/API/Vue/Bridge | 真实 SFTP、队列恢复、打开/保存动作验收 |
| 网络工具 / Traffic / 无线扫描 | `MIGRATED` | `PARTIAL` | `/network-tools/*`、Network/Traffic Service/API/WS/Vue | 本地与 Agent iPerf/fping、无线扫描现场验收 |
| Task Center/Agent | `MIGRATED` | `PARTIAL` | `/tasks`、`/agents`、共享 Task/Agent Service | 多 Agent/现场与 Electron 子窗口人工验收 |
| 命令说明 / 日志中心 / 系统设置 | `MIGRATED` | `PARTIAL / IMPLEMENTED_UNVERIFIED` | 对应 API/Vue 与白名单 Desktop Action | 本机工具、路径动作、日志清理和设置人工验收 |
| 功能开关管理页 | `HIDDEN_PENDING_MIGRATION` | `NOT_STARTED`（客户产品） | 内部 Feature Registry/API | 保持开发态内部，不进入客户包 |
| SNMP Center/MIB/OID/SNMPv3 | `REMOVED` | `COMPLETE`（删除） | 无活动入口 | 不恢复；历史用户数据不做破坏性清理 |
| 无线勘测 | `REMOVED` | `COMPLETE`（删除） | 无活动入口 | 不恢复；无线扫描独立验收 |

## 使用规则

- “迁移处置完成”不等于“真实功能验收完成”。
- 历史 Qt 页面已经删除只说明旧宿主退出；正在工作树实现、尚未提交或尚未人工/真实设备验收的能力不能因此提升为 `COMPLETE`。
- `HIDDEN_PENDING_MIGRATION` 的入口必须保持不可见/不可用，不能以只读占位页冒充迁移。
- 现场条件缺失时保持 `REAL_DEVICE_PENDING`；Fake 只验证协议，不替代真实设备。
- 设备详情打开时先读取最近数据库快照，各页签首次激活再分页加载；“刷新全部”必须通过现有 Task Center 的 `device.inventory.collect`，不能在 Router 或 Renderer 直连设备。
- 当前通用刷新只允许 H3C/Comware 交换机与车载 MR 且命中可执行版本化 Profile；H3C AC 只读复用 AC 业务 Query Service，H3C MR 关联信息只读复用 Online MR Query Service，Huawei/ZTE 和未知或未验证厂商、角色、平台、Profile 均失败关闭。
- 未知事实由 API 返回 `null` 并在页面显示“—”，不能伪造数值 `0`；设备详情 DTO 不得包含凭据或服务端绝对路径。
- 设备详情 LLDP 公开契约不包含邻居能力或型号；删除的公开字段不保留 DTO/TypeScript/API 别名、双读或 fallback。如后续需要物理重建数据库，由独立维护脚本完成备份/迁移，不在正式启动路径中加入兼容迁移。
- AC Mesh-Link 公开契约已硬删除 `link_status/channel/bandwidth/ap_online_status/optical_status` 及相关筛选；只返回当前产品需要的 MR/AP 事实、RSSI、位置和两侧收光。原始 snapshot status 只在 Query Service 内计算在线状态，不是公开兼容字段。
- AC Mesh-Link 不再是独立用户页面；`/rail-transit/train-online` 是唯一列车在线入口，并由 `VehicleMrOnlineQueryService -> AcMeshLinkQueryService` 聚合每列车 CT/TC。旧 AC URL 重定向，底层 `/api/ac-management/mesh-links/*` 仅作为 deprecated API 保留，Core、Parser、Repository、历史和 raw 不删除。
- 光模块正常状态不返回公开严重性原因，注意、告警、无光等异常原因继续保留；关联业务公开 DTO 不携带重复的 AC/AP、交换机、光模块严重性和 MR 会话细节，内部历史数据不因此删除。
- Navigation Registry 当前注册项使用中立的 `legacy_page_id/legacy_feature_id`；`qt_page_id/qt_feature_id` 只在 schema v1 读取兼容与负向测试中保留，规范化后不会出现在活动导航项，也不代表 Qt 运行时存在。
