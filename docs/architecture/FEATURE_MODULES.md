# 功能模块与 Feature Registry

## 1. 唯一事实来源

用户可见模块、页面、Tab、动作和按钮统一登记在 `src/netconsole/core/feature_registry.py`。Feature key 使用点号分层；页面通过 `FeatureGate` 和 `apply_feature_to_widget` 控制，而不是散落读取配置。Registry 使用 `FeatureStatus` 表达 `ENABLED / DISABLED / DEVELOPMENT / HIDDEN`，profile 不能重新开启 `DISABLED` 能力。

内部“版本与功能交付”页面使用 `module.feature_switch`。该页面只在源码开发态注册；所有冻结/安装包运行态（包括 internal、customer、engineer）都强制隐藏并禁用，不能通过 profile 或本地覆盖重新开启。

正式 Electron 包由 `PackagedRuntimeFeaturePolicy` 执行固定生产功能集：只读取包内 `customer/production` 基线，忽略环境变量、外部 runtime 配置和 `feature_flags.local.json`；外部 `feature_flags.json` 的 schema 版本不改变这条边界。功能配置读写、预览和恢复 API 固定拒绝。包内基线缺失或损坏时，Gate 记录 `PACKAGED_FEATURE_POLICY_FALLBACK` 并回退 Registry 稳定默认。`module.system_settings`、`module.task_center`、`module.logs` 受到核心保护；internal-only 以及 `DISABLED / HIDDEN / DEVELOPMENT` 状态仍强制关闭。源码开发态继续按现有语义读取外部 runtime 配置和本地覆盖。

## 2. 一级模块

| Feature key | 中文模块 | 状态 | 说明 |
| --- | --- | --- | --- |
| `module.devices` | 设备管理 | `ENABLED` | 设备、分组、连接、批量任务和相关导出 |
| `module.ac` | AC 管理 | `ENABLED` | FIT-AP 资源、扩展、光衰、受控动作和 OmniPeek 名称表 |
| `module.rail_transit` | 轨道交通 | `ENABLED` | MR、Mesh、轨旁 AP、车载网络 |
| `module.config_collection` | 配置采集 | `ENABLED` | 快照、比较、批量采集 |
| `module.file_management` | 文件管理 | `ENABLED` | 局点文件和下载 |
| `module.network_tools` | 网络工具 | `ENABLED` | 网络测试能力的兼容模块标识；页面统一归入工具集 |
| `module.tools` | 工具集 | `ENABLED` | 流量测试、连通性检测、无线扫描、网络测试组件和 Electron 第三方 EXE 管理 |
| `module.command_reference` | 命令参考 | `ENABLED` | 命令、解析器与消费者索引 |
| `module.logs` | 日志 | `ENABLED` | 应用日志 |
| `module.system_settings` | 系统设置 | `ENABLED` | 设置、清理、版本等 |

## 3. 已登记的子功能与内部能力

`module.ground_unattended` 是轨道交通下的独立正式页面，依赖任务中心、轨道交通基础资料和列车在线能力。页面维护自己的局点配置、运行、全车长 Ping、每日深度覆盖和归档状态；底层复用 AC Mesh-Link、Online MR Session/最终化和 fping，不建立第二套人工采集页面。该页面代码与自动测试已接入生产基线，真实 AC/MR、长时运行和托盘隐藏验收状态仍为 `REAL_DEVICE_PENDING`。

