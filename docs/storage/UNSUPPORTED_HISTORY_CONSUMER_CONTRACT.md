# Unsupported History Consumer Contract

状态：`CONFIRMED`（代码消费者存在）；迁移状态：`BLOCKED_BY_TARGET_EVENT_CONTRACT`。

`ac_fit_ap_unauthenticated_history` 和 `ac_station_online_summary_history` 不能继续标成“无消费者”。
两者目前仍是 legacy projection，HistoryStore 尚未为其定义稳定的 target event schema，因此本轮不
执行 source retirement、删除或自动迁移。

## Consumer audit

| 表 | producer / writer | readers / export | 语义结论 |
| --- | --- | --- | --- |
| `ac_fit_ap_unauthenticated_history` | `AcRepository.replace_fit_ap_unauthenticated()`；H3C AC collector 写入当前快照并追加历史行 | `list_fit_ap_unauthenticated_history()`；`_enrich_resources_with_unauthenticated_status()`；轨旁 AP business snapshot；AC/FIT-AP tests | 有业务价值：用于判断“历史新上线/已固化”及最后一次未认证证据。仅从当前 `ac_fit_ap_unauthenticated` 无法重建历史时间序列。 |
| `ac_station_online_summary_history` | `AcRepository.save_station_online_summary_history()`；legacy task `ac_overview_history_snapshot` | `list_station_online_summary_history()`、分页/count handler、`common_exporters.py` 导出；AC management tests | 有业务价值：站点级在线率历史。当前 overview 只能重建最新快照，不能重建历史采样。 |

## Migration contract

- Authority remains the legacy table until a reviewed HistoryStore event contract exists.
- Proposed target kinds are `fit_ap_unauthenticated` (entity key `ac_device_uuid`) and
  `station_online_summary` (entity key `site_name`), matching the existing HistoryStore kind aliases.
- Every target event must preserve source table/id provenance, `collected_at`, canonical payload,
  row counts and semantic equivalence. Invalid timestamps or shape mismatches make the run `NOT_READY`.
- Copy/verify may be rehearsed on an isolated `D:\study` database. `SHARD_VERIFIED` and explicit CAS
  cutover are prerequisites; no source delete, DROP, VACUUM or physical shrink is authorized.
- Rebuild from current tables is **not** supported. A rebuildable diagnostic view may read legacy rows,
  but it is not an authority and must not be used to mark source deletion eligible.

The existing `UNSUPPORTED` classification in `HistoryLegacyMigrationService` is therefore a safety gate,
not evidence that the tables are dead. It must remain fail-closed until the target event schema and all
consumer migrations are implemented.

## Required evidence

- `tests/test_ac_unauthenticated_and_trackside_merge.py` and `tests/test_ac_management.py` prove write,
  read, enrichment and station-history pagination behavior.
- `tests/test_history_legacy_migration.py` proves both tables remain `UNSUPPORTED` and are not copied by
  the generic migration.
- `tests/test_unsupported_history_contract.py` verifies this contract against the producer/consumer paths.

