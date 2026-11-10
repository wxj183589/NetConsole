# Syslog 全量回放

## 回放路径

回放复用了当前 `WmeshRealtimeParser`、`GroundApDisplayResolver`、`SyslogUdpReceiver._process`、`PositionEngine` 与 `GroundUnattendedRepository.commit_wmesh_projection_batch`。严格身份回放完整写入隔离 SQLite；扩展 AP 身份回放使用相同 Parser/Resolver/PositionEngine 做接收序与事件时间序内存对照，避免重复写入同一份 40,290 行历史。

原始归档行中的 `device_time` 字段为空。工具只从脱敏 H3C 原文提取时间，并按当前时钟质量规则决定是否使用；未凭空填充事件时间。

## 结果

| 指标 | 结果 |
|---|---:|
| Syslog 原始行 | 40,290 |
| Parser 产生结构化事件 | 40,120 |
| WMESH 事件 | 39,827 |
| 非 WMESH 结构化事件 | CFGMAN 262、IFNET 31 |
| 非业务/未解析行 | 170；均命中重启、命令或 IFNET 非 WMESH 标记 |
| 可信设备时间事件 | 39,757 |
| 仅接收时间事件 | 363 |
| 回放 MR 位置状态 | 35 |

| 回放模式 | 事件数 | 位置更新 | 重复 | 乱序 | 失败 |
|---|---:|---:|---:|---:|---:|
| 严格 AC 身份 + 接收序 + Repository | 39,778 个唯一 WMESH 投影行 | 32,484 | 0 个 Engine 标记；Repository 记录 49 个语义去重键 | 69 | 0 |
| 扩展身份 + 接收序 + PositionEngine | 39,827 | 32,815 | 36 | 69 | 0 |
| 扩展身份 + 有效事件时间序 + PositionEngine | 39,827 | 32,875 | 36 | 0 | 0 |

严格 Repository 回放的 49 条少于原始 WMESH 行，是按同一 MR/事件时间/事件身份的去重投影，不是原始行删除；原始历史完整性见 [LEGACY_ARCHIVE_INTEGRITY.md](LEGACY_ARCHIVE_INTEGRITY.md)。

## 原始时间阶段限制

归档没有原始 `Raw Persist Time`、`Parse Complete Time`、`Position Commit Time`、`UI Available Time`。因此本次只报告离线读取、解析、归并和持久化处理耗时，不能从归档反推出线上 Event Time→UI Available 延迟，也不能用于宣称 P95/P99 30 秒指标。

