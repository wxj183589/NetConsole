# NetConsole Production tasks.db Source Drift Reconciliation

日期：2026-09-10  
Agent：codex-A  
Codex-Thread：`production-task-rollback-refresh-20260910`

## 结论

本轮仅处理 Production `D:\NetConsoleData` 下 9 个 `tasks.db` 的 source drift reconciliation、rollback scope refresh、只读 rehearsal 和 fresh preview。没有执行 Production GC、DELETE、VACUUM、VACUUM INTO、candidate replace、restore 或业务数据库 mutation。

最终状态：

```text
SOURCE_DRIFT_RECONCILIATION=PASS
CURRENT_SOURCE_STABLE=YES
ROLLBACK_OWNER_STATUS=VERIFIED
ROLLBACK_SCOPE_COMPLETE=YES
ROLLBACK_SCOPE_COVERAGE=9/9
ROLLBACK_REHEARSAL=PASS
FRESH_PREVIEW=PASS
PRODUCTION_GC_EXECUTION_READY_FOR_AUTHORIZATION=YES
PRODUCTION_CUTOVER_AUTHORIZED=FALSE
PRODUCTION_GC=NOT_RUN
```

## 绑定与范围

- 当前执行证据绑定 HEAD：`d37d0ebbc1b8d7b92f61b92c2d8387f60abbb4e1`。
- Production 数据根：`D:\NetConsoleData`。
- Production `tasks.db` 数量：9。
- 当前文件总大小：`408866816` bytes。
- writer/process stop 检查：focused Production writer=`0`，scheduled writer=`0`。
- 当前来源稳定性：10 秒双样本，9/9 size、mtime、SHA 全部一致，`SOURCE_STABILITY=PASS`。
- 仅允许的 rollback 资源为当前 Production allowlist 的 9 个 `tasks.db`；protected、unknown、HistoryStore、业务数据、日志、Artifact、MESH、Online MR 正式结果、Ground 正式结果和原始文件均不在范围内。

## Source drift 审计

旧 owner 对当前来源的 exact identity 校验发现 2 个 drift：

| 局点 | 旧来源 | 当前来源 | 分类 | 判定依据 |
| --- | --- | --- | --- | --- |
| 宁波地铁10号线 | SHA `a5e85ae6071054b50c9428edb50fb58f58c23f54c2ed6476ed90f7a9da1b140e`，`67158016` bytes | SHA `9b3a18865461d820c9f96311f15930df27c5a4dc7c45a5c6e9da82709b7449f9`，`67162112` bytes | `EXPECTED_OPERATIONAL_WRITES` | schema 相同；新增 1 个 task、8 个 event、1 个 result blob、1 个 result、1 个 snapshot；无 task 删除 |
| 宁波地铁12号线 | SHA `b3e58d550a649271d2b3a20051748e104c59de01f3662d4841cc52eeee695a14`，`153550848` bytes | SHA `4ef7e9465ffb9ac92c3915c46a4ccdc0938fe78b607e13a52f6fbe04b246ae38`，`160104448` bytes | `EXPECTED_OPERATIONAL_WRITES` | schema 相同；新增 8 个 task、8219 个 event、5 个 result blob、8 个 result、8 个 snapshot；无 task 删除 |

两处均未发现 `UNEXPLAINED` 或 `MIXED` 漂移，当前来源稳定且 quick/FK 校验通过，因此：

```text
DRIFTED_DB_COUNT=2
NINGBO10_DRIFT_CLASSIFICATION=EXPECTED_OPERATIONAL_WRITES
NINGBO12_DRIFT_CLASSIFICATION=EXPECTED_OPERATIONAL_WRITES
SOURCE_DRIFT_ACCEPTED=YES
```

旧授权因 source drift 已失效，不得复用旧 preview、旧 scope 或旧授权。

## Rollback scope refresh