Registry 当前显式登记的主要子功能包括：设备管理页面、连接测试、正式写入、采集诊断、导入、导出和桌面联动；这些真实页面/API 已提升为 `ENABLED`，但现场状态仍是 `IMPLEMENTED_UNVERIFIED`。其他登记项包括配置采集、比较、下载，以及删除、`save force`、报告导出和目录动作；文件管理下载、本地下载目录写入、设备 SFTP 浏览/下载和文件桌面联动；网络工具 toolbox、TCP 端口测试和已进入正式路由但仍为 `REAL_DEVICE_PENDING` 的无线扫描；轨道交通基础资料、其下的轨旁 AP 规划页签、轨旁 AP 业务与光衰更新、列车在线、通信监测、Mesh/Online MR。已有 Router、Application Service、Vue 页面和定向测试的列车在线动作、Mesh 导入/报告、Online MR 解析/报告及统一任务控制也已进入 `ENABLED`；未接入生产调用的 `capability.online_mr.local_control / capability.online_mr.agent_control`、隐藏兼容车内诊断页和 AC 规划能力继续保持 `DEVELOPMENT`。Online MR 分析页另登记 `capability.online_mr.open_location` 与 `capability.online_mr.session_delete` 两个稳定动作，前者还必须同时满足 `desktop.native_bridge`，后者继续受统一任务控制和会话资源互斥约束；AC FIT-AP，以及 AP 扩展预览/写入/回滚/导出、本地重算和高风险动作；命令说明、应用日志与安全维护页面 `module.logs` 及日志导出动作 `capability.logs.export`；统一任务中心、Agent 管理、Electron 外壳状态与白名单 Native Bridge `desktop.native_bridge`，以及开发态 Feature 页面。Mesh-Link 底层 API 与刷新动作归属 `module.train_online`，不再登记第二个页面 Feature。所有未经人工或真实设备验收的能力都不能据自动测试直接标记为 `COMPLETE`。

`module.tools` 是 `module.tools` 下的 Electron Desktop“外部工具”子页面，正式路由为 `/tools`，导航 ID 为 `tools.external-tools`，与流量测试、连通性检测、无线扫描和网络测试组件并列；它不进入 Python Backend 或局点数据，Browser 不显示桌面专属导航且直接路由由 `desktopOnly` Guard 拒绝。Renderer 启动只传工具 UUID 与普通/管理员模式，定位只传 UUID，Electron Main 从独立 Store 或系统外部终端设置取可信路径。iperf3/fping 不属于快捷工具，IPOP 由旧设置一次性迁移后独立管理，SecureCRT/Xshell/PuTTY 使用只保存来源 key 的引用卡片。当前代码与自动测试状态为 `IMPLEMENTED_UNVERIFIED`，原生选择器、真实 UAC 接受/取消、普通用户、不同第三方 EXE、重启持久化和正式安装包 helper 仍需 Windows 人工验收。

`desktop.native_bridge` 只控制 Vue 中 Electron 本机能力状态区的产品可见性和禁用状态。它不能绕过 Electron main 的发送方校验、参数白名单和同会话路径授权，也不能替代具体业务模块的人工验收。

`module.system_settings` 已作为 Electron Desktop 正式设置页启用并进入客户包；Browser 导航隐藏，Server Mode API 拒绝访问。内部 `internal.feature_switch` 仅在源码开发态可见、启用且不进入客户包，所有打包态强制关闭。`module.command_reference` 与 `module.logs` 已注册真实页面、Application Service 和 API；日志 CSV 与开源许可 TXT/XLSX 已通过统一 Export Process 和公共 Artifact source whitelist 闭环，安全清理仍需 Electron 人工确认/取消/恢复验收。系统设置当前仍为 `PARTIAL`，本机工具和目录动作仍需桌面人工验收。默认隐藏规划页继续包括 `capability.ac.online_overview`、`capability.ac.optical` 和 `capability.ac.config_snapshots`；`module.train_online` 与 `module.online_mr_analysis` 已纳入正式生产基线。轨旁 AP 业务页、光衰更新、导出与基础资料中的轨旁 AP 规划已进入生产基线，不再登记 AC 重复页面 Feature。`capability.ac.extensions`、`module.train_communication（隐藏兼容）` 与网络工具无线扫描仍未通过真实设备验收；无线扫描与已删除的无线勘测不是同一模块。完整当前状态见 Feature/Navigation Registry、生产代码、测试和[正式包功能矩阵](../release/PACKAGED_FEATURE_MATRIX.md)；[冻结迁移矩阵](../archive/migrations/qt-to-electron/MIGRATION_MATRIX.md)只解释已删除路径去向和历史验收维度，不扩展 `FeatureItem` Schema。

`module.agent` 只控制 Agent 配置与健康管理入口；iPerf/fping 和默认关闭的 Online MR AGENT executor 使用各自独立 Feature/服务边界，不能由该页面的启用状态推断。

`module.snmp_center` 与 `module.wifi_survey` 已从 Registry、profile、入口、业务代码和资源中删除，并进入 `REMOVED_FEATURE_IDS` 防御集合。历史 profile 即使仍携带这两个 key，也必须被忽略且不能重新启用。设备管理 SNMP v1/v2c 和网络工具无线扫描分别属于现有模块，不得借此恢复已删除平台。

