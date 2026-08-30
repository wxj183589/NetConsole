# Development 数据根生命周期审计

## 环境

- 数据根：`D:\NetConsoleData-dev`
- 运行模式：`development`
- 生成时间：`2026-08-20T19:40:19Z`
- SQLite 连接：`mode=ro`，并设置 `PRAGMA query_only=ON`
- `WRITE_OPERATION_COUNT=0`

## tasks.db

- 当前 `sites` 任务库合计：441303040 bytes（420.86 MiB）。扫描到 37 个 `tasks.db`，归档/冲突副本单独列出，未混入当前汇总。
- 当前占用最大的关注表：`task_events` (218006472 bytes), `task_results` (163125935 bytes), `task_snapshots` (42456129 bytes)。
- 增长判断：`task_events.payload_json`、`task_snapshots.result_json` 等长 JSON 与终态任务长期保留是主要增长来源；`task_results`、`task_logs`、artifact 引用按库实际存在情况报告，未执行删除。
- 详细表级行数、物理分配、索引和大字段统计见 `TASK_DB_USAGE_REPORT.json`。

## LLDP

- 分析范围：宁波地铁6号线 development 数据根 `devices.db` 的全部 LLDP 相关表。
- 所有 LLDP 表按五字段键合计重复组：2527；其中当前 `device_lldp_neighbors` 的完整五字段重复组为 0，另有 2 个同设备/本地端口槽位包含多邻居记录。
- 当前表没有覆盖完整 LLDP 业务键的 UNIQUE 约束，这是 B 类结构性风险；但本快照未证明 A 类相同采集重复写入，也未证明 C 类迁移遗留。历史表中的重复键是跨采集时间的历史记录，不能直接当作当前态重复。
- 详细重复键、首末时间、样本和约束证据见 `LLDP_DUPLICATE_REPORT.json`。

## History retention

- 目标：每个资源最多保留最近 10 条有效变化记录。
- 分析表：`device_lldp_neighbors_history`, `device_optical_modules_history`, `device_interfaces_history`, `ap_lldp_history`, `ap_optical_history`, `ac_fit_ap_lldp_history`, `ac_fit_ap_optical_history`。
- 超限资源：27，超出记录数合计：3586。
- 结论：只读库能确认当前超限，但不能单独证明是写入阶段未限流还是清理任务未运行；下一步应查 producer/job 审计日志并复现，不在本阶段清理。

## 风险

- tasks 事件和结果 payload 可能同时保存完整命令输出、设备响应或 snapshot；物理占用会随任务终态和事件量增长。
- LLDP 当前表缺少足够强的业务唯一约束，重复采集可能继续积累。
- legacy history 表未体现统一的最近10条边界，直接删除会影响时间线、导出和诊断消费者。

## 下一步建议

1. 由负责人确认 producer、history cleanup job 和 result/artifact 引用的生命周期契约。
2. 在 development 数据根建立按 collect_run/task 版本的增长基线，先做 COPY/verify 演练，再单独审批修复或清理。
3. 本审计未执行清理、修复、压缩、迁移、删除或 schema 修改；等待负责人确认后再进入下一阶段。