- 新 owner：`ProductionMaintenanceCapability`。
- 新 maintenance/revision：`production-task-gc-20260910-r2`。
- 新 backup set：`production-task-gc-20260910-r2-tasks`。
- 新 scope digest：`dd3d7c6d861563ba91f46424a43c2a1e0acc0ad440bc319480d6b25dfbef2ad5`。
- 新 rollback backup：9/9，累计 `408866816` bytes；使用 SQLite Online Backup API。
- 新备份 quick check：`9/9 PASS`。
- 新备份 foreign-key check：`9/9 PASS`。
- 新 owner verifier：`owner_status=VERIFIED`、`requested=9`、`covered=9`、`missing=0`、`scope_complete=true`。
- registry restart persistence：`PASS`。
- offline repository/tombstone/current-mapping/recent-task rehearsal：`9/9 PASS`。
- post-backup source identity match：`9/9`；post-backup 10 秒 source stability=`PASS`。
- 旧 revision：`production-task-gc-20260910` 保持存在且 VERIFIED；旧 9 份备份逐份 size/SHA 匹配，累计 `402309120` bytes，`OLD_ROLLBACK_SET_PRESERVED=YES`。
- 本轮未删除、覆盖、重命名旧 backup，也未恢复或替换任何 active Production DB。

## Fresh preview 与执行计划

本轮 fresh preview 为只读 dry-run：

```text
CANDIDATE_COUNT=7207
SAFE_TO_RETIRE_COUNT=6568
PROTECTED_COUNT=639
UNKNOWN_COUNT=0
PREVIEW_SHA256=b4c1a038a7ad35f09ef69bf9f6e1c7a4ba02616e6cfa48904de7feca1f970a6d
SAFE_LOGICAL_PAYLOAD_BYTES=195523259
SAFE_EVENT_ROWS=84457
SAFE_SNAPSHOT_ROWS=6568
SAFE_RESULT_ROWS=4158
```

相对 source drift 前的 `7207/6402/805/0`：candidate `+0`、safe `+166`、protected `-166`、unknown `+0`。protected 原因仍只作为保护条件，不进入执行候选；unknown 保持 0。

生成的执行计划状态为：

```text
EXECUTION_PLAN_STATUS=EXECUTABLE_BUT_NOT_AUTHORIZED
PRODUCTION_CUTOVER_AUTHORIZED=FALSE
PRODUCTION_BUSINESS_DB_MUTATION=NONE
PRODUCTION_GC=NOT_RUN
PRODUCTION_VACUUM=NOT_RUN
PRODUCTION_REPLACE=NOT_RUN
APPLY_MANIFEST_CREATED=FALSE
```

该计划仅绑定 fresh preview、当前 9 库 scope 和新 rollback owner；只有收到新的明确 Production GC authorization 后，才可另行重新校验 writer、HEAD、owner、backup、preview digest 并进入执行会话。

## Evidence

证据目录：

`D:\study\NetConsole-Workspace\diagnostic\production-task-rollback-refresh-20260910-190406`

主要文件：

- `SOURCE_STABILITY_CHECK.json`
- `DRIFT_DATABASE_AUDIT.json`
- `CURRENT_PRODUCTION_TASKS_DB_RESOURCE_SET_POST_REGISTRATION.json`
- `NEW_ROLLBACK_SCOPE_VERIFIED.json`
- `ROLLBACK_SCOPE_VERIFIER.json`
- `ROLLBACK_REGISTRY_RESTART_PERSISTENCE.json`
- `CURRENT_PRODUCTION_TASKS_DB_ROLLBACK_MANIFEST.json`
- `ROLLBACK_REHEARSAL.json`
- `POST_BACKUP_SOURCE_MATCH.json`
- `OLD_ROLLBACK_PRESERVATION.json`
- `TASK_RETIREMENT_PREVIEW_AFTER_DRIFT.json`
- `PRODUCTION_TASKS_DB_GC_EXECUTION_PLAN_AFTER_DRIFT.json`

## 数据影响与剩余要求

- Production active `tasks.db`：未修改。
- Production GC/DELETE：未运行。
- Production VACUUM/VACUUM INTO：未运行。
- candidate replace/restore：未运行。
- old rollback backup：保留。
- 本轮允许的变更仅为新 rollback backup 和正式 maintenance registry evidence。
- 需要用户另行发送新的明确 GC authorization；本轮及 source drift 前的旧授权均不构成当前执行授权。
