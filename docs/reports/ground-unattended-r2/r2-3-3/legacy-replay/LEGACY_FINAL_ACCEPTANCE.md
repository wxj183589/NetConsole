# 原版历史归档最终验收

## 验收结论

| 验收项 | 结论 |
|---|---|
| ARCHIVE_INTEGRITY | PASS |
| ARCHIVE_DEDUPLICATION | PASS |
| SYSLOG_REPLAY | PASS |
| WMESH_LINKUP / LINKDOWN / ACTIVE_SWITCH | PASS |
| MR_IDENTITY_MAPPING | PASS_WITH_LIMITATION：源 IP 未自动信任 |
| AP_IDENTITY_MAPPING | PASS_WITH_LIMITATION：严格/扩展身份均保留未解析项 |
| POSITION_CORRECTNESS | PASS_WITH_LIMITATION：与旧 scheduler Current/Previous 可比较项 100% 一致，旧投影不是绝对真值 |
| POSITION_HISTORY | PASS：39,827 条 WMESH 参与回放，原始日志仍保留 |
| PING_HISTORY | REVIEW：原始样本与 manifest/日摘要计数不一致 |
| AC_SNAPSHOT_DELTA | PASS |
| SYSLOG_AC_RECONCILIATION | PASS：AC_NEWER/STALE 被明确分类，不覆盖 Syslog Current |
| THREE_CHANNEL_TIMELINE | PASS：三通道交集 35 MR |
| LEGACY_COMPATIBILITY | PASS |
| FULL_LOCAL_REGRESSION | PENDING_LOCAL_GATES |
| LEGACY_REPLAY_ACCEPTANCE | PASS_WITH_LIMITATION |

## 最终判断

杭州地铁 10 号线这份归档可以被当前 Parser、PositionEngine、AC Delta、Ping 统计和三通道时间线工具读取并回放。Syslog WMESH 业务事件、MR/AP 精确身份边界、Current/Previous 位置归并和历史保全均通过离线证据验证。

本次不把 Ping 摘要计数差异或 AP 未确认身份伪装成通过；它们作为归档质量/现场数据限制保留在报告中。线上位置更新 P95≤10 秒、P99≤30 秒仍需带原始阶段时间的实时或合成负载测试单独验收。

