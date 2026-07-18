# AP Identity Job 宿主评估（冻结历史）

## 文档状态

本文原本评估阶段 8.2 如何把 `DiagnosticsSummaryViewModel` 接入 Qt Job/Dialog。Qt 页面、Manager、QProcess Adapter 与候选 Dialog 路径已经删除，原评估全文由 Git 历史保存，不构成恢复 Qt 宿主、结果持久化或新增 Feature 的授权。

## 当前事实

- Electron 提供独立统一任务窗口，任务事实源仍是 `TaskApplicationService`、Task/Export Repository 和 owner capability。
- AP Identity 脱敏结构位于 `src/netconsole/models/diagnostics_summary.py`。
- 导出诊断适配位于 `src/netconsole/services/export_identity_diagnostics.py`。
- 当前尚未把 AP Identity 摘要接入统一任务窗口或具名 Vue 诊断页；缺少真实局点采样和脱敏复核时必须保持隐藏。
- 统一任务窗口不得持久化 raw result、samples、evidence、明文身份、绝对路径或跨局点引用。

## 若后续接入

1. 只允许从 owner 的终态事件复制严格允许列表字段。
2. 入口必须显式、默认关闭、internal-only，并受 Feature Registry 控制。
3. diagnostics 的 disabled/unavailable/failed 不得改变原 Job/Export 终态。
4. 窗口关闭后释放前端订阅和 ViewModel，但不停止后台任务。
5. 必须覆盖权限、脱敏、并发 Job 隔离、页面重开恢复和真实局点验收。

当前结论保持 `HOLD / NOT_WIRED`。活动架构见 [Job Center](JOB_CENTER.md)、[AP Identity 总览](AP_IDENTITY.md)与[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)。
