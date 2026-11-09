# R2.3 Syslog 位置性能报告

日期：2026-11-10。结论：隔离短时链路验证 **PASS**；性能目标验收 **PARTIAL**。

## 目标

正常运行负载下位置更新目标为 P95 ≤ 10 秒、P99 ≤ 30 秒。该目标从有效 Event Time 计算到 Position Commit/查询可读，不要求毫秒级刷新。突发、设备停机、UDP 丢包、Backend 故障不套用正常负载目标。

## 已实现的测量字段

每个事件/位置状态可记录 Event Time、Receive Time、Raw Persist Time、Parse Complete Time、Position Commit Time 和 API/UI Available Time；健康快照提供阶段及端到端 P50/P95/P99。Event Time 不可信时保留时间精度限制。

## 本轮证据

| 场景 | 状态 | 说明 |
| --- | --- | --- |
| 单事件完整阶段链路 | PASS | `tests/test_ground_unattended_syslog_position_latency.py` 使用临时 Repository 验证字段、位置状态和健康分位数字段 |
| 多事件位置归并 | PASS | `tests/test_ground_unattended_position_engine.py` 覆盖切换、重复、旧事件、未知事件和恢复 |
| 正常持续负载 P50/P95/P99 | NOT_RUN | 没有持续发送 harness 和固定样本量 |
| 突发负载 P50/P95/P99 | NOT_RUN | 没有完成突发发送/消费速度对比 |
| Parser 变慢、Raw 变慢、SQLite 锁 | NOT_RUN | 本轮未建立独立故障注入测量 |
| 30 秒上限验收 | NOT_VERIFIED | 设计和指标已接入，但没有足够样本证明目标 |

## 资源策略

Receiver、Raw Writer、Parser 和位置提交采用有界/批处理路径；位置状态按批次写入，Renderer 读取增量投影，不要求每条日志触发刷新。原始留存优先，消费不足时通过队列、最老等待和 spool 错误暴露问题，不静默丢弃。

## 语义限制

当前 Raw Persist Time 是 Raw Writer 的写入边界时间，不等同于磁盘 `fsync` 完成时间。当前分位数样本需要正常负载 harness 才能代表真实运行；短时单事件测试仅证明字段可测和链路可读，不能替代容量或现场 SLA。
