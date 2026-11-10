# R2.3.2 位置更新延迟

## 时间口径

有效位置事件按 `Event Time` 计算，数据库详情同时保留 `event_time`、`receive_time`、`raw_persist_time`、`parse_complete_time`、`position_commit_time` 和 `position_latency_ms`。脱敏 Fixture 的事件时间来源为 `DEVICE_TIME`、精度 `DEVICE_TIMESTAMP`；它是本机合成设备时间，不是现场设备时钟证明。长稳没有逐事件 `UI_AVAILABLE_TIME` 字段，GUI 截图作为可见性证据单列，不伪造 UI 延迟。

## 分场景结果

独立 latency runner 使用生产 Receiver/Raw/Parser/Position，100 MR，所有事件均带有效 AP 和唯一 fixture sequence：

| 场景 | 事件数 | P50 | P95 | P99 | 阶段 P95（接收→Raw / Raw→解析 / 解析→位置） | Drop |
|---|---:|---:|---:|---:|---|---:|
| 正常 | 100 | 506 ms | 973 ms | 1010 ms | 3 / 1 / 970 ms | 0 |
| 突发 | 2000 | 2120 ms | 5899 ms | 6286 ms | 507 / 5369 / 77 ms | 0 |

两场景均满足正常测试负载目标 P95≤10 秒、P99≤30 秒。突发场景主要延迟位于 Raw→Parser 批处理阶段，Raw 仍完整保留。

## 6 小时 40 分长稳

从长稳 SQLite `ground_unattended_wmesh_events.details_json.position_latency_ms` 独立计算 28,393 个有效样本：

| 指标 | 结果 |
|---|---:|
| 实际墙钟 | 24,000.379 s |
| P50 / P95 / P99 | 622 / 1,134 / 3,877 ms |
| 最大值 | 6,639 ms |
| 超过 10 秒 / 30 秒 | 0 / 0 |
| 队列峰值（Raw / Parser / UDP） | 13 / 8 / 13 |
| 最老等待峰值 | 1.005 s |
| 停止时队列 | 全部 0 |

长稳停止前阶段 P95 为接收→Raw 3 ms、Raw→Parse 112 ms、Parse→Position 1,029 ms；滚动 P95/P99 峰值约 1,130/2,192 ms。独立 normal/burst 结果不与故障恢复窗口混合。

## 判定

正常负载 `POSITION_P95<=10s`、`POSITION_P99<=30s` 满足。`POSITION_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`；限制是合成数据、loopback、设备时间精度和未逐事件测量 UI Available Time。
