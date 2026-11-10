# R2.3.1 基线审计

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
范围：Ground Unattended 的 Syslog、Raw/Parser、Position、Heartbeat/fping、AC 快照及 Renderer 展示。

## 结论

现有 R2.3 基线已经具备 UDP 接收、Raw 顺序批写、解析积压、PositionEngine 按事件时间归并、有限队列/磁盘 spool、位置延迟阶段字段、Heartbeat 常驻和 Renderer 增量轮询。R2.3.1 的主要缺口是 AC 全快照没有可审计的本地 ADDED/UPDATED/REMOVED/UNCHANGED/UNKNOWN 账本，也没有将 Syslog 与 AC 的新旧关系保存为明确状态。

本次补充保持现有服务边界，不引入 Kafka、Redis 或第二套 HistoryStore：

- `ac_reconciliation.py` 提供全快照差异和只读对账判定。
- `ground_unattended_repository.py` 增加 additive AC delta/reconciliation 表和 Repository API，schema version 从 15 升为 16。
- `supervisor.py` 在 AC 新快照写入前记录差异和对账证据，不修改 Syslog 位置状态。
- API/DTO/Renderer 显示对账状态及 AC 时间。
- `ground_unattended_r2_3_1_simulation.py` 提供可重复的 100 MR 本地三链路模拟。

证据：`ruff`、AC/Position/Raw 定向测试、Ground 集成测试及真实 loopback UDP 模拟均通过。完整仓库 Gate 仍受当前工作树已有 Mesh/数据根 dirty 修改影响，见 [最终验收](R2_3_1_FINAL_ACCEPTANCE.md)。

## 边界

本报告不读取 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`，不代表真实设备、现场网络、真实 AC 控制器或 8 小时运行验收。
