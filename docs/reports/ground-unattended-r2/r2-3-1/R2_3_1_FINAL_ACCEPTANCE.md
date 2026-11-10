# R2.3.1 最终验收

## 总结

`LOCAL_ACCEPTANCE=PARTIAL`。本地核心链路已经有可重复的真实 loopback UDP 证据：Syslog/Raw/Parser/Position、Heartbeat 100 MR/200 主备目标、AC delta/reconciliation、组件隔离和同库重启均通过；正常合成负载位置 P95/P99 满足 10/30 秒目标。8 小时长稳未运行，当前环境无法提供可见 Electron 截图，完整 Gate 受已有并行 dirty 修改影响。

## 验收矩阵

| Gate | 状态 | 证据/说明 |
|---|---|---|
| LOCAL_UDP_RECEIVER | PASS | 402 条 loopback UDP |
| SYSLOG_100_MR | PASS | 100 MR synthetic fixture |
| RAW_PERSISTENCE | PASS | 402 初始 Raw，stop data complete |
| PARSER_CORRECTNESS | PASS | 402 parse success；74 项专项 |
| POSITION_CORRECTNESS | PASS | 100/100 最终 AP-B，历史保留 |
| POSITION_P95 | PASS | 4309 ms |
| POSITION_P99 | PASS | 4562 ms |
| EVENT_ORDERING | PASS | 迟到旧 A 不覆盖 B |
| EVENT_DEDUPLICATION | PASS | 100 重复事件合并 |
| POSITION_FRESHNESS | PASS | 时间字段与队列指标可读 |
| AC_60S | PASS_WITH_EVIDENCE_CAVEATS | 默认配置/专项测试；未等待现场周期 |
| AC_DELTA_SYNC | PASS | 301 条 delta，含五类变更 |
| AC_RECONCILIATION | PASS | SYSLOG_NEWER→CONSISTENT |
| HEARTBEAT_100_IP | PASS | 100 primary |
| HEARTBEAT_200_IP | PASS | 100 primary + 100 backup |
| COMPONENT_ISOLATION | PASS | 慢 AC/故障不阻塞 Heartbeat/Syslog |
| BACKEND_RECOVERY | PASS_WITH_EVIDENCE_CAVEATS | 本地 lifecycle/同库恢复；非现场进程 kill |
| SQLITE_RECOVERY | PASS_WITH_EVIDENCE_CAVEATS | lock/recovery 测试；非物理磁盘故障 |
| ELECTRON_GUI | PARTIAL | 真实 Electron smoke 通过；无可见截图 |
| LONG_STABILITY_8H | NOT_RUN | 未执行 8 小时 |
| FULL_LOCAL_GATE | PARTIAL | 43 个非 Ground 范围既有 dirty/clean-worktree 失败 |
| FIELD_ACCEPTANCE | NOT_AVAILABLE | 无真实车辆/AP/AC/现场网络 |

## 判定原则

几秒延迟被接受；本地正常运行 P95≤10 秒、P99≤30 秒。位置准确性、历史完整性、旧事件不覆盖、未知身份不强行关联优先于毫秒级刷新。以上结果不对现场网络故障、UDP 丢包、设备停机或 Backend 长时间故障作 30 秒承诺。
