# Production tasks.db Operational GC execution acceptance

## 结论

本次会话已收到用户对 `D:\NetConsoleData` 的明确 Production tasks.db
Operational GC 授权，但执行在 apply 前的 current resource identity gate 失败关闭。
没有执行 GC、DELETE、VACUUM、candidate replace、Restore 或其它 Production
业务数据 mutation。

```text
PRODUCTION_AUTHORIZATION=VERIFIED
EXECUTION_CODE_SHA=0446d0376ef866626fadc35c622b4837ac071d84
PRODUCTION_WRITERS_STOPPED=YES
ROLLBACK_OWNER=ProductionMaintenanceCapability
REGISTERED_ROLLBACK_OWNER_STATUS=VERIFIED
ROLLBACK_SCOPE_RECHECK=FAIL
ROLLBACK_SCOPE_COVERAGE=7/9
ROLLBACK_SCOPE_MISSING=2
PRODUCTION_GC=NOT_RUN
PRODUCTION_COMPACT=NOT_RUN
PRODUCTION_REPLACE=NOT_RUN
PRODUCTION_TASKS_DB_MAINTENANCE=BLOCKED_FAIL_CLOSED
```

## Authorization and current-head gate

- 用户授权范围：仅 `D:\NetConsoleData`、最新 VERIFIED rollback owner 覆盖的 9 个
  `tasks.db`，且仅处理最新 preview 的 `safe=true`。
- 当前源码：`main@0446d0376ef866626fadc35c622b4837ac071d84`。
- worktree clean，`main` 与 `github/main` 一致。
- 相关代码从 rollback scope 验收提交到当前 HEAD 无新增变化。
- focused Production writer process=`0`；Backend instance lock recheck=`ACQUIRED`
  后正常释放；未发现可继续写入 Production 的 NetConsole writer。

## Fresh scope and rollback recheck

重新发现 artifact：
`D:\study\NetConsole-Workspace\diagnostic\production-task-gc-execution-20260910-184901\EXECUTION_PRODUCTION_DB_SET.json`

- current resource count=`9`
- current source total=`408866816` bytes
- current scope digest=`dd3d7c6d861563ba91f46424a43c2a1e0acc0ad440bc319480d6b25dfbef2ad5`
- current source quick/FK=`9/9 PASS`
- formal owner verifier=`owner_status=VERIFIED`，但与 fresh current resource set 的
  exact coverage 只有 `7/9`，因此 `scope_complete=false`。

两个资源发生 source identity/size 漂移，不能使用旧 rollback copy 对其执行本轮维护：

| site | resource | registered source | current source | registered/current size |
| --- | --- | --- | --- | --- |
| 宁波地铁10号线 (`legacy-784dcd2b63e3`) | `sites/宁波地铁10号线/db/tasks.db` | `a5e85ae6071054b50c9428edb50fb58f58c23f54c2ed6476ed90f7a9da1b140e` | `9b3a18865461d820c9f96311f15930df27c5a4dc7c45a5c6e9da82709b7449f9` | `67158016 / 67162112` |
| 宁波地铁12号线 (`legacy-dfd356e96ea0`) | `sites/宁波地铁12号线/db/tasks.db` | `b3e58d550a649271d2b3a20051748e104c59de01f3662d4841cc52eeee695a14` | `4ef7e9465ffb9ac92c3915c46a4ccdc0938fe78b607e13a52f6fbe04b246ae38` | `153550848 / 160104448` |

7 个未漂移资源仍保持 rollback owner 覆盖；两份旧 rollback backup 均保留，未被修改。

## Stop boundary

由于 `RESOURCE_IDENTITY_MATCH=7/9`，按 fail-closed contract 在 rollback recheck 阶段
停止，以下步骤均未执行：

- 最新 dry-run preview 和 apply manifest
- Operational GC / task-owned row deletion
- GC 后 integrity、Task Center、Log Center、Artifact、Online MR、Ground、business smoke
- `VACUUM INTO`、candidate integrity/parity、atomic replace
- Production GUI/restart、post-GC preview、After baseline

因此本次不存在 `TASKS_DELETED`、`APPLY_ATTEMPTED`、物理释放或 compact 结果。下一次
执行必须先重新确认两个漂移数据库的合法 current source、重建并验证覆盖全部 9 库的
rollback scope/backup，再从 fresh preview 开始；不得复用本次或旧 preview/manifest。

## Data safety

- 活动 Production `tasks.db` 未修改。
- 未删除 protected、unknown、HistoryStore、业务数据、日志、Artifact、MESH、Online MR、
  Ground 或原始文件。
- 9 个既有 canonical rollback backup 保持 `RECOVERY_COPY_RETENTION=KEEP`。
