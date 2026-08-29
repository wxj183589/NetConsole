# Formerly Unsupported History Consumer Contract

状态：`RETIRED_AND_MIGRATED`（2026-08-29）

`ac_fit_ap_unauthenticated_history` 和 `ac_station_online_summary_history` 曾因
没有稳定的 HistoryStore target event contract 被标记为 unsupported。该限制已由
本次专用 Current + Recent10 模型解决；旧表只保留为显式 maintenance 输入，不能
再作为运行时 authority。

## Consumer audit

| 数据类别 | runtime writer | runtime reader | 新 authority |
| --- | --- | --- | --- |
| FIT AP unauthenticated | `AcRepository.replace_fit_ap_unauthenticated()` | `list_fit_ap_unauthenticated_history()`、`_enrich_resources_with_unauthenticated_status()`、Trackside AP snapshot | `ac_fit_ap_unauthenticated` + `fit_ap_unauthenticated_recent` |
| Station online summary | `AcRepository.save_station_online_summary_history()` | station summary list/page/count 与相关导出 | `station_online_summary_current` + `station_online_summary_recent` |

两类 reader 都只调用 `devices.db` 本地 projection。缺少旧 source rows 不会触发
HistoryStore fallback，也不会自动创建 `<site>/db/history`。

## Migration contract

- `scripts/maintenance/retire_legacy_history_store.py prepare` 按
  `collected_at/updated_at/created_at` 和稳定事件 id 排序，在隔离候选库中回放；
  当前事实进入 Current，变化窗口进入 Recent10，每个资源最多 10 条。
- 当前值不以旧历史重建覆盖；无法确定业务身份的行不猜测写入，并在报告中计入
  source/discarded 统计。
- `apply` 先比较 source `devices.db` SHA-256 与 history manifest，备份后原子替换
  候选 `devices.db`，只删除已注册站点的 `db/history`。它只接受精确
  `D:\NetConsoleData` 和显式 `LEGACY_HISTORY_RETIREMENT_AUTHORIZED`。
- 旧表、旧 catalog 和月分片不再参与普通查询、导出、Update All 或启动；其他
  HistoryStore maintenance 仍需显式调用，不能被误当成 runtime consumer。

## Required evidence

- `tests/test_current_history_retention.py` 覆盖两类模型的 Current/Recent10、
  去重、上限和新站点不创建 history。
- `tests/test_history_store_cutover_compat.py`、`tests/test_ac_management.py`、
  `tests/test_trackside_ap_web.py` 验证旧表/旧事件不会恢复运行时事实。
- `docs/storage/HISTORYSTORE_RUNTIME_CONSUMER_MATRIX.md` 记录四类历史、Task Center
  和 maintenance-only 入口的完整前后边界。
