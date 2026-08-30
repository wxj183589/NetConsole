# Formerly Unsupported History Consumer Contract

状态：`RETIRED_AND_MIGRATED`（2026-08-29）

`ac_fit_ap_unauthenticated_history` 和 `ac_station_online_summary_history` 曾因
没有稳定的 HistoryStore target event contract 被标记为 unsupported。该限制已由
本次专用 Current + Recent10 模型解决；旧表不再作为外部 HistoryStore 的迁移输入或
运行时 authority。

## Consumer audit

| 数据类别 | runtime writer | runtime reader | 新 authority |
| --- | --- | --- | --- |
| FIT AP unauthenticated | `AcRepository.replace_fit_ap_unauthenticated()` | `list_fit_ap_unauthenticated_history()`、`_enrich_resources_with_unauthenticated_status()`、Trackside AP snapshot | `ac_fit_ap_unauthenticated` + `fit_ap_unauthenticated_recent` |
| Station online summary | `AcRepository.save_station_online_summary_history()` | station summary list/page/count 与相关导出 | `station_online_summary_current` + `station_online_summary_recent` |

两类 reader 都只调用 `devices.db` 本地 projection。缺少旧 source rows 不会触发
HistoryStore fallback，也不会自动创建 `<site>/db/history`。

## Retirement contract

Legacy external HistoryStore 的迁移、回放、验证和 retirement CLI 均已删除。旧表、旧
catalog 和月分片不参与普通查询、导出、Update All、启动或任何 maintenance workflow；
它们不会触发 fallback，也不会创建 `<site>/db/history`。

## Required evidence

- `tests/test_current_history_retention.py` 覆盖两类模型的 Current/Recent10、
  去重、上限和新站点不创建 history。
- `tests/test_history_store_cutover_compat.py`、`tests/test_ac_management.py`、
  `tests/test_trackside_ap_web.py` 验证旧表/旧事件不会恢复运行时事实。
- [DATA_LAYOUT.md](./DATA_LAYOUT.md) 记录 Current/Recent10、TaskHistoryStore 与 Legacy
  external HistoryStore 的当前边界。
