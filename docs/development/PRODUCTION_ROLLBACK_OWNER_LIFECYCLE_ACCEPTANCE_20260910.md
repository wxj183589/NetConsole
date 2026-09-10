# Production Rollback Owner Lifecycle Acceptance — 2026-09-10

## Scope

本记录只覆盖 Production `TASK_OPERATIONAL_GC` rollback owner lifecycle、当前 9 个
`tasks.db` 的 rollback rebuild 准备和 fresh dry-run Preview。Production GC、DELETE、
VACUUM、replace、restore、schema migration、GUI smoke 均不在本轮执行范围。

Production DataRoot：`D:\NetConsoleData`。

## Root cause

当前模型选择 owner-per-revision（Strategy B），但 `register_rollback_scope` 只向
`config/storage_registry.yaml` append 新 owner，没有执行 `superseded_by` transition。
同时 storage registry Gate 直接按所有 resource-set owner 计数，把已 VERIFIED 的 r1/r2
历史 recovery evidence 与当前 r3 actionable owner 混在一起。

因此 registry 中出现：

- 两个旧宁波 12 号线 scalar cutover owner：`PENDING_PRODUCTION_BACKUP`，继续
  `PROTECT`，不是本轮 9 库 tasks GC 的 actionable owner；
- r1/r2：9/9 VERIFIED，但未标记 historical/superseded；
- r3：9 库当前 source scope，`PENDING_PRODUCTION_BACKUP`。

## Owner lifecycle strategy

选择 `B_OWNER_PER_REVISION_WITH_FORMAL_SUPERSEDE`，原因是当前正式模型已经以
`maintenance_id`、`resources[]` 和 immutable backup set 表达 revision；本轮只补齐
transition 和统计语义，不引入第二套 owner/revision registry。

`storage_registry.yaml` 的职责是静态 owner/evidence map。它保留历史 owner，但只允许
一个未 supersede 的当前 `TASK_OPERATIONAL_GC` resource-set owner；旧 owner 的 backup
仍受保护并可查询，不能继续成为当前执行 authority。

## Lifecycle contract

实现了：

- `ProductionRollbackOwner.lifecycle_state`：从现有 observation/supersede 字段派生
  `PENDING`、`ACTIVE`、`SUPERSEDED`；不伪造历史 owner 为 VERIFIED；
- `current_execution_eligible` 与 `actionable_pending`：只识别当前 9 库 tasks
  resource-set；
- `register_rollback_scope`：新 revision 注册时正式 supersede 旧 actionable revision；
- `reconcile_rollback_owner_lifecycle`：对既有 r3 registry 做一次正式 transition；
- `audit_rollback_owners` 与 CLI `audit-owners`：输出 owner、scope、backup、revision、
  supersede 和 actionable 计数；
- registry writer：允许“一次新 owner append + 多个旧 owner supersede”的受控原子更新，
  拒绝其它批量改写。

## Current audit and transition

审计文件：

`D:\study\NetConsole-Workspace\diagnostic\production-task-lifecycle-final-20260910-202500\PRODUCTION_ROLLBACK_OWNER_AUDIT.json`

transition 结果：

```text
TOTAL_OWNER_COUNT=5
PENDING_OWNER_COUNT=3
HISTORICAL_OWNER_COUNT=2
ACTIONABLE_OWNER_COUNT=1
ACTIONABLE_PENDING_OWNER_COUNT=1
CURRENT_OWNER=production-task-gc-20260910-r3
```

r1/r2 已设置 `superseded_by=production-task-gc-20260910-r3`；其 18 个 canonical
backup 文件未删除，仍 `backup_exists=true`、`retire_state=PROTECT`，并通过 historical
evidence 查询。r3 尚未创建 backup。

## Tests

覆盖：

- zero / one / two actionable pending owner policy；两个 actionable owner 仍 FAIL；
- 新 revision supersede 旧 revision，actionable pending 仍为 1；
- 历史 backup/evidence 保留且不再作为 current authority；
- registry restart/load 后 lifecycle 状态保持；
- exact 9-resource coverage、重复/错误 role/path、scalar backward compatibility；
- Storage registry / architecture guards。

结果：Production maintenance 定向 `36 passed`；Architecture/Storage registry
定向 `23 passed`；Ruff、compile、diff check PASS。

## Production boundary

本轮只读审计 Production registry 与既有 backup identity；未创建 r3 backup，未运行
fresh source stability、schema rebuild、fresh Preview、GC、VACUUM、replace、restore
或 GUI。上一轮 authorization 已终止，不能复用旧 preview/manifest/authorization。

当前状态：`OWNER_LIFECYCLE_FIX=PASS`，但需要在最终 clean HEAD 上重新执行 source
stability、schema、rollback backup/rehearsal、post-backup identity 和 fresh Preview；
即使这些全部通过，也只生成 `EXECUTABLE_BUT_NOT_AUTHORIZED`，不执行 Production GC。
