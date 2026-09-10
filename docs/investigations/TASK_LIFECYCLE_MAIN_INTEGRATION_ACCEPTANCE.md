# Task Lifecycle 主线集成验收

**日期：** 2026-09-10  
**范围：** 将 `codex-A/task-lifecycle-operational-gc` 集成到最新 `main`，并在最终集成树复验 Task Lifecycle consumer gates。  
**边界：** 本阶段不执行 Production tasks.db GC、VACUUM、candidate replace、版本步进、tag 移动、安装包重打或真实设备验收。

## INTEGRATION

```text
BASE_SHA = 510ea6e3a293f3ef7f6e5c58d43cd6806dda4a8b
SPECIAL_BRANCH = codex-A/task-lifecycle-operational-gc
SPECIAL_BRANCH_SHA = a41ac5a8b2809d0ba224e0c6f12b927532a9e80a
FUNCTIONAL_FINAL_MAIN_SHA = a41ac5a8b2809d0ba224e0c6f12b927532a9e80a
MERGE_STRATEGY = git merge --ff-only
MERGE_CONFLICT = NO
TASK_BRANCH_INTEGRATION = PASS
CODE_INTEGRATION_READY = YES
```

专项提交是 `BASE_SHA` 的直接子提交。`merge-tree` 无冲突，快进时没有接受
ours/theirs、没有覆盖最新主线，也没有把当前独立的 Installer 分支带入。集成前
保留并只读核对的并行状态：`codex-A/installer-task-lifecycle-fix` 工作树干净，未
参与本次 main 集成。

## ROOT_CAUSE_AND_FUNCTIONAL_FIX

`site_import` 的“任务不存在”是三个条件叠加的生命周期缺陷：

1. 任务在源局点 A 的 `tasks.db` 持久化；导入成功后 active site 切换到 B，但任务
   没有迁移，任务 identity 仍属于 A。
2. 旧 Query/Application Service 在当前局点 B 查询详情、事件和日志，重启后又
   丢失了只存在内存中的 site map，于是把 A 中仍有效的任务误判为 404。
3. Renderer 在收到 terminal snapshot/event 后仍继续 detail/log polling，后续瞬时
   404 覆盖了已经确认的终态。

修复后的契约为：任务 identity 与 active site 解耦；终态快照/终态日志到达后停止
对应 polling；已确认终态遇到瞬时 404 保留终态 UI；从未取得有效快照的未知 task
仍返回 404。

## TASK_AUTHORITY_FIX

`config/task-authority-index.json` 是小型、原子写入的路由索引，不是第二份任务历史：

- `TaskApplicationService.prepare/create_external_task` 在任务落入某局点的
  `tasks.db` 后绑定 `task_id -> [{site_name, task_type}]`。
- `TaskAuthorityIndex.resolve()` 只有在 task id 唯一对应一个局点时才隐式路由；
  重复 task id 不猜测，必须使用显式 site。
- detail、event/log tail、列表/summary 和 acknowledge/dismiss 使用记录的原始
  authority；active-site switch 或重启不要求扫描所有 Site DB。
- Operational GC 在 task-owned rows 成功删除后移除对应索引项；tombstone 防止
  迟到事件重新创建已退休 task。

`site_import A -> B` 自动契约在最终集成树通过：T1 经 `PENDING -> STARTING ->
RUNNING -> COMPLETED`，active site 切到 B 后仍可读 COMPLETED detail 和 finished
log，无 `FALSE_TASK_NOT_FOUND`。

## RENDERER_TERMINAL_AND_404

```text
TERMINAL_STATUS_POLLING = STOPPED
TERMINAL_LOG_POLLING = STOPPED
TERMINAL_TRANSIENT_404 = PRESERVED_CONFIRMED_TERMINAL
REAL_UNKNOWN_TASK_404 = PASS
```

覆盖 `COMPLETED / FAILED / CANCELLED`；terminal snapshot 停止 detail polling，
finished/error/cancelled 或 terminal state log 停止 log tail polling。已确认终态
之后的 404 不清空 UI；从未取得快照的 task 仍向用户显示“任务不存在”。

