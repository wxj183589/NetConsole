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
| `module.wifi_survey` | 无线勘测 | `DISABLED` | 代码和数据保留；Qt/Web 入口关闭，等待独立重构 |
| `module.config_collection` | 配置采集 | `ENABLED` | 快照、比较、批量采集 |
| `module.file_management` | 文件管理 | `ENABLED` | 局点文件和下载 |
| `module.snmp_center` | SNMP Center | `DISABLED` | 代码、数据库和 MIB 保留；Qt/Web 入口关闭，等待独立重构 |
| `module.network_tools` | 网络工具 | `ENABLED` | Ping/fping、iPerf、无线扫描和工具箱 |
| `module.command_reference` | 命令参考 | `ENABLED` | 命令、解析器与消费者索引 |
| `module.logs` | 日志 | `ENABLED` | 应用日志 |
| `module.system_settings` | 系统设置 | `ENABLED` | 设置、清理、版本等 |

## 3. 已登记的子功能与内部能力

Registry 当前显式登记的主要子功能包括：设备外部终端/SecureCRT/OmniPeek 导出；轨道交通 train online、车载网络、轨旁 AP、MR/Mesh、Online MR 采集与分析；Online MR 链路详情、fping 汇总、备注、高级 Ping 和 iPerf；AC 轨旁计划、在线概览、FIT AP 资源/光衰/扩展及动作；文件管理 Mesh 下载/自动导入/WinSCP；网络工具 toolbox、`network_tools.wireless_scan` 与 `network_tools.ipop`；Mesh 报告；系统磁盘清理、变更记录、开源信息和开发态 Feature 页面。无线扫描与无线勘测不是同一模块，当前仅标记为 Web 迁移 HOLD，不禁用现有 Qt Tab。

阶段 3 新增 Web 页面登记项 `web.agent_management`。它只控制 Agent 配置与健康管理入口，不代表 iPerf、Ping 或 Online MR 已迁移。

SNMP Center 的 MIB 资源、Browser、OID 模板、监控、Trap/告警和拓扑目前作为 `module.snmp_center` 内部 Tab，尚未分别登记子 Feature key。单次查询和推荐页面是中心内部工作流，不是独立可见 Tab。若未来需要 edition 级单独控制，必须先在 Registry 增加明确 key，不能在页面另造配置。

状态语义：`ENABLED` 进入正常 Gate/profile 判定；`DISABLED` 强制隐藏、禁用且不进入客户包，任何 profile 不能重开；`DEVELOPMENT` 只允许源码开发环境；`HIDDEN` 保留登记但不提供用户入口。

## 4. 新功能登记流程

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

只读摘要只有前两个开关都显式为 true 才可启用；缺失按 false。`samples` 开关当前不授权展示或持久化 samples。阶段 8.3 的统一 Job 详情宿主尚不存在，因此即使代码中有纯 ViewModel，也不得据此在多个业务页面添加可见入口。
