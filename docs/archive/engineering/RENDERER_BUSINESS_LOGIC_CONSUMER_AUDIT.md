# Renderer Business Logic Consumer Audit

日期：2026-11-23
范围：v1.5.18 候选分支 `codex-A/release-v1.5.18-20261123`

## 结论

本轮审计覆盖了三个 Architecture Guard 目标符号及其实际调用链。三个符号均已从 Renderer 产品路径移除；Backend 现在在 Application Service 出口统一投影 Ping 状态和自然秒统计。Renderer 仍保留状态标签、颜色、坐标和图表序列拼装，这些只消费 Backend 字段。

## 消费者矩阵

| 原始符号 | 原定义 | 直接/间接消费者 | 当前迁移结果 |
| --- | --- | --- | --- |
| `normalizedStatus` | `apps/desktop_renderer/src/components/ground-unattended/pingChartStatus.ts` | 原由 `classifyPingStatus` 使用；间接进入 `pingPointValues`、`mrMonitoringChartOptions`、`GroundPingChart` 和 Quick Ping 图表 | 删除。归一化由 `ping_business.normalize_status` 执行 |
| `classifyPingStatus` | `apps/desktop_renderer/src/components/ground-unattended/pingChartStatus.ts` | 长 Ping 图表 tooltip、点位序列、Quick Ping 统计/图表 | 删除。`ping_business.classify_status` 生成 `status` |
| `naturalSecondLossBuckets` | `apps/desktop_renderer/src/components/ground-unattended/quickPingStatistics.ts` | `quickPingChartOptions` 及历史回放/Quick Ping 图表 | 删除。Backend API 返回 `second_loss_buckets` |

## 输入和业务规则

### Ping 状态

原契约读取 `status/state/result/outcome` 的第一个非空字段，支持 `SUCCESS/OK/CONNECTED`、`TIMEOUT/TIMED_OUT`、`PACKET_LOSS/LOSS/LOST` 和 `UNKNOWN` 别名。显式状态优先于 `ok`、超时标记、错误原因、丢包率和 RTT；无布尔 `ok` 时为 `UNKNOWN`；失败原因含 `TIMEOUT` 时为 `TIMEOUT`，其他失败为 `PACKET_LOSS`；成功但无有效 RTT 为 `UNKNOWN`。

### 自然秒统计

样本时间按 `received_at -> ts -> sample.received_at -> sample.ts` 读取，按 UTC 自然秒 `[start, start + 1s)` 分桶。优先使用 `sample_id` 去重，否则使用 run、target、sequence 和时间戳组成稳定键。每桶返回总数、成功数、丢包数、未知数和丢包率，按桶开始时间排序。

## 当前消费者

- `GroundPingChart.vue`：读取 `point.status`、`point.rtt_display_ms`，仅做 tooltip 和图表展示。
- `mrMonitoringChartOptions.ts`：读取 `status/heartbeat_status`，仅生成 ECharts 序列。
- `QuickPingChart.vue`/`quickPingChartOptions.ts`：读取 `status/loss_percent/rtt_display_ms` 与 Backend `second_loss_buckets`，仅生成坐标序列。
- `QuickPingPage.vue`：请求 Quick Ping 样本页并合并已计算桶；不再从原始样本计算自然秒桶。
- `GroundHistoryPlayback.vue`：请求历史样本页并转交 Backend 桶；保留既有页面级去重统计展示，输入已是 Backend 投影字段。

## 回归入口

- Backend：`tests/test_ground_unattended_ping_business.py`、Ground unattended API/monitoring/heartbeat/quick-ping tests。
- Renderer：`pingChartStatus.test.ts`、`quickPingStatistics.test.ts`、`quickPingChartOptions.test.ts`、`GroundPingChart.test.ts`、`QuickPingPage.test.ts`。
- Architecture Guard：`python scripts/architecture/check_ui_business_logic.py`。
