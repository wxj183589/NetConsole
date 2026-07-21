# 功能模块与 Feature Registry

## 1. 唯一事实来源

用户可见模块、页面、Tab、动作和按钮统一登记在 `src/netconsole/core/feature_registry.py`。Feature key 使用点号分层；页面通过 `FeatureGate` 和 `apply_feature_to_widget` 控制，而不是散落读取配置。Registry 使用 `FeatureStatus` 表达 `ENABLED / DISABLED / DEVELOPMENT / HIDDEN`，profile 不能重新开启 `DISABLED` 能力。

内部功能开关页面使用 `module.feature_switch`。该页面只在源码开发态注册；所有冻结/安装包运行态（包括 internal、customer、engineer）都强制隐藏并禁用，不能通过 profile 或本地覆盖重新开启。

## 2. 一级模块

| Feature key | 中文模块 | 状态 | 说明 |
| --- | --- | --- | --- |
| `module.devices` | 设备管理 | `ENABLED` | 设备、分组、连接、批量任务和相关导出 |
| `module.ac` | AC 管理 | `ENABLED` | FIT AP 资源、扩展、光衰、历史和命令 |
| `module.rail_transit` | 轨道交通 | `ENABLED` | MR、Mesh、轨旁 AP、车载网络 |
| `module.config_collection` | 配置采集 | `ENABLED` | 快照、比较、批量采集 |
| `module.file_management` | 文件管理 | `ENABLED` | 局点文件和下载 |
| `module.network_tools` | 网络工具 | `ENABLED` | Ping/fping、iPerf、无线扫描和工具箱 |
| `module.command_reference` | 命令参考 | `ENABLED` | 命令、解析器与消费者索引 |
| `module.logs` | 日志 | `ENABLED` | 应用日志 |
| `module.system_settings` | 系统设置 | `ENABLED` | 设置、清理、版本等 |

## 3. 已登记的子功能与内部能力

Registry 当前显式登记的主要子功能包括：设备管理页面、连接测试、正式写入、采集诊断、导入、导出和桌面联动；这些设备能力仍处于 `IMPLEMENTED_UNVERIFIED`。其他登记项包括配置采集、比较、下载，以及删除、`save force`、报告导出和目录动作；文件管理下载、本地下载目录写入、设备 SFTP 浏览/下载和文件桌面联动；网络工具 toolbox、TCP 端口测试和已进入正式路由但仍为 `REAL_DEVICE_PENDING` 的无线扫描；轨道交通基础资料、其下的轨旁 AP 规划页签、轨旁 AP 业务与光衰更新、列车在线、通信监测、Mesh/Online MR，以及默认关闭的车内诊断执行、Mesh 导入/报告、Online MR 报告和统一任务控制；AC FIT-AP，以及 AP 扩展预览/写入/回滚/导出、本地重算和高风险动作；命令说明、应用日志与安全维护页面 `web.logs` 及日志导出动作 `web.logs_export`；统一任务中心、Agent 管理、Electron 外壳状态与白名单 Native Bridge `desktop.native_bridge`，以及开发态 Feature 页面。Mesh-Link 底层 API 与刷新动作归属 `web.rail_train_online`，不再登记第二个页面 Feature。所有未经人工或真实设备验收的能力都不能据自动测试直接标记为 `COMPLETE`。

`desktop.native_bridge` 只控制 Vue 中 Electron 本机能力状态区的产品可见性和禁用状态。它不能绕过 Electron main 的发送方校验、参数白名单和同会话路径授权，也不能替代具体业务模块的人工验收。

`web.system_settings` 已作为 Electron Desktop 正式设置页启用并进入客户包；Browser 导航隐藏，Server Mode API 拒绝访问。内部 `web.feature_switch` 仅在源码开发态可见、启用且不进入客户包，所有打包态强制关闭。`web.command_reference` 与 `web.logs` 已注册真实页面、Application Service 和 API；日志 CSV 与开源许可 TXT/XLSX 已通过统一 Export Process 和公共 Artifact source whitelist 闭环，安全清理仍需 Electron 人工确认/取消/恢复验收。系统设置当前仍为 `PARTIAL`，本机工具和目录动作仍需桌面人工验收。默认隐藏规划页继续包括 `web.ac_online_overview`、`web.ac_optical`、`web.ac_config_snapshots`、`web.rail_train_online` 和 `web.online_mr_analysis`。轨旁 AP 业务页 `web.rail_trackside_ap_business` 及光衰更新动作 `web.rail_trackside_ap_business_update` 已进入客户包；轨旁 AP 规划只保留 `web.rail_trackside_ap_plan` 基础资料页签，不再登记 AC 重复页面 Feature。`web.ac_extensions`、`web.rail_car_network_diagnostic` 与网络工具无线扫描仍未通过真实设备验收；无线扫描与已删除的无线勘测不是同一模块。完整状态见[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)。

阶段 3 新增 Web 页面登记项 `web.agent_management`。它只控制 Agent 配置与健康管理入口，不代表 iPerf、Ping 或 Online MR 已迁移。

`module.snmp_center` 与 `module.wifi_survey` 已从 Registry、profile、入口、业务代码和资源中删除，并进入 `REMOVED_FEATURE_IDS` 防御集合。历史 profile 即使仍携带这两个 key，也必须被忽略且不能重新启用。设备管理 SNMP v1/v2c 和网络工具无线扫描分别属于现有模块，不得借此恢复已删除平台。

状态语义：`ENABLED` 进入正常 Gate/profile 判定；`DISABLED` 强制隐藏、禁用且不进入客户包，任何 profile 不能重开；`DEVELOPMENT` 只允许源码开发环境；`HIDDEN` 保留登记但不提供用户入口。

## 4. 新功能登记流程

### 在线列车车地通信检测

正式页面使用 `web.train_communication_monitoring`。点表维护、点表导出和检测执行作为该页面的动作能力登记，不再依赖已隐藏的历史 `web.rail_car_network_diagnostic` 页面 Feature。历史页面保留为迁移事实记录，不进入正式导航。

1. 在 Registry 中选择稳定 key，声明父模块、默认值、版本/edition 策略和 internal 属性。
2. 页面、Tab、动作或按钮使用同一个 key；隐藏与禁用语义必须明确。
3. 若能力需要后台任务，登记 task type 和对应 handler；若产生用户文件，登记 Export Process 类型。
4. 添加 Feature 开/关测试，至少覆盖导航、直接入口、按钮状态和空/错误状态。
5. 同步本文、根 README、变更记录及相关业务专题。

## 5. Edition 与运行时配置

构建配置可按 internal/customer/engineer edition 或 profile 生成默认功能集合，但运行时仍由统一 Registry/Gate 判定。客户 profile 的 `build_options.engineer_package` 只决定 `both` 是否附加工程师包，不是运行时功能开关。不得在页面用 edition 名称硬编码同一能力的第二套开关。

## 6. AP Identity 特例

AP Identity diagnostics 使用：

- `ap_identity_diagnostics_enabled`
- `ap_identity_diagnostics_ui_enabled`
- `ap_identity_diagnostics_samples_enabled`

只读摘要只有前两个开关都显式为 true 才可启用；缺失按 false。`samples` 开关当前不授权展示或持久化 samples。Web 任务中心虽已有通用只读详情，但尚未接入 AP Identity diagnostics 专用 ViewModel，因此不得据此在多个业务页面添加可见入口。
