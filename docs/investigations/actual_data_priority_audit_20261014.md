# NetConsole 实际采集数据优先治理审计

日期：2026-10-14
审计分支：`codex-A/actual-data-priority-field-merge-20261014`
审计基线：`d7b36fbc`（`main`，与 `github/main` 一致）

## 结论摘要

本阶段完成 Phase 1 审计，并对已确认的一个字段级合并缺陷完成最小修复：

- `merge_fit_ap_rows_by_identity()` 在较高优先级记录胜出时，原实现整行覆盖，可能用新记录的空字段抹掉另一条记录中仍有效的光衰或 LLDP 字段。
- 现改为“首选记录保留非空值，回退记录仅补首选记录缺失字段”，不改变身份键、状态判定、接口、数据库结构或导出列。
- 页面、导出、统计和设备详情的既有业务规则未被替换；当前页/导出快照链路保持不变。

本阶段不宣称全项目治理完成。审计发现的跨模块来源语义收敛和兼容路径统一，仍需按下文风险清单分阶段处理。

## 当前来源边界

| 模块 | 当前主要入口/生产者 | 当前实际优先级与保护 | 本阶段结论 |
| --- | --- | --- | --- |
| AC/FIT-AP | `AcManagementQueryService`、`AcRepository`、AC 采集任务 | 当前 FIT-AP 资源、当前 LLDP、当前光衰由 AC 域读取；身份合并限定 AC 作用域和稳定 MAC/序列号，歧义不猜测 | 已有规则可复用；未扩大接口 |
| 轨旁 AP 业务 | `TracksideApBusinessQueryService.list_rows()`、`load_trackside_ap_business_snapshot()`、`build_trackside_ap_business_rows()` | 当前交换机接口/光衰/LLDP 和 AC 当前资源优先；历史 LLDP/离线台账仅作有标识的回退；规划资料用于范围、目标和补充，不覆盖实际端口事实 | 修复字段级合并缺陷；页面和导出仍使用统一快照 |
| 轨旁 AP 导出 | `build_trackside_ap_business_export_snapshot()`、`export_trackside_ap_business_from_snapshot()` | 与页面共用业务快照和修订号，导出列结构未改 | 回归通过 |
| 轨道交通基础资料 | `RailTransitBaseDataQueryService`、`source_policy.py` | 正式资料写入仍保持人工/既有数据库优先；运行态通过 `include_runtime=True` 附加展示；FIT-AP 管理 IP 保持 runtime-only，不自动写回正式身份 | 不修改正式资料和写入策略 |
| 列车在线 / Vehicle MR | `VehicleMrOnlineQueryService`、Mesh-Link 查询 | 当前 Mesh/AP 状态和基础资料在现有服务内分层处理；并行 PR #83 尚未合并，本分支不重复修改其 CT/TC 站点回退和 RSSI 文件 | 保留待合并变更边界 |
| MESH / Online MR | 原始 MESH、Online MR 查询与分析服务 | 原始 RSSI、时间、Peer/链路事实保持独立；身份和站点作为关联补充 | 本阶段未改原始数据和命令流程 |
| 地面无人值守 | Syslog 原始接收、设备身份解析、Supervisor 状态机 | 原始记录和完整 MAC 身份边界独立；未将 Ping 或基础资料提升为 Mesh 在线事实 | 本阶段未改状态机 |
| 设备管理兼容路径 | `DeviceManagementWebService._trackside_ap_business()`、Job Center 旧任务处理器 | 仍使用同一业务行构建器，但部分兼容/后台路径不经过 Web 页面使用的冻结业务快照 | 记录为后续收敛项，避免本阶段扩大公共详情接口变更 |

## 已确认并修复的问题

文件：`src/netconsole/services/trackside_ap_business.py`
函数：`merge_fit_ap_rows_by_identity()`

原逻辑在新记录优先时执行整行覆盖：

```text
preferred row + empty field  -> empty field
```

这不符合字段级来源决策：同一身份的较新记录可以决定它实际提供的字段，但不能抹掉另一条可信记录中仍存在、且本条没有提供的字段。

现逻辑为：

```text
preferred row 的非空字段优先
preferred row 缺失字段 <- fallback row 的非空字段
```

回归测试：`tests/test_trackside_ap_business_optimization.py::test_fit_ap_identity_merge_preserves_nonempty_fields_from_lower_priority_row`，覆盖新记录保留新 IP/Tx，同时保留旧记录有效 Rx 和 LLDP 邻居字段。

该修复不改变：

- AP 身份键和 AC 作用域；
- 在线/离线、光衰阈值、LLDP 匹配和统计判定；
- API DTO、数据库表、字段类型和 Excel 导出列；
- 采集器、设备会话、任务中心、Electron Runtime。

## 审计发现的剩余风险

1. `DeviceManagementWebService._trackside_ap_business()`、`legacy_tasks._ac_trackside_business_refresh()` 和 `legacy_tasks._device_detail_load_all()` 仍是兼容/后台构建路径。它们使用业务行构建器，但没有完全复用页面和导出使用的冻结 `TracksideApBusinessSnapshot`。后续若统一来源修订号、页面/详情/后台结果一致性，应逐个消费者补充审计和回归，不能直接替换公共接口。
2. `source_policy.py` 主要约束正式基础资料导入/写入，不是运行态页面的全局优先级表。不能为了表面统一而把 AC 当前 IP、AP 名称或 LLDP 事实直接写入正式资料，也不能倒置已有人工资料保护规则。
3. 设备详情兼容路径存在异常时保留空站点名称的保护分支。该分支需要后续明确错误可见性和来源状态，当前不在本阶段改动，避免把兼容详情接口改成隐式全量快照查询。
4. 千级 FIT-AP 真实数据、现场设备、Electron GUI 安装和跨机器验收未在本阶段执行；自动化测试不能替代这些验收。
5. PR #83（`chatgpt/train-online-station-rssi-20261014`）在审计时仍为 OPEN，不能把其未合并内容计入本分支完成范围。

## 数据安全与回滚

- 未读取、复制、覆盖或写入 `D:\NetConsoleData`、`D:\NetConsoleData-dev`。
- 未执行数据库迁移、数据修复、正式资料修改、采集日志修改或导出列变更。
- 代码改动为单文件局部逻辑，测试改动为单个回归用例；可通过回滚本提交独立撤销。
- 未连接真实设备，未执行配置命令。

## 测试证据

基线阶段已通过：

- AP Identity 相关：`103 passed`；
- Trackside/AC 相关组合：`172 passed`、`102 passed`；
- Mesh、Online MR、Ground Unattended 等领域组合：`335 passed`。

本阶段改动后通过：

- `tests/test_trackside_ap_business_optimization.py`：`24 passed`；
- 轨旁 AP 快照、范围、Web、运行一致性、统计组合：`200 passed`；
- 轨旁 AP 导出、AC 查询/Web、设备管理 Web、未认证 AP 合并：`153 passed`，18 个既有弃用警告；
- AC 管理、轨旁 AP 维护/身份影子/WPS/导出/基础资料回填组合：`413 passed`，1 个既有弃用警告；
- `git diff --check`：通过。

未执行：完整全仓库 Gate、真实设备采集、千级真实 FIT-AP 性能、GUI 安装和现场验收。

## 下一阶段建议

优先对剩余兼容/后台消费者做 L3 Consumer Audit，先为每个消费者补“当前值、字段缺失、历史回退、来源状态、页面/导出一致性”测试，再决定是否把它们接入冻结快照；不建议在未完成消费者审计前引入全局数据来源框架或修改公共 Query Service 接口。
