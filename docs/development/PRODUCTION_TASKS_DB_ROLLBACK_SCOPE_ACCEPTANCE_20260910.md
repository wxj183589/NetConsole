# Production tasks.db rollback scope acceptance

## 结论

本轮只补齐 `ProductionMaintenanceCapability` 对 9 个 Production `tasks.db` 的正式
rollback resource-set 能力。没有执行 Task GC、DELETE、VACUUM、Replace、cutover 或
生产恢复。

`ROLLBACK_OWNER_STATUS=VERIFIED`、`ROLLBACK_SCOPE_COMPLETE=YES`、
`ROLLBACK_REHEARSAL=PASS`，并已达到 `READY_FOR_EXPLICIT_AUTHORIZATION`；
`PRODUCTION_CUTOVER_AUTHORIZED=FALSE` 保持不变。

## ROOT_CAUSE

原模型把 owner 固定为 `(site_id, database)` scalar binding，只能识别宁波 12 号线
两个 `PENDING_PRODUCTION_BACKUP` 槽位。它没有 maintenance id、resource-set、精确
coverage 或跨 Site tasks-only identity，因此本轮 9 库查询得到 `0/9`。已有中央
database-upgrade backup store 不是 `ProductionMaintenanceCapability` 的 rollback
owner，不能冒充本边界。

## CURRENT_OWNER_MODEL / SCOPE_MODEL

保留旧 scalar owner 解析和 pending 条目；在同一个
`production_rollback_owners` registry entry 中增加 schema-compatible resource-set：

- `maintenance_id=production-task-gc-20260910`
- `maintenance_type=TASK_OPERATIONAL_GC`
- `scope_kind=resource-set`
- `resources[9]`：Site ID/display、`database_role=tasks.db`、relative/normalized path、
  source identity/SHA/revision、size、schema、quick/FK、backup identity/status

coverage 按 `(site_id, database_role, normalized_path)` 计数，要求 requested/covered
精确相等；missing 或 extra、重复、错误 role、source/backup identity 不匹配均不通过。
`ProductionMaintenanceCapability._owner()` 只有在 resource-set owner 全部 9 个资源
verified 后才把它作为任一 Site 的 rollback authority。

## CODE_CHANGE

最小修改仅位于 Production maintenance capability、其维护 CLI 和定向测试：

- 增加多资源 owner/resource model、稳定 path identity、精确 coverage 和持久 registry
  append/replace；registry writer 保留其它大型 registry 内容格式。
- 增加正式 `scope` → `register-scope` → `backup-scope` → `manifest-scope` →
  `verify-scope` 流程；backup 使用 SQLite Online Backup API。
- 保持旧 single-resource owner backward compatible；不修改 Task GC、Task Lifecycle、
  GUI、Installer。

## RESOURCE_SET / BACKUP_CREATION

- Production DataRoot：`D:\NetConsoleData`
- `PRODUCTION_DB_COUNT=9`
- source total：`402309120` bytes
- rollback set：`production-task-gc-20260910-tasks`
- backup root pattern：`sites/<site>/files/backups/production-maintenance/production-task-gc-20260910-tasks/database.sqlite`
- backup total：`402309120` bytes
- source/backup quick check：`9/9 ok`
- source/backup foreign key check：`9/9 ok`
- scope：仅 9 个 `tasks.db`，未包含 `devices.db`、HistoryStore、raw、Artifact 或整个 DataRoot

证据：

- `PRODUCTION_TASKS_DB_SCOPE_CURRENT.json`
- `PRODUCTION_TASKS_DB_ROLLBACK_MANIFEST_FINAL.json`
- `ROLLBACK_SCOPE_RESTART_PERSISTENCE.json`

## OWNER_VERIFICATION / RESTART_PERSISTENCE

正式新进程 verifier 结果：

```text
owner_status=VERIFIED
requested_count=9
covered_count=9
missing=[]
extra=[]
scope_complete=true
```

旧宁波 12 号线两个 scalar owner 仍为 `PENDING_PRODUCTION_BACKUP`、`PROTECT`，没有
被改写为 VERIFIED，也没有被新 resource-set 污染。

## ROLLBACK_REHEARSAL

不恢复 Production，只读取 9 个 backup：

- TaskRepository readable：`9/9`
- current mappings readable：`9/9`
- tombstone readable：`9/9`
- recent task readable：`9/9`
- Production restore：`NOT_RUN`

## PREVIEW / EXECUTION_READINESS

owner VERIFIED 后重新执行全站 dry-run preview：

```text
candidate=7207
safe=6568
protected=639
unknown=0
read_only_preview=true
```

最新 execution plan 为 `EXECUTABLE_BUT_NOT_AUTHORIZED`，仅剩显式 Production cutover
authorization；这不等于已授权执行。

## FINAL STATUS

```text
ROLLBACK_SCOPE_MODEL = PASS
ROLLBACK_OWNER_REGISTERED = YES
ROLLBACK_OWNER_STATUS = VERIFIED
ROLLBACK_SCOPE_COMPLETE = YES
ROLLBACK_BACKUP_SET = PASS
ROLLBACK_REHEARSAL = PASS
ROLLBACK_REGISTRY_PERSISTENCE = PASS
PRODUCTION_PREVIEW = PASS
PRODUCTION_GC_EXECUTION_READY_FOR_AUTHORIZATION = YES
PRODUCTION_GC = NOT_RUN
PRODUCTION_VACUUM = NOT_RUN
PRODUCTION_REPLACE = NOT_RUN
PRODUCTION_MUTATION = NONE
PRODUCTION_CUTOVER_AUTHORIZED = FALSE
```

`PRODUCTION_TASKS_DB_GC_EXECUTION_PLAN.json`、scope、rollback manifest 和 preview
均绑定本轮 maintenance id；后续若要执行，必须另行取得明确授权并重新验证当前
HEAD、writer quiescence、scope、manifest、preview 和全部 gates。