## OPERATIONAL_GC

当前 GUI 单条“从列表移除”和批量清理共用
`TaskCleanupService -> TaskRepository`：

```text
task_events -> task_results -> task_snapshots
```

在单个 SQLite 事务内再次验证终态后，仅删除选中 task-owned rows；共享
`task_result_blobs` 只有在引用复核确认无剩余引用时才删除。提交后执行
`PRAGMA quick_check` 和 `PRAGMA foreign_key_check`。写入 UI/API 事件不重新进入
Worker 执行事件流。

```text
MANUAL_TASK_OPERATIONAL_GC = PASS (isolated fixtures)
RUNNING_TASK_PROTECTION = PASS
TOMBSTONE_LIGHTWEIGHT = PASS
```

### Tombstone audit

当前 schema 为：

```sql
CREATE TABLE task_retention_tombstones (
    task_id TEXT PRIMARY KEY,
    retired_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
```

它只保留 task identity、退休时间和原因；没有原 snapshot、result、event 或大
JSON 字段。生产库本阶段没有执行 apply，因此没有生产 tombstone 新增行、物理
行大小或物理缩容数据可报告；fixture 验证的是三列轻量 payload 和反复写入不复活。

## PROTECTED_DATA

```text
RUNNING / PENDING / STARTING / STOPPING = protected
UNCONFIRMED_ALERT = protected
ONLINE_MR_REFERENCE = protected
GROUND_REFERENCE = protected
ARTIFACT_REFERENCE = preserved/protected according to reference readability
UNKNOWN_REFERENCE = fail-closed protected when present
LOG_CENTER = preserved
BUSINESS_DATA = preserved
```

本专项不删除长期 Log Center 文件、Artifact/导出文件、raw/采集文件、业务 DB、
Ground 当前映射、Online MR 当前 session 或 recovery 依赖。不可读/未知的
metadata、Artifact scope 和 durable result reference 不会被当作安全候选。

## AUTOMATED_GATES

以下均在最终集成树 `a41ac5a8` 上执行，不沿用专项 worktree 的旧计数：

| Gate | Result |
| --- | --- |
| Change Impact | `L4`; required consumers recorded |
| Task/Storage consumer pytest | `233 passed, 1 warning` |
| Full Python `local_gate --mode full` | `4800 passed, 2 skipped, 33 warnings` |
| Renderer full | `181 files / 1300 tests passed` |
| Renderer typecheck/build | `PASS` |
| Electron full | `37 files / 298 tests passed` |
| Electron typecheck/Main+Preload build | `PASS` |
| Architecture | `12/12 PASS` |
| Main contract smoke | `12 passed, 3 warnings` |
| Storage registry | `PASS` |
| Docs/path guards | `22 passed` |
| Ruff | `PASS` |
| compileall/diff check | `PASS` |

Renderer 测试中仍会打印对 `127.0.0.1:3000` 的连接拒绝诊断，但最终测试计数和
退出码均通过；它不是本轮失败。测试使用仓库规定的隔离 test-data 根，未使用
Production 或 Development Real Data 做破坏性验证。

## REAL_GUI_GATE

```text
REAL_GUI_STARTUP = PASS (process/readiness evidence only)
REAL_GUI_SITE_IMPORT = PENDING
REAL_GUI_MANUAL_REMOVE = PENDING
REAL_GUI_LOG_PRESERVATION = PENDING
REAL_GUI_ARTIFACT_PRESERVATION = PENDING
REAL_GUI_RESTART = PENDING
REAL_GUI_GATE = PENDING
```

已从最终集成树启动正常持久开发 Electron GUI，显式使用 Development Real Data，
Vite 在独立端口就绪，Electron 进程来自集成 worktree，随后已正常关闭且无残留
进程。当前 Codex 会话没有桌面点击/截图控制入口，因此没有伪造以下人工步骤：

