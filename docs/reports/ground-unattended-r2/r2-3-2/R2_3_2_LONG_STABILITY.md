# R2.3.2 长稳收尾

## 政策与实际时段

- 原目标：28,800 秒（8 小时）真实墙钟；不使用时间加速。
- 用户在 2026-11-10 明确要求立即结束，不再等待剩余时长，也不补跑剩余 1.5 小时。
- 开始：`2026-11-10T08:57:10.438+08:00`。
- 结束：`2026-11-10T15:37:10.817+08:00`。
- 实际墙钟：`24,000.379 秒`（约 6 小时 40 分）。
- Runner 原始状态：`FAIL`；原因仅为内部 `actual_seconds >= 28,800` 门槛未满足。`summary.json` 同时记录 `data_complete=true`、正常 stop 成功且 `errors=[]`。
- 本轮政策结论：`SOAK_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`；`LONG_STABILITY_8H=WAIVED_BY_USER`。不得把本次结果描述为 8 小时 PASS。

## 配置与范围

- 100 MR、100 个 primary Heartbeat targets，Heartbeat 周期 5,000 ms。
- AC poll interval 60 秒；每分钟写入 `metrics.ndjson`，共 400 个采样。
- 本机 loopback UDP；deterministic fixture seed 232；包含正常事件、重复、乱序、未知 AP、坏格式和周期突发。
- fping 使用 in-process synthetic runner，child process count 为 0；不冒充真实 `fping.exe`。
- 证据根：`D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-long-20261110-085709-e4e2b010`。
- 运行日志：`D:\study\NetConsole-Workspace\reports\tests\r2-3-2-long-stability\long-runner.log`。

## Syslog / Raw / Parser

| 指标 | 实际结果 |
|---|---:|
| Syslog 总发送 | 30,424 |
| UDP 接收 | 30,424 |
| Raw 写入 | 30,424 |
| Parser 完成 | 30,424 |
| 内部丢弃 | 0 |
| 解析失败 | 0 |
| 解析忽略（坏格式） | 510 |
| 未识别 AP 注入 | 557 |
| 周期突发 | 152 |
| 重复事件注入 | 1,410 |
| 乱序事件注入 | 826 |

接收、Raw 写入和停止前快照均为 30,424，停止结果 `data_complete=true`、`queue_empty=true`、`udp_port_released=true`、`projection_flushed=true`、`metadata_flushed=true`、`compression_flushed=true`。独立 Raw 审计进一步确认：SQLite 中 syslog Raw 文件 800 行记录、`sum(record_count)=30,424`；文件系统中 802 个 plain `.ndjson` 的行数为 30,424，736 个 gzip 文件均可读取。`summary.json` 的 `syslog.raw_record_count=7,452` 是运行器调用分页 Raw 列表造成的报告字段缺陷，不是数据缺失；该代码已改为使用停止快照的 authoritative written count。

## 位置延迟与准确性

从 SQLite `ground_unattended_wmesh_events.details_json.position_latency_ms` 独立计算 28,393 个有效位置样本：

| 指标 | 结果 |
|---|---:|
| P50 | 622 ms |
| P95 | 1,134 ms |
| P99 | 3,877 ms |
| 最大值 | 6,639 ms |
| 超过 10 秒 | 0 |
| 超过 30 秒 | 0 |
| 最终 AP-B | 100/100 MR |
| 位置状态行 | 100 |

数据库中的位置结果为 `POSITION_UPDATED=27,010`、`OUT_OF_ORDER_POSITION_EVENT=826`、`POSITION_RETAINED_UNRESOLVED=557`；状态累计重复事件 1,521、乱序事件 826。未知 AP 被保留为 unresolved，不关联到已知 AP；旧事件没有覆盖更新状态；历史事件仍在 Raw/W-Mesh history 中。事件时间精度为脱敏 Fixture 的 `DEVICE_TIMESTAMP` 毫秒级本机墙钟，不构成现场设备时钟证明。

正常负载目标 `POSITION_P95<=10s`、`POSITION_P99<=30s` 满足。独立 normal/burst latency runner 仍分别保留 506/973/1010 ms 与 2120/5899/6286 ms 的结果，未与长稳故障窗口混合。

## Heartbeat / AC / 资源

- Heartbeat：100 targets、9 个 in-process worker/process slots、478,184 samples；停止时 9/9 worker 停止、无存活 worker、元数据持久化成功、Heartbeat compression worker 停止；无真实 fping child。
- Ping 汇总：2,390,920 sent、2,390,920 success、0 loss；RTT min/avg/max 为 1.0/1.1999/1.4 ms，最大 loss rate 0%。
- AC：376 polls、360 accepted snapshots、23 timeouts、23 failure windows、16 partial、34 duplicate；delta 为 ADDED 100、UPDATED 18,460、UNCHANGED 17,440、UNKNOWN 1,584；reconciliation 为 `SYSLOG_NEWER=3,099`、`AC_NEWER=34,047`、`STALE=300`、`UNKNOWN=16`，没有 AC error。AC 查询耗时没有单独持久化，报告不伪造毫秒值。
- 资源采样：RSS 69,160,960→108,236,800 bytes，峰值 126,242,816 bytes；线程 17→16，范围 16–17；CPU process time 3,115.609 秒；Raw/Parser 队列峰值分别 13/8，UDP 队列峰值 13，最老等待峰值 1.005 秒，停止时全部清零。
- 压缩队列曾有界满提示（`compression queue is full`），原始 NDJSON 未丢失；压缩完成/失败/跳过计数为 787/0/13，作为低资源与现场存储规格 caveat 保留。
- SQLite 独立校验：`PRAGMA integrity_check=ok`，`foreign_key_check=[]`。

## 判定

本报告证明的是约 6 小时 40 分真实墙钟的本地合成集成稳定性。用户主动豁免剩余时长，因此 `LONG_STABILITY_8H=WAIVED_BY_USER`；整体 R2.3.2 仍受 Full Gate 基线失败、正式安装器 push 保护和现场不可用边界约束，不能作为现场或发布 PASS。
