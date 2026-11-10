# 杭州地铁 10 号线归档清单

## 来源与边界

- 来源文件：`2026-11-09_ground_unattended.zip`
- 归档类型：`ground_unattended_daily`
- `site_id`：`hzl10`
- `run_id`：`ground_20261109_fe484f124afe`
- 运行时间：2026-11-09 16:26:25.520 +08:00 至 18:12:31.340 +08:00
- 归档状态：`COMPLETED`，单次会话，轻量监测模式
- 读取边界：直接从 ZIP 流式读取；未解压覆盖原归档，未写入生产数据、开发真实数据或设备

## 容量与成员

| 项目 | 结果 |
|---|---:|
| ZIP 成员总数 | 780 |
| 非目录成员 | 467 |
| 未压缩大小 | 390,810,634 bytes |
| ZIP 成员压缩大小合计 | 17,680,254 bytes |
| JSON/JSONL/NDJSON 有效记录 | 781,503 |
| manifest 文件登记成员 | 466；另有 manifest 自身未在文件清单中登记 |

| 目录/数据集 | 关键内容 |
|---|---|
| `realtime/syslog` | 95 个普通 NDJSON 文件；Syslog 40,290 行 |
| `scheduler_events.jsonl` | 500 条调度投影事件 |
| `ac_snapshots` | 3 个 JSONL 文件，389 个快照、37,511 行 |
| `fleet_ping` | 123 个普通 NDJSON 文件，42 个目标 |
| `ping_summaries` | 18,316 条摘要 JSONL 记录及按 MR/列车 JSON 汇总 |
| `timeline` | 225,897 条三通道关联记录 |
| `evidence` | 脱敏设备采集证据；本次只作归档存在性/格式审计，不复制到仓库 |

## manifest 摘要与实际数据覆盖

manifest 声明主线列车 11、Ping 目标 42、Syslog 记录 40,290、原始文件 218。实际 Syslog 普通文件读取到 40,290 行，Ping 普通文件读取到 216,743 行；Ping 的 manifest/日汇总计数低于原始文件计数，详见 [LEGACY_PING_COMPARISON.md](LEGACY_PING_COMPARISON.md)。