1. site_import 成功并自动切换 A -> B；
2. Task Center 显示 COMPLETED/100%，Detail 和 Log 可读；
3. 安全测试任务“从列表移除”后刷新/重启不复现，Log Center/Artifact 仍在；
4. 退出并完全重启后的 Task Center 恢复检查。

## PRODUCTION_PROFILE

本阶段只做了 Production read-only preview：

```text
TASKS_DB_FILES = 9
TASKS_DB_BYTES = 402067456
REMOVED_TERMINAL_CANDIDATES = 7207
CURRENT_SAFE_CANDIDATES = 6402
CURRENT_PROTECTED_TASKS = 805
UNKNOWN_REFERENCE = 0 (本次 preview 未发现；代码对未知/不可读引用 fail-closed)
PRODUCTION_GC = NOT RUN
PRODUCTION_VACUUM = NOT RUN
PRODUCTION_REPLACE = NOT RUN
```

当前 preview 的 reason hit 不是互斥分类；同一 task 可能命中多个原因：

| reason | task count |
| --- | ---: |
| `RESOURCE_REFERENCE` | 612 |
| `ARTIFACT_MANIFEST_REFERENCE` | 162 |
| `DURABLE_RESULT_REFERENCE` | 189 |
| `ONLINE_MR_TASK` | 112 |
| `ONLINE_MR_MAPPING` | 9 |
| `RESULT_ARTIFACT_REFERENCE` | 8 |

专项早先的只读快照为 `6568 safe / 639 protected`；本次用相同 `a41ac5a8` 在主线
集成 worktree 和专项 worktree 各重跑一次，均为 `6402 safe / 805 protected`，
候选 task id 数量保持 7207。差异来自当前真实引用/文件状态重新评估（169 个由
safe 变为保护，3 个旧未确认告警解除），不是快进集成修改了 Production；未执行
任何 Production 写操作。下一阶段仍需独立 owner 授权、停写、恢复副本和 preview
digest 复核后才可维护生产库。

## FINAL_STATUS

```text
TASK_LIFECYCLE = PASS (automated/integrated)
SITE_IMPORT_FALSE_NOT_FOUND = FIXED
TASK_AUTHORITY = PASS
TERMINAL_STATUS_POLLING = STOPPED
TERMINAL_LOG_POLLING = STOPPED
REAL_UNKNOWN_TASK_404 = PASS
MANUAL_TASK_OPERATIONAL_GC = PASS (isolated fixtures)
TOMBSTONE_LIGHTWEIGHT = PASS
RUNNING_TASK_PROTECTION = PASS
ONLINE_MR_PROTECTION = PASS
GROUND_PROTECTION = PASS
ARTIFACT_PROTECTION = PASS
LOG_CENTER_PROTECTION = PASS
BUSINESS_DATA_PROTECTION = PASS
FULL_PYTHON_GATE = PASS
RENDERER_GATE = PASS
ELECTRON_GATE = PASS
ARCHITECTURE_GATE = PASS
STORAGE_GATE = PASS
REAL_GUI_SITE_IMPORT = PENDING
REAL_GUI_MANUAL_REMOVE = PENDING
REAL_GUI_LOG_PRESERVATION = PENDING
REAL_GUI_RESTART = PENDING
PRODUCTION_TASKS_DB_GC = NOT_RUN
PRODUCTION_TASKS_DB_COMPACT = NOT_RUN
PRODUCTION_GC_READY = NO (real GUI gate pending)
NEXT_PRODUCTION_MAINTENANCE_READY = NO (independent authorization required)
VERSION_BUMP = NO
V1_5_6_TAG_MOVED = NO
```

## OPEN_ITEMS

- 由具备桌面点击/截图能力的受控 Windows 会话完成并记录上述真实 GUI 五项。
- Production tasks.db 维护另开独立会话执行 preview -> backup/recovery copy -> apply
  -> verify -> candidate compact/replace；本验收不得把代码集成或自动化 PASS 当作
  生产 GC 授权。
