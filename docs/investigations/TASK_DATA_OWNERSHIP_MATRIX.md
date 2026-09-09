# Task Data Ownership Matrix

**Scope:** current/recent Task Center and explicit operational retirement.
**Principle:** task metadata may be garbage-collected after user removal;
canonical logs, files, business facts and active recovery mappings are not
owned by Task Center GC.

| data_type | runtime_owner | long_term_owner | canonical_authority | task_cleanup_action | must_preserve | reason |
| --- | --- | --- | --- | --- | --- | --- |
| task row / current snapshot | `TaskApplicationService` + `TaskRepository` | none; current/recent Task Center only | `sites/<site>/db/tasks.db.task_snapshots` | delete after terminal/reference checks and user removal | active rows; unremoved terminal rows | operational identity and current state |
| task state transition | `TaskRepository` / Worker protocol | Log Center only if separately emitted as app log | `task_events` for task tail | delete with retired task's owned rows | active/recovery events | no permanent Task Detail requirement |
| progress event / payload | Worker + `TaskRepository` | none by Task Center | `task_events` | delete with retired task; never sample active writes | active task progress | temporary runtime telemetry |
| task log tail | Worker/task owner + `JobCenterQueryService` | `SystemMaintenanceApplicationService` / `app_logger` for long-term application logs | `task_events` only for operational tail; `runtime/logs/app*.log` for Log Center | remove task tail with task metadata; do not clear app log | Log Center files | task tail is not the long-term Log Center authority |
| result summary | task owner + `TaskRepository` | business owner as applicable | bounded snapshot summary / `task_results` authority | delete when no protected reference remains | summary needed by unremoved task | small operational projection, not archive |
| result payload | task owner | Artifact/File Store or business owner | immutable `task_results` + shared `task_result_blobs` when used | delete task-owned result metadata; orphan blob rows only after reference recheck | shared blobs and external canonical result | task result metadata is not the formal business fact |
| Artifact / export / report | producing service + `WebArtifactStore` | Artifact/File Store | manifest + file content/hash | never delete from Task Center GC | files and manifests | `TASK_RETIREMENT != DELETE_TASK_OUTPUT` |
| business data | domain service | domain database | domain SQLite/business authority | no action | imported site, devices, parsed data, formal result | task only records execution metadata |
| recovery | task runtime / domain recovery service | domain recovery state | registered recovery journal/mapping | block if still referenced or unreadable | active recovery state | deleting a recovery dependency can cause unsafe restart behavior |
| Online MR mapping | Online MR service | Online MR operational store | `online_mr_task_sessions` | block while `controller_task_id` is mapped | current mapping | active session identity is not ordinary history |
| Ground mapping | Ground Unattended service | Ground operational store | Ground repository/index | block while task is referenced | current run/session mapping | active run/recovery dependency |
| authority routing index | Task Center application layer | none; rebuildable operational index | `config/task-authority-index.json` | remove entry after task rows are deleted; ambiguous IDs are never guessed | entries for active/unremoved tasks | routes a task ID to its per-site tasks.db after site switch/restart |
| retention tombstone | `TaskRepository` | none; anti-resurrection guard | `task_retention_tombstones` | insert atomically with deletion | tombstone for retired ID | prevents late worker events from recreating a retired task |

## Log Center verification

`SystemMaintenanceApplicationService.list_logs()` reads `PathResolver.app_log_path`
through `app_logger.get_logs()`. This is independent from
`JobCenterQueryService.get_logs()`, which is the bounded task-event tail. The
cleanup service therefore removes task-owned event rows without clearing
application log files. A fixture regression writes an application log entry,
retires the task, and reads that entry back through the Log Center reader.

## Deletion boundary

The only SQLite rows deleted by the current operational GC are the selected
task's `task_events`, `task_results`, and `task_snapshots`, in child-to-parent
order, in one repository transaction. Shared `task_result_blobs` are removed
only when no remaining `task_results` references them. `quick_check` and
`foreign_key_check` run after commit. Unknown, unreadable, active, mapped, or
unacknowledged protected cases are skipped and reported.

No permanent `TaskHistoryStore`, Task Archive browser, new Log Store, new
Artifact Store, automatic retention framework, scheduler, or external task
engine was added.
