# 功能模块与 Feature Registry

## 1. 唯一事实来源

用户可见模块、页面、Tab、动作和按钮统一登记在 `src/netconsole/core/feature_registry.py`。Feature key 使用点号分层；页面通过 `FeatureGate` 和 `apply_feature_to_widget` 控制，而不是散落读取配置。Registry 使用 `FeatureStatus` 表达 `ENABLED / DISABLED / DEVELOPMENT / HIDDEN`，profile 不能重新开启 `DISABLED` 能力。

内部功能开关页面使用 `module.feature_switch`。该页面只在源码开发态注册；所有冻结/安装包运行态（包括 internal、customer、engineer）都强制隐藏并禁用，不能通过 profile 或本地覆盖重新开启。

正式 Electron 包由 `PackagedRuntimeFeaturePolicy` 执行固定生产功能集：只读取包内 `customer/production` 基线，忽略环境变量、外部 runtime 配置和 `feature_flags.local.json`；外部 `feature_flags.json` 的 schema 版本不改变这条边界。功能配置读写、预览和恢复 API 固定拒绝。包内基线缺失或损坏时，Gate 记录 `PACKAGED_FEATURE_POLICY_FALLBACK` 并回退 Registry 稳定默认。`module.system_settings`、`web.system_settings`、`web.job_center`、`module.logs` 和 `web.logs` 受到核心保护；internal-only 以及 `DISABLED / HIDDEN / DEVELOPMENT` 状态仍强制关闭。源码开发态继续按现有语义读取外部 runtime 配置和本地覆盖。

## 2. 一级模块

| Feature key | 中文模块 | 状态 | 说明 |
| --- | --- | --- | --- |
| `module.devices` | 设备管理 | `ENABLED` | 设备、分组、连接、批量任务和相关导出 |
| `module.ac` | AC 管理 | `ENABLED` | FIT-AP 资源、扩展、光衰、受控动作和 OmniPeek 名称表 |
| `module.rail_transit` | 轨道交通 | `ENABLED` | MR、Mesh、轨旁 AP、车载网络 |
| `module.config_collection` | 配置采集 | `ENABLED` | 快照、比较、批量采集 |
| `module.file_management` | 文件管理 | `ENABLED` | 局点文件和下载 |
| `module.network_tools` | 网络工具 | `ENABLED` | Ping/fping、iPerf、无线扫描和工具箱 |
| `module.command_reference` | 命令参考 | `ENABLED` | 命令、解析器与消费者索引 |
| `module.logs` | 日志 | `ENABLED` | 应用日志 |
| `module.system_settings` | 系统设置 | `ENABLED` | 设置、清理、版本等 |

## 3. 已登记的子功能与内部能力

`web.ground_unattended` 是轨道交通下的独立正式页面，依赖任务中心、轨道交通基础资料和列车在线能力。页面维护自己的局点配置、运行、全车长 Ping、每日深度覆盖和归档状态；底层复用 AC Mesh-Link、Online MR Session/最终化和 fping，不建立第二套人工采集页面。该页面代码与自动测试已接入生产基线，真实 AC/MR、长时运行和托盘隐藏验收状态仍为 `REAL_DEVICE_PENDING`。

Registry 当前显式登记的主要子功能包括：设备管理页面、连接测试、正式写入、采集诊断、导入、导出和桌面联动；这些真实页面/API 已提升为 `ENABLED`，但现场状态仍是 `IMPLEMENTED_UNVERIFIED`。其他登记项包括配置采集、比较、下载，以及删除、`save force`、报告导出和目录动作；文件管理下载、本地下载目录写入、设备 SFTP 浏览/下载和文件桌面联动；网络工具 toolbox、TCP 端口测试和已进入正式路由但仍为 `REAL_DEVICE_PENDING` 的无线扫描；轨道交通基础资料、其下的轨旁 AP 规划页签、轨旁 AP 业务与光衰更新、列车在线、通信监测、Mesh/Online MR。已有 Router、Application Service、Vue 页面和定向测试的列车在线动作、Mesh 导入/报告、Online MR 解析/报告及统一任务控制也已进入 `ENABLED`；未接入生产调用的 `web.online_mr_local_control / web.online_mr_agent_control`、隐藏兼容车内诊断页和 AC 规划能力继续保持 `DEVELOPMENT`。Online MR 分析页另登记 `web.online_mr_session_open_location` 与 `web.online_mr_session_delete` 两个稳定动作，前者还必须同时满足 `desktop.native_bridge`，后者继续受统一任务控制和会话资源互斥约束；AC FIT-AP，以及 AP 扩展预览/写入/回滚/导出、本地重算和高风险动作；命令说明、应用日志与安全维护页面 `web.logs` 及日志导出动作 `web.logs_export`；统一任务中心、Agent 管理、Electron 外壳状态与白名单 Native Bridge `desktop.native_bridge`，以及开发态 Feature 页面。Mesh-Link 底层 API 与刷新动作归属 `web.rail_train_online`，不再登记第二个页面 Feature。所有未经人工或真实设备验收的能力都不能据自动测试直接标记为 `COMPLETE`。

`desktop.native_bridge` 只控制 Vue 中 Electron 本机能力状态区的产品可见性和禁用状态。它不能绕过 Electron main 的发送方校验、参数白名单和同会话路径授权，也不能替代具体业务模块的人工验收。

