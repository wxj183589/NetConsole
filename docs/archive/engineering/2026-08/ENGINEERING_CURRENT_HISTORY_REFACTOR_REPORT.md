# Engineering Current/History Refactor Report

本轮不是继续优化 HistoryStore，而是完成工程态事实源切换：Current 保存最新状态，Recent 保存最近 10 条有效状态变化，时间戳变化不再制造历史事件。四类设备事实和 FIT-AP Radio 已统一 helper；AP LLDP/AP Optical 复用 bounded authority；Trackside 消费 Current/active snapshot。

最终 main commit：`afa35c06`

代码、迁移和验证详情分别见：

- `docs/archive/engineering/2026-08/ENGINEERING_STATE_STORAGE_AUDIT.md`
- `docs/archive/migrations/2026-08/ENGINEERING_RECENT10_MIGRATION_REPORT.md`
- `docs/archive/engineering/2026-08/LEGACY_HISTORYSTORE_RETIREMENT_REPORT.md`
- `docs/archive/performance/2026-08/TRACKSIDE_CURRENT_SNAPSHOT_PERFORMANCE_REPORT.md`
