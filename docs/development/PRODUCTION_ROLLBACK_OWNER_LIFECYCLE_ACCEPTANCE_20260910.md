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

`D:\study\NetConsole-Workspace\diagnostic\production-task-lifecycle-final-20260910-202500\PRODUCTION_ROLLBACK_OWNER_AUDIT_POST_BACKUP_2169939d.json`

transition 结果：

```text
TOTAL_OWNER_COUNT=5
PENDING_OWNER_COUNT=2
HISTORICAL_OWNER_COUNT=2
ACTIONABLE_OWNER_COUNT=1
ACTIONABLE_PENDING_OWNER_COUNT=0
CURRENT_OWNER=production-task-gc-20260910-r3
CURRENT_OWNER_STATUS=VERIFIED
```

r1/r2 已设置 `superseded_by=production-task-gc-20260910-r3`；其 18 个 canonical
backup 文件未删除，仍 `backup_exists=true`、`retire_state=PROTECT`，并通过 historical
evidence 查询。r3 已完成 9/9 canonical backup，状态为 `VERIFIED`；旧 scalar
`PENDING_PRODUCTION_BACKUP` 条目仍保留且继续受保护，不计为当前 tasks GC actionable owner。

## Tests

覆盖：

- zero / one / two actionable pending owner policy；两个 actionable owner 仍 FAIL；
- 新 revision supersede 旧 revision，actionable pending 仍为 1；
- 历史 backup/evidence 保留且不再作为 current authority；
- registry restart/load 后 lifecycle 状态保持；
- exact 9-resource coverage、重复/错误 role/path、scalar backward compatibility；
- Storage registry / architecture guards。

结果：lifecycle/Production maintenance 定向 `59 passed`；Architecture/Storage registry
定向 `23 passed`；Ruff、compile、diff check PASS。Current HEAD Consumer Gate 绑定
`5d1d2c3817f406b93d159cd83f7b5f1f917848ae`，结果为 Renderer `181/1300`、Electron
`37/298`、Architecture `12/12`、Main Contract `12`、Python `4819 passed, 2 skipped`、
`NEW_FAILURES=0`、`RESULT: PASS`。

## Production boundary

本轮绑定的 Production DataRoot 仍为 `D:\NetConsoleData`，只处理当前 9 个
`tasks.db` scope。当前 code/registry HEAD=`2169939d35b81b7be8fb9cc879a75e909ab42f16`，
scope digest=`423c3c1ed4a48dce5db9c27a5d4939f052bc6f86b86d96e72c7d75209cdd71cf`。

已完成并留存：

- writer/scheduled writer=`0/0`，9 库 source stability=`PASS`，source SHA/size 双样本稳定；
- `LEGACY_DB_COUNT=0`，task schema compatibility=`9/9 PASS`；
- 当前 owner=`production-task-gc-20260910-r3`，rollback backup=`9/9`，总计
  `408866816` bytes，quick/FK/schema=`9/9 PASS`，registry restart persistence=`PASS`；
- offline rollback rehearsal=`9/9 PASS`：TaskRepository、recent task、当前 mapping、
  tombstone 均可读；外部 Ground/Artifact/业务库未打开；
- fresh dry-run Preview：candidate/safe/protected/unknown=`7207/6568/639/0`，
  safe logical payload=`195523259` bytes，schema=`9/9 PASS`，`read_only_preview=true`；
- 旧 r1/r2 backup 保持原状，未删除；旧 scalar pending owner 仍受保护。

证据目录：

`D:\study\NetConsole-Workspace\diagnostic\production-task-lifecycle-final-20260910-202500`

当前结果：`OWNER_LIFECYCLE_FIX=PASS`，`PRODUCTION_GC_EXECUTION_READY_FOR_AUTHORIZATION=YES`，
但 `EXECUTION_PLAN_STATUS=EXECUTABLE_BUT_NOT_AUTHORIZED`。上一轮 authorization 已终止，
不能复用旧 preview/manifest/authorization；本轮未执行 Production GC/DELETE、VACUUM、
VACUUM INTO、candidate replace、restore、schema migration 或 GUI smoke。