`web.system_settings` 已作为 Electron Desktop 正式设置页启用并进入客户包；Browser 导航隐藏，Server Mode API 拒绝访问。内部 `web.feature_switch` 仅在源码开发态可见、启用且不进入客户包，所有打包态强制关闭。`web.command_reference` 与 `web.logs` 已注册真实页面、Application Service 和 API；日志 CSV 与开源许可 TXT/XLSX 已通过统一 Export Process 和公共 Artifact source whitelist 闭环，安全清理仍需 Electron 人工确认/取消/恢复验收。系统设置当前仍为 `PARTIAL`，本机工具和目录动作仍需桌面人工验收。默认隐藏规划页继续包括 `web.ac_online_overview`、`web.ac_optical` 和 `web.ac_config_snapshots`；`web.rail_train_online` 与 `web.online_mr_analysis` 已纳入正式生产基线。轨旁 AP 业务页、光衰更新、导出与基础资料中的轨旁 AP 规划已进入生产基线，不再登记 AC 重复页面 Feature。`web.ac_extensions`、`web.rail_car_network_diagnostic（隐藏兼容）` 与网络工具无线扫描仍未通过真实设备验收；无线扫描与已删除的无线勘测不是同一模块。完整状态见[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)和[正式包功能矩阵](PACKAGED_FEATURE_MATRIX.md)。

阶段 3 新增 Web 页面登记项 `web.agent_management`。它只控制 Agent 配置与健康管理入口；iPerf/fping 和默认关闭的 Online MR AGENT executor 使用各自独立 Feature/服务边界，不能由该页面的启用状态推断。

`module.snmp_center` 与 `module.wifi_survey` 已从 Registry、profile、入口、业务代码和资源中删除，并进入 `REMOVED_FEATURE_IDS` 防御集合。历史 profile 即使仍携带这两个 key，也必须被忽略且不能重新启用。设备管理 SNMP v1/v2c 和网络工具无线扫描分别属于现有模块，不得借此恢复已删除平台。

状态语义：`ENABLED` 进入正常 Gate/profile 判定；`DISABLED` 强制隐藏、禁用且不进入客户包，任何 profile 不能重开；`DEVELOPMENT` 只允许源码开发环境；`HIDDEN` 保留登记但不提供用户入口。运行时的 `enabled/visible` 与 Registry 状态不同：`enabled=true, visible=false` 表示能力仍可被依赖和调用但不生成导航入口；`enabled=false` 必须同时 `visible=false`，前端路由、后端 API 和任务入口均按统一 Gate 拒绝新访问。

## 4. 新功能登记流程

### 车内通信检测

正式页面使用 `web.train_communication_monitoring`。点表维护、点表导出和检测执行作为该页面的动作能力登记；历史 `web.rail_car_network_diagnostic` 只保留为隐藏兼容事实记录，不进入正式导航。

1. 在 Registry 中选择稳定 key，声明父模块、默认值、版本/edition 策略和 internal 属性。
2. 页面、Tab、动作或按钮使用同一个 key；隐藏与禁用语义必须明确。
3. 若能力需要后台任务，登记 task type 和对应 handler；若产生用户文件，登记 Export Process 类型。
4. 添加 Feature 开/关测试，至少覆盖导航、直接入口、按钮状态和空/错误状态。
5. 同步本文、根 README、变更记录及相关业务专题。

## 5. Edition 与运行时配置

构建配置可按 internal/customer/engineer edition 或 profile 生成默认功能集合，但运行时仍由统一 Registry/Gate 判定。客户 profile 的 `build_options.engineer_package` 只决定 `both` 是否附加工程师包，不是运行时功能开关。不得在页面用 edition 名称硬编码同一能力的第二套开关。

`client_package/internal_only` 只表示构建选择或发布元数据。源码开发态的功能开关页面将其合并为只读“发布范围”标签，更新 DTO 不接受这两个字段；页面保存只写应用数据根 `runtime/feature_flags.local.json` 中的 `visible/enabled` 覆盖，不再修改 `config/profiles/features/customer.json`。覆盖文件使用文件锁与原子替换，恢复默认写回空覆盖集合，发布 profile 和构建选项保持不变。正式包继续忽略该本地覆盖并固定拒绝配置 API。

当前运行时配置作用域只有“全局”。页面显示当前配置、作用范围和继承 profile，并按基础能力、任务与 Agent、设备与 AC、配置与文件、轨道交通、内部与实验功能分组；搜索、仅显示已修改、三状态选择器和右侧变更预览均为 Renderer 展示/轻量联动。独立发布配置管理页、局点/用户覆盖、运行中任务阻断和批量更新尚未实现，不能从当前页面状态推断这些能力已经存在。

Registry 的 `parent_id + dependencies` 共同组成运行时依赖。当前显式补充了 Agent 管理对任务中心、设备采集与诊断对设备管理/任务中心、车载 MR 实时展示对任务中心/轨道交通基础资料、车内通信检测对轨道交通基础资料/任务中心的依赖。Gate 在读取时递归收敛有效状态，保存前拒绝依赖不完整配置；页面启用子功能或禁用依赖时会确认并明确列出联动项。

## 6. AP Identity 特例

AP Identity diagnostics 使用：

- `ap_identity_diagnostics_enabled`
- `ap_identity_diagnostics_ui_enabled`
- `ap_identity_diagnostics_samples_enabled`

只读摘要只有前两个开关都显式为 true 才可启用；缺失按 false。`samples` 开关当前不授权展示或持久化 samples。Web 任务中心虽已有通用只读详情，但尚未接入 AP Identity diagnostics 专用 ViewModel，因此不得据此在多个业务页面添加可见入口。
