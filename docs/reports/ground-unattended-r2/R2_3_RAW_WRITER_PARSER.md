# R2.3 Raw Writer 与 Parser 报告

日期：2026-11-10。结论：本地链路 **PASS**，故障注入覆盖 **PARTIAL**。

## 已完成

- Raw envelope 先写入 NDJSON，再进入 Parser 派生链路；解析失败不会删除原始日志。
- Raw Writer 在写入完成后生成 Raw Persist Time，由派生 envelope、结构化事件和位置状态携带；原始 NDJSON 的事实字段保持紧凑，避免阶段元数据改变原始流轮转边界。
- Raw Writer/Parser 使用既有有界内存队列和受管 spool；spool 恢复保持 at-least-once 语义，不宣称 exactly-once。
- Parser 成功、失败、忽略、spool 写入失败、队列长度和最老等待时间进入健康快照。
- Parser 完成后将解析结果交给 PositionEngine，位置提交仍与结构化事件在同一批次事务内完成。

## 证据

`tests/test_udp_syslog_reliable_spool.py`、`tests/test_ground_unattended_syslog_v2_stress.py`、`tests/test_ground_unattended_radio_correlation.py` 的定向回归通过；`tests/test_ground_unattended_syslog_position_latency.py` 验证 raw→parse→position 的时间字段贯通。Raw 查询/原始保留回归没有发现本轮新增字段进入 `parsed_details` 的契约冲突。

## 未完成故障注入

以下场景尚未形成 R2.3 的独立量化证据：Parser 暂时变慢、Raw Writer 慢写、SQLite 暂时锁定、后台进程强杀后重启、持续队列增长和磁盘接近阈值。下一步应验证原始流继续留存、spool 有界、恢复后不重复位置切换，并记录每阶段延迟。
