# R2.3.3 AC Delta 与 Syslog 对账

## 本地测试

AC 轮询保留全量快照 Delta，旧 AC 延迟快照不能无条件覆盖已提交的 Syslog 位置。AC 查询 timing 字段、timeout 计数和 snapshot processing 字段由 `mesh_link_refresh_service.py`、`mesh_link_resident_polling_service.py` 写入并由 Ground health API 暴露。

## 杭州 10 号线归档对照

只读回放统计：389 个 snapshot、37,511 行、32,402 行含位置；Delta 为 `ADDED=213`、`UPDATED=9,057`、`REMOVED=174`、`UNCHANGED=28,089`、`UNKNOWN=152`，2 个过期/不完整快照被拒绝。对账按时间分类为 `AC_NEWER=29`、`STALE=6`（扩大到 ordering-only 窗口为 AC_NEWER 35），未把 AC 结果无条件写回 Syslog Current。

证据文件：`docs/reports/ground-unattended-r2/r2-3-3/legacy-replay/LEGACY_AC_SNAPSHOT_DIFF.md`、`LEGACY_POSITION_COMPARISON.md`。

结论：`AC_DELTA=PASS_WITH_EVIDENCE_CAVEATS`，`AC_RECONCILIATION=PASS_WITH_EVIDENCE_CAVEATS`。归档没有真实线上阶段时间，AC/Syslog 的现场时钟关系仍需局点确认。
