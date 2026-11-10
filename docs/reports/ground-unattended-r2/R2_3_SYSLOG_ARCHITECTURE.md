# R2.3 Syslog 位置架构报告

日期：2026-11-10。结论：本地实现 **PASS**，整体现场架构验收 **PARTIAL**。

## 链路

```text
UDP Receiver
    -> bounded Raw Queue
    -> Raw Writer -> immutable NDJSON / raw_persist_time
    -> bounded Parser Queue / managed spool
    -> Parser -> parse_complete_time
    -> PositionEngine (per MR, event time + receive sequence)
    -> one Repository transaction
       [structured event + timeline + position current state]
    -> API snapshot -> incremental Renderer projection
```

## 阶段契约

| 阶段 | 记录内容 | 失败/积压语义 |
| --- | --- | --- |
| Receiver | Receive Time、接收序号、MR 归属候选 | 只负责接收和入有界队列；socket 错误计数可观测 |
| Raw Writer | 原始 envelope、Raw Persist Time | 原始记录先落 NDJSON；parser 失败不删除 raw |
| Parser | Event Type、Event Time、时间精度、Parse Complete Time | 解析失败保留 raw 并增加 parse error；派生 spool 可恢复 |
| PositionEngine | 当前/上一个 AP、位置状态、重复/乱序计数 | 精确身份不足时保留已有位置，不猜测 AP |
| Repository | Position Commit Time、端到端延迟、位置状态 | 位置状态与结构化事件同一批量事务提交 |
| API/Renderer | UI Available Time、来源、新鲜度、状态 | `STALE`/`UNRESOLVED` 显式展示，不能伪装实时 |

## 关键不变量

1. 同一 MR 只接受精确解析为 `PHYSICAL_AP` 或 `RADIO_BSSID` 的 AP 身份进入当前位置。
2. 事件按有效 Event Time 排序；同一时间使用 receive sequence 稳定排序。
3. 设备时间缺失或不可信时使用 Receive Time，但保留 `RECEIVE_TIME_ONLY` 精度标记。
4. 重复事件只增加计数，不再次切换；旧事件不能覆盖已处理的新状态。
5. 未识别 AP、解析失败、不完整事件和延迟 AC 数据不能清空或无条件覆盖 Syslog 位置。
6. 中间切换仍保留在事件/时间轴；批处理只减少中间状态的重复持久化和 UI 刷新。

## 可观测性

健康快照增加 Raw Writer 队列、Parser 队列、最老未处理等待时间、每秒接收/解析/位置更新、重复/乱序计数，以及 receive→raw、raw→parse、parse→position 和端到端位置延迟的 P50/P95/P99。队列持续增长时设置积压告警；本轮未进行长时间增长阈值校准。