状态语义：`ENABLED` 进入正常 Gate/profile 判定；`DISABLED` 强制隐藏、禁用且不进入客户包，任何 profile 不能重开；`DEVELOPMENT` 只允许源码开发环境；`HIDDEN` 保留登记但不提供用户入口。运行时的 `enabled/visible` 与 Registry 状态不同：`enabled=true, visible=false` 表示能力仍可被依赖和调用但不生成导航入口；`enabled=false` 必须同时 `visible=false`，前端路由、后端 API 和任务入口均按统一 Gate 拒绝新访问。

`capability.network_tools.components` 是 `module.tools` 下的 Electron Desktop 配置页，读取 `/api/settings/network-components` 并保存 `builtin/custom` 模式；内置组件缺失或自定义组件失效时，解析器返回可见回退原因，不由 Agent 配置路径覆盖。

## 4. 新功能登记流程

### 车内通信检测

正式页面使用 `module.train_communication`。点表维护、点表导出和检测执行作为该页面的动作能力登记；历史 `module.train_communication` 只保留为隐藏兼容事实记录，不进入正式导航。

1. 在 Registry 中选择稳定 key，声明父模块、默认值、版本/edition 策略和 internal 属性。
2. 页面、Tab、动作或按钮使用同一个 key；隐藏与禁用语义必须明确。
3. 若能力需要后台任务，登记 task type 和对应 handler；若产生用户文件，登记 Export Process 类型。
4. 添加 Feature 开/关测试，至少覆盖导航、直接入口、按钮状态和空/错误状态。
5. 同步本文、根 README、变更记录及相关业务专题。

## 5. Edition 与运行时配置

构建配置可按 internal/customer/engineer edition 或 profile 生成默认功能集合，但运行时仍由统一 Registry/Gate 判定。客户 profile 的 `build_options.engineer_package` 只决定 `both` 是否附加工程师包，不是运行时功能开关。不得在页面用 edition 名称硬编码同一能力的第二套开关。

`client_package/internal_only` 只表示构建选择或发布元数据，不是正式运行时权限。源码开发态的“版本与功能交付”直接维护 `config/profiles/features/full.json` 与 `customer.json`，是唯一矩阵编辑入口；系统设置只提供当前版本状态和显式维护动作，不再保存新的运行时矩阵。旧 `runtime/feature_flags.local.json` 仅保留升级兼容清理，正式包继续忽略该文件并固定拒绝模板配置 API。

客户模板使用“不交付 / 交付并显示 / 交付但隐藏”单一三态；完整版使用“显示并启用 / 隐藏入口但保留能力 / 关闭”。页面按业务分类默认折叠模块，展开后显示页面和操作；`cap.*` 技术能力单独只读折叠。草稿会话预览只存于当前 Backend 进程，不写模板或运行时覆盖，退出或重启后恢复。

Registry 将层级与依赖拆开：`parent_id` 只表达界面树和客户交付父级闭包，`requires` 只表达运行时技术依赖，`delivery_requires` 表达客户版交付依赖。Gate 只按 `requires` 递归收敛运行状态，父级隐藏不会自动关闭仍需保留的底层能力。任务中心、轨交基础数据、轨交任务控制、列车在线数据、Online MR 分析和 Desktop Bridge 等共用技术能力登记为只读 `cap.*` 项，业务页面与动作不再借另一个页面充当技术依赖。

模板检查与自动修复由 Backend 统一计算结构化依赖问题，Renderer 不维护第二套依赖算法。自动修复会把可修复依赖设为“启用但隐藏”，客户模板同时纳入交付；修复只进入当前草稿，保存后才写模板。Electron 版本资源注入前再次校验 Full/Customer Profile，依赖闭包、内部功能或非正式状态泄漏会直接中止构建并输出具体链路。

## 6. AP Identity 特例

AP Identity diagnostics 使用：

- `ap_identity_diagnostics_enabled`
- `ap_identity_diagnostics_ui_enabled`
- `ap_identity_diagnostics_samples_enabled`

只读摘要只有前两个开关都显式为 true 才可启用；缺失按 false。`samples` 开关当前不授权展示或持久化 samples。Web 任务中心虽已有通用只读详情，但尚未接入 AP Identity diagnostics 专用 ViewModel，因此不得据此在多个业务页面添加可见入口。
