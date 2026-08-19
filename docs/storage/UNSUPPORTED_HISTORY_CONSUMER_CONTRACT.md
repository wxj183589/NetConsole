# Unsupported History Consumer Contract

状态：`CONFIRMED`（代码消费者存在）；迁移状态：`SUPPORTED_TARGET_EVENT_CONTRACT`。

`ac_fit_ap_unauthenticated_history` 和 `ac_station_online_summary_history` 不能继续标成“无消费者”。
两者仍保留 legacy source 作为兼容事实源，同时已定义稳定的 HistoryStore target event contract；
新写入按实体进入 bounded change history，legacy source 不在本轮删除。

## Consumer audit

| 表 | producer / writer | readers / export | 语义结论 |
| --- | --- | --- | --- |
| `ac_fit_ap_unauthenticated_history` | `AcRepository.replace_fit_ap_unauthenticated()`；H3C AC collector 写入当前快照并追加历史行 | `list_fit_ap_unauthenticated_history()`；`_enrich_resources_with_unauthenticated_status()`；轨旁 AP business snapshot；AC/FIT-AP tests | 有业务价值：用于判断“历史新上线/已固化”及最后一次未认证证据。仅从当前 `ac_fit_ap_unauthenticated` 无法重建历史时间序列。 |
| `ac_station_online_summary_history` | `AcRepository.save_station_online_summary_history()`；legacy task `ac_overview_history_snapshot` | `list_station_online_summary_history()`、分页/count handler、`common_exporters.py` 导出；AC management tests | 有业务价值：站点级在线率历史。当前 overview 只能重建最新快照，不能重建历史采样。 |

## Migration contract

- Legacy tables remain available for compatibility; HistoryStore is the target read contract for new writes.
- Proposed target kinds are `fit_ap_unauthenticated` (entity key `ac_device_uuid`) and
  `station_online_summary` (entity key `site_name`), matching the existing HistoryStore kind aliases.
- Every target event must preserve source table/id provenance, `collected_at`, canonical payload,
  row counts and semantic equivalence. Invalid timestamps or shape mismatches make the run `NOT_READY`.
- Copy/verify may be rehearsed on an isolated `D:\study` database. `SHARD_VERIFIED` and explicit CAS
  cutover are prerequisites; no source delete, DROP, VACUUM or physical shrink is authorized.
- Rebuild from current tables is **not** supported. A rebuildable diagnostic view may read legacy rows,
  but it is not an authority and must not be used to mark source deletion eligible.

Invalid rows fail closed with diagnostics; valid rows use the supported target contract. Source retirement
and physical cleanup remain separately gated and are not part of this change.

## Required evidence

- `tests/test_ac_unauthenticated_and_trackside_merge.py` and `tests/test_ac_management.py` prove write,
  read, enrichment and station-history pagination behavior.
- `tests/test_history_legacy_migration.py` proves both tables are registered as `SUPPORTED` targets and
  invalid rows are not emitted.
- `tests/test_unsupported_history_contract.py` verifies this contract against the producer/consumer paths.

