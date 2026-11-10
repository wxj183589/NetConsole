# R2.3.2 SOAK Final Report

## 结论

`SOAK_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`

`LONG_STABILITY_8H=WAIVED_BY_USER`

用户在实际运行约 6 小时 40 分后主动要求停止，本报告不把该结果写成 8 小时 PASS，也不补跑剩余时长。证据显示停止排空成功、原始日志完整、位置最终一致、队列无持续积压、SQLite 完整性通过；仍需保留合成数据、无现场设备和压缩吞吐 caveat。

## 墙钟与配置

| 项目 | 结果 |
|---|---|
| 开始 | 2026-11-10T08:57:10.438+08:00 |
| 结束 | 2026-11-10T15:37:10.817+08:00 |
| 实际墙钟 | 24,000.379 s |
| 模拟车辆/MR | 100/100 |
| Heartbeat targets | 100 primary |
| Syslog UDP | 127.0.0.1 loopback |
| AC 周期 | 60 s |
| 证据根 | `D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-long-20261110-085709-e4e2b010` |

## 数据完整性

- Syslog 发送、接收、Raw 写入、Parser 完成：`30,424 / 30,424 / 30,424 / 30,424`。
- 内部丢弃、解析失败、Raw 写失败：`0 / 0 / 0`。
- 解析忽略的坏格式：510；未识别 AP：557；这些记录仍保留 Raw，不清空已有位置。
- 停止快照：`data_complete=true`、`queue_empty=true`、端口释放、投影/metadata/compression flush 成功。
- Raw 独立审计：SQLite syslog Raw records sum 30,424；plain NDJSON 行数 30,424；gzip 736 个文件均可读。
- SQLite：`integrity_check=ok`，`foreign_key_check=[]`。

## 位置

从 28,393 个 W-Mesh 事件的 `position_latency_ms` 计算：P50 622 ms、P95 1,134 ms、P99 3,877 ms、最大 6,639 ms；超过 10 秒和 30 秒均为 0。100/100 MR 最终 AP-B 正确率为 100%。位置结果保留 826 个乱序事件和 1,521 个重复计数，557 个未知 AP 为 unresolved，不强行关联。独立 normal/burst 测试结果为 506/973/1010 ms 和 2120/5899/6286 ms，未与长稳混合。

## Heartbeat / AC / 资源

- Heartbeat：478,184 samples；2,390,920 sent、2,390,920 success、0 loss；RTT min/avg/max 1.0/1.1999/1.4 ms；停止 9/9 worker，无真实 fping child。
- AC：376 polls、360 accepted、23 timeout、16 partial、34 duplicate；Syslog/AC reconciliation 记录 `SYSLOG_NEWER=3,099`、`STALE=300` 等状态，AC 失败未停止 Syslog/Heartbeat。查询耗时未单独持久化，未伪造数值。
- RSS 69.2→108.2 MB，峰值 126.2 MB；线程范围 16–17；Raw/Parser/UDP 队列峰值 13/8/13，最老等待峰值 1.005 s，停止时均清零。
- 压缩队列出现有界满提示，但 compression failed=0，原始 NDJSON 保留；作为存储规格 caveat 记录。

## 证据与限制

原始日志：`D:\study\NetConsole-Workspace\reports\tests\r2-3-2-long-stability\long-runner.log`；汇总：`summary.json`；采样：`metrics.ndjson`。`summary.json` 中旧的分页 Raw 汇总字段为 7,452，独立审计和停止快照确认真实 Raw 写入 30,424；候选脚本已修复该统计口径。所有结果仅适用于本地合成 inventory、脱敏 Fixture 和 loopback，不替代现场设备、现场网络、真实 AC、真实 fping 或 Field Acceptance。
