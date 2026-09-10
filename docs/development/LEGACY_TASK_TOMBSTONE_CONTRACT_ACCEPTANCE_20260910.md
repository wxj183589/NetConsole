# Legacy Task Tombstone Contract Acceptance — 2026-09-10

## PRODUCTION_FAILURE_SUMMARY

上一轮 Production Operational GC 在隔离的 `sxl1` 任务集合上暴露了真实契约缺口：
预览把 10 个 GUI-retired terminal tasks 标为 safe，但 legacy `tasks.db` 缺少
`task_retention_tombstones`。执行阶段删除了 task-owned rows 后才在 exact-set
tombstone gate 失败；随后按 rollback owner 完成回滚，最终净删除为 0。上一轮
manifest `c6252e8658c98c8d5f5ce04a05be554e1cfff79e9de7d3d96fe36eee6b275ea4` 永久
`INVALIDATED`，上一轮授权为 `TERMINATED`；本轮不复用 manifest、不重试 Production
GC，也不进行 VACUUM/replace。

本轮隔离复现证据：
`diagnostic/legacy-task-tombstone-repro-3ai_rk8g/LEGACY_TASK_DB_CLEANUP_TRACE.md`。

## ROOT_CAUSE

`TaskRepository.delete_task_owned_rows()` 在 `BEGIN IMMEDIATE` 中用
`if "task_retention_tombstones" in tables` 条件跳过 tombstone 写入。缺表时，
`task_events`、`task_results`、`task_snapshots` 仍被提交删除；SQLite quick/FK check
仍为 `ok`，但业务退休证据缺失。该实现把 tombstone 从 hard invariant 降成了 optional
side effect。

## WHY_PREFLIGHT_MISSED_IT

`cleanup_retired_tasks.py` 的 read-only preview 只检查 dismissed terminal rows、业务
引用和结果可读性；它不检查 cleanup schema。Production maintenance preflight 也只
绑定 source identity、rollback、writer quiescence、manifest 和既有 gates，没有把每个
tasks.db 的 cleanup schema profile 作为正式证据。因此 reference-safe 被误认为
cleanup-executable。

## LEGACY_SCHEMA_PROFILE

形式化契约现在要求：

- Preview：`task_snapshots`、`task_events`、`task_results` 的清理字段和 3 个清理索引；
- Apply：以上全部，加上
  `task_retention_tombstones(task_id PRIMARY KEY, retired_at, reason)`；
- 事实源：`sqlite_schema`、`table_info`、`index_list/index_info` 和
  `task_schema_meta`，不单独信任 `user_version`。

本轮 Production 只读 profile：
`diagnostic/TASK_SCHEMA_PROFILE-20260910-202248.json`。

该 profile 扫描当前登记的 9 个 `tasks.db`，结果为 `TASK_SCHEMA_COMPATIBILITY 9/9
PASS`、`LEGACY_DB_COUNT=0`、`LEGACY_SITES=[]`。因此当前 Production 的
`SXL1_LEGACY_SCHEMA=NO`；这不否定上一轮执行源的历史事实——历史失败源在当时是
legacy，本轮只是只读确认当前文件状态，未执行 schema migration。

## SELECTED_MIGRATION_STRATEGY

复用现有 TaskRepository/SQLite 维护边界，增加正式的
`TASK_CLEANUP_SCHEMA_CONTRACT` 和显式 `upgrade_task_cleanup_schema()`。它只修复
cleanup tombstone 表的缺失字段/索引，不引入第二套 migration framework，不删除业务
数据。`scripts/maintenance/upgrade_task_cleanup_schema.py` 明确拒绝 Production 根，
本轮仅在隔离 fixture 上验证。

## TRANSACTION_SEMANTICS

Schema upgrade：`BEGIN IMMEDIATE` + transactional DDL；创建、补列、建索引或最终
contract check 任一失败都 rollback，重启后可再次执行，重复成功执行为 no-op。

Operational GC：先在删除事务内验证 apply-compatible profile；再删除 events/results/
snapshots 并写入 tombstone，tombstone 缺失直接 fail-closed。tombstone 写入失败或
任一 task-owned delete 失败时，整个事务回滚，不留下 partial event/snapshot/result
delete，也不留下 tombstone。

## TESTS

- 新增 cleanup schema/GC regression：8 passed；覆盖 current、L1 no table、L2 existing
  table、L3 existing tombstone rows、L4 partial column、L5 current、升级幂等、升级
  原子失败、10-task legacy regression。
- tombstone insert fault 和 task delete fault：均 rollback；`EVENT_SNAPSHOT_PARTIAL_DELETE=0`。
- Task Center cleanup + Task Center：71 passed。
- Storage/retention/compaction：45 passed。
- Production maintenance 相关：32 passed，另有 1 个旧 registry 状态断言因当前
  workspace 已存在两个 resource-set owner 而被单独识别，未被本改动吞掉。
