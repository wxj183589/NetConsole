# History Storage V2（历史退役候选格式）

## 状态与边界

分类：HISTORICAL_RECORD。本文保留 V2 候选格式、隔离迁移和查询结果的历史技术记录，不是当前运行时规范。当前运行时边界以
[Data Layout](./DATA_LAYOUT.md) 和
[Storage Architecture](./STORAGE_ARCHITECTURE.md) 为准。

History Storage V2 是已退役的月分片候选格式，不再是运行时写入或查询格式。`HistoryStore`
及其 catalog、查询、计数和 COPY-only migration 工具均已退役；运行时不创建
`history_outbox`，不启动历史 drain，也不对 `db/history` 做 fallback。

- 旧候选工具的新写统一进入 `history_events_v2`；正式运行时四类业务事实写入
  `devices.db` 的 Current/Recent10 模型。
- 既有 `history_events` V1 表不重写、不删除，V1-only 和同月 V1/V2 mixed shard 均继续可读。
- `event_type=legacy` 的迁移副本属于已完成迁移的历史记录；源 legacy table 不再被读取。
- 旧 `history_outbox`/`history_state` 仅属于 HistoryStore 生命周期；候选迁移完成后删除这两个内部表，
  不删除仍承担 bounded Current/Recent10 语义的专用 `*_history` 表。
- 已验证且无错误的单个源表不再有维护工具；正式运行时不切换为 shard 查询事实源，
  也不保留 HistoryStore 作为业务 fallback。

## 物理基线

隔离的真实 `devices.db` snapshot 包含 2,094,944 行 supported legacy history。将这些表与
索引受控重建后的物理基线为 774,860,800 B。相同 snapshot 的 V1 migration target 为
2,778,030,080 B，即 `3.585199x` 放大。

V1 target 的主要占用为：

| 组成 | 字节 | 占比 |
| --- | ---: | ---: |
| payload JSON | 1,769,086,976 | 63.6813% |
| envelope + primary index | 459,341,824 | 16.5348% |
| secondary indexes | 446,492,672 | 16.0723% |
| rebuild fragmentation | 100,761,600 | 3.6271% |
| catalog | 2,347,008 | 0.0845% |

两个 V1 secondary index 分别占 282,853,376 B（entity/time）和 163,639,296 B
（time）。采样的 26,163,598 B payload 中，重复 migration metadata 为 2,347,203 B
（8.9713%），payload 内重复 `collected_at` 为 1,162,610 B（4.4436%）。去除这两类
envelope 字段并将 JSON object 映射为字段数组后剩余 10,651,572 B（40.7114%）；扣除
上述 envelope 后，重复字段名和 object 结构约占 12,002,213 B（45.8737%）。字段数组再用
zlib level 1 压缩时为 6,657,930 B（原 payload 的 25.4473%）。

## 候选比较

| 候选 | 结论 |
| --- | --- |
| 仅精简 envelope | 不足。payload 和文本 secondary indexes 仍是主要占用。 |
| schema-mapped compact payload | 采用。字段 shape 只在 dictionary 中保存一次，每行只保存 value array。 |
| 按 kind 建 typed tables | 暂不采用。会复制多套 schema/migration/query contract，并扩大 producer 与旧格式兼容面。 |
| 全 payload 压缩 | 采用自适应模式。schema array 仅在 zlib level 1 至少节省 4 B 时压缩，否则保存 raw UTF-8 JSON。 |
| index optimization | 采用。kind/entity/event type 字典化，精确实体查询固定走 entity/time，类型时间查询固定走 kind/time。 |

## V2 格式

每个 V2 shard 使用 `storage_schema_version=2`、`payload_schema_version=2`，并包含：

- `history_kinds_v2`、`history_entities_v2`、`history_event_types_v2`；
- `history_payload_schemas_v2`，保存有序字段名和 payload schema version；
- `history_events_v2 WITHOUT ROWID`，其中 SHA-256 event ID 从 64 字符 hex 改为 32 B BLOB；
- `idx_history_events_v2_entity_time(entity_id, collected_at, event_id)`；
- `idx_history_events_v2_kind_time(kind_id, collected_at, event_id)`；
- `history_storage_metadata`，保存 storage/payload version。

`collected_at`、`legacy_source_table` 和 `legacy_source_id` 不再逐行重复进入 compact payload。
legacy source table、source key range、month、digest 和 deterministic sample 由 catalog range journal
持久化；显式 cutover 必须以 `VERIFIED` range provenance 为依据。读取未知 payload codec/version
或写入更高 storage version 会显式失败，不会静默降级。payload 原本没有 `created_at` 时，V2 读取也
不会新增该字段，保持 V1 shape。

## 真实 Snapshot 结果

真实 880,967,680 B snapshot 在隔离目录完成全部十张表迁移：

| 指标 | 结果 |
| --- | ---: |
| copied target events | 1,715,712 |
| verified source rows | 2,094,944 |
| verified projection duplicates | 379,232 |
| errors | 0 |
| target bytes | 872,407,040 |
| amplification / legacy physical baseline | `1.125889x` |
| target / V1 target | `31.4038%` |
| active throughput | 2,036.25 rows/s |
| chunk latency p50 / p95 / p99 / max | 172 / 785 / 1007 / 1155 ms |

三个 shard 分别有 359,810、1,007,777、348,125 行，`quick_check=ok`、freelist=0，且
storage/payload version 均为 2。source snapshot 保留，未执行 DELETE、DROP 或 VACUUM。

## 查询结果

真实 V1/V2 target 各运行 10 次，五类查询的行数、排序和 event ID 摘要全部一致：

| 查询 | V1 p50 | V2 p50 |
| --- | ---: | ---: |
| 单实体最近 100 | 3.332 ms | 8.613 ms |
| 单实体时间范围 1000 | 13.778 ms | 38.249 ms |
| 单 kind 时间范围 1000 | 356.758 ms | 64.914 ms |
| 跨月最近 200 | 232.809 ms | 14.773 ms |
| offset 500 / limit 100 | 279.981 ms | 42.976 ms |

V2 exact-entity plan 使用 `idx_history_events_v2_entity_time`，kind/time plan 使用
`idx_history_events_v2_kind_time`。V1 exact-entity plan 使用旧 entity/time index；V1 kind/time
基线实际选择旧 entity/time index 并建立临时排序 B-tree，没有命中旧 time index。V2 的精确实体
查询因 dictionary join 和 payload 解压有固定开销，但类型范围、跨月和 offset 查询显著降低延迟。

## 剩余门禁

- `SERVER_HDD_STORAGE_V2_TEST=PENDING`：开发机 snapshot 结果不能替代真实 Windows Server HDD
  长时运行和无人值守并发验收。
- `STORAGE_V2_READY` 只表示新写格式、兼容读取和隔离 snapshot 验证完成。
- 已验证隔离 catalog 的历史查询能力仅供维护工具审计；它不是运行时业务 authority。
- `SOURCE_DELETE_DESIGN_READY` 不代表自动删除；Production 的 `devices.db` 替换和旧目录删除
  必须由本任务的显式授权、候选报告、备份和 post-verify 闭合。