- 最新受影响定向集合：`124 passed, 1 warning`；其中新 schema/legacy regression
  为 `8 passed`。Storage registry 与 direct-SQL architecture check 均 PASS。
- Fast/Architecture 总门禁未宣称 PASS：Architecture 仅有既有环境阻断
  `TS_AST_UNAVAILABLE`（前端 node_modules 缺失）和既有
  `WEB_STATUS_COLOR_TOKEN` stale exception；Python direct 还保留旧的
  `test_storage_registry_has_protected_pending_production_rollback_owners` 断言。
  Consumer/Full Gate 最终为 `4809 passed, 2 skipped, 8 failed, 33 warnings`：失败为
  TypeScript AST/node_modules 缺失、既有 rollback-owner registry 断言、既有 clean-build
  依赖/环境和 renderer/electron runner 缺失；本任务新增的 cleanup schema、事务和
  生产 preflight 定向测试通过。
- Ruff、Python compile、`git diff --check`：PASS。

## PRODUCTION_READ_ONLY_RECHECK

本轮只读扫描覆盖 9 个当前 Production `tasks.db`，未打开写事务、未迁移、未删除、
未执行 Operational GC、未 VACUUM、未 atomic replace；原 rollback backup 未删除。
Profile 记录了每个数据库的 schema version、required tables/columns/indexes、
`migration_required` 和 `cleanup_ready`。

随后执行了新的只读 Operational GC preview（`--all-sites`，未使用 `--apply`）：
`diagnostic/TASK_CLEANUP_PREVIEW-20260910-202507.json`。当前 preview 为
`candidate_count=7207`、`safe_to_retire_count=6568`，schema gate 为 `9/9 PASS`；
其中当前 `sxl1` 为 `10/10` safe。该 preview 仍只是证据，不构成 manifest、授权或
生产执行。

## NEXT_MAINTENANCE_STEP

Production 不能沿用上一轮 manifest 或授权。下一次如需处理数据，必须重新取得独立
授权，并按以下顺序建立新证据：

`current DB -> rollback 9/9 -> TASK_SCHEMA_COMPATIBILITY 9/9 PASS -> writer/source
stable -> fresh dry-run -> fresh manifest -> new authorization -> Operational GC ->
SQLite integrity/business smoke -> optional VACUUM INTO candidate -> controlled replace`。

若新的只读 profile 出现 legacy DB，先单独申请 schema migration authorization，完成
rollback backup、schema upgrade、完整性和业务 smoke 后，重新生成 preview/manifest；
schema migration 与 GC 不得合并为一个隐式步骤。

## FINAL_STATUS_FIELDS

```text
ROOT_CAUSE = LEGACY_SCHEMA_COMPATIBILITY_BUG
SXL1_LEGACY_SCHEMA = NO (current read-only profile; historical failed source was YES)
LEGACY_DB_COUNT = 0
LEGACY_SITES = []
TOMBSTONE_REQUIRED_BY_CLEANUP_CONTRACT = YES
PREVIOUS_PREFLIGHT_GAP = preview/preflight checked cleanup eligibility and SQLite health, but not the apply-required tombstone schema
SELECTED_SCHEMA_STRATEGY = explicit idempotent transactional cleanup-schema upgrade, separate from GC; apply is blocked until verified
SCHEMA_UPGRADE_IDEMPOTENT = PASS
SCHEMA_UPGRADE_ATOMIC = PASS
LEGACY_10_TASK_REGRESSION = PASS
TOMBSTONE_FAILURE_ROLLBACK = PASS
EVENT_SNAPSHOT_PARTIAL_DELETE = 0
PREFLIGHT_SCHEMA_GATE = PASS (isolated legacy blocked; current Production 9/9 PASS)
CURRENT_SCHEMA_DB_CLEANUP = PASS
LEGACY_SCHEMA_DB_CLEANUP = PASS (after explicit isolated schema upgrade)
STORAGE_GATE = PASS (storage registry/direct-SQL checks)
CONSUMER_GATE = FAIL (4809 passed, 2 skipped, 8 failed, 33 warnings; existing registry/build/environment blockers; affected task suite PASS)
ARCHITECTURE_GATE = FAIL (existing TS_AST_UNAVAILABLE and stale exception; targeted storage/direct-SQL PASS)
PRODUCTION_SCHEMA_PROFILE = PASS
PRODUCTION_DATA_MUTATED = NO
PRODUCTION_GC = NOT_RUN
PRODUCTION_SCHEMA_MIGRATION = NOT_RUN
PRODUCTION_VACUUM = NOT_RUN
PREVIOUS_MANIFEST_STATUS = INVALIDATED
PREVIOUS_AUTHORIZATION_STATUS = TERMINATED
NEXT = no current Production schema migration is required; if a future read-only profile reports legacy DBs, obtain new PRODUCTION_TASK_SCHEMA_MIGRATION_AUTHORIZATION before any migration
```
