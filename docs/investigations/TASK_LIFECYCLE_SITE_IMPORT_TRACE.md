# `site_import` Task Lifecycle Trace

**Date:** 2026-09-10
**Scope:** `site_import` task identity, per-site `tasks.db` authority, active-site switch, Task Center detail/log reads.
**Evidence labels:** `[CODE]` source inspection; `[FIXTURE]` automated regression; `[DB-READONLY]` production read-only profile; `[NOT RUN]` intentionally not performed.

## Finding

`site_import` itself completed successfully. The false `任务不存在` was a
combined authority/race defect:

```text
ROOT_CAUSE = COMBINATION
  TASK_REPOSITORY_AUTHORITY_CHANGED
  + CURRENT_SITE_SCOPED_QUERY
  + RENDERER_TERMINAL_POLLING_RACE
```

Before this change, the task was persisted in the source/current site A
`tasks.db`. The import handler published the new site B and the UI switched
the active-site context to B. `JobCenterQueryService.get_task()` and
`get_logs()` then opened only B's `tasks.db`; after the task's in-memory site
map was gone (or after restart), the still-valid A task looked like a 404.
The renderer continued detail and log polling after a terminal snapshot/event,
so a later 404 overwrote a valid `COMPLETED` view with a false error.

## Trace

The table uses `T1` for the task and A/B for the source/target site. Paths are
shown as the production-shaped `DataRoot` pattern so no production task ID is
copied into a durable document.

| stage | task_id | task_state | active_site | owner | repository | repository_path | DataRoot | query_authority | log_authority | result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CREATE | T1 | CREATED/PENDING | A | `site-storage` | `TaskApplicationService.prepare` -> `TaskRepository` | `DataRoot/sites/A/db/tasks.db` | `DataRoot` | task site A is bound in the authority index | task event stream in A | task row created before worker launch |
| PENDING | T1 | PENDING | A | `site-storage` | `TaskRepository` | A `tasks.db` | same | A | A `task_events` | durable snapshot/event |
| STARTING | T1 | STARTING | A | `site-storage` | `TaskRuntime` + repository callback | A `tasks.db` | same | A | A `task_events` | worker has not changed identity |
| RUNNING | T1 | RUNNING | A | `site-storage` | `TaskRuntime` + `TaskRepository.record` | A `tasks.db` | same | A | A `task_events` | progress is operational telemetry |
| IMPORT_DONE | T1 | RUNNING | A (target B is published) | `site-storage` | `site_jobs.site_import` -> `SitePackageService` / `SiteApplicationService` | task remains A; business files/DB/Registry for B are published by site service | same | task identity remains A | A | import result says B is switchable |
| TERMINAL_PERSIST | T1 | COMPLETED | A | `site-storage` | `TaskApplicationService.complete` -> `TaskRepository` | A `tasks.db` | same | A | A `task_events` | terminal snapshot and `finished` event durable |
| PUBLISH | T1 | COMPLETED | A | `TaskEventHub` / WebSocket | `TaskRepository` remains A | A `tasks.db` | same | A authority index + A DB | A events plus independent app log | live UI receives completion |
| ACTIVE_SITE_SWITCH | T1 | COMPLETED | B | site registry / UI switch | no task relocation | B becomes current query context; T1 is still in A DB | same | **old code: B only; fixed: indexed A** | **old code: B only; fixed: indexed A** | context changes, task identity must not |
| DETAIL_REFRESH | T1 | COMPLETED | B | Renderer Task Center | `GET /api/job-center/tasks/{id}` -> `JobCenterQueryService.get_task` | **old: B; fixed: resolve A then read A** | same | fixed `_db_path(site_id, task_id)` | n/a | fixed detail returns `COMPLETED` |
| EVENT_REFRESH | T1 | COMPLETED | B | Renderer Task Center | same task-detail authority; progress rows from A | **old: B; fixed: A** | same | A | A `task_events` | event tail remains readable |
| LOG_REFRESH | T1 | COMPLETED | B | Renderer Task Center | `GET /api/job-center/tasks/{id}/logs` -> `get_logs` | **old: B; fixed: A** | same | A | task tail A; Log Center is independent app log | fixed terminal log stops further tail polling |

## Code path evidence

1. `[CODE]` `src/netconsole/backend/api/site_storage_router.py::_submit` assigns
   the current site directory to `job_params["site_name"]` for `site_import`.
2. `[CODE]` `TaskApplicationService.prepare` writes the initial snapshot to
   `paths.site_tasks_db_path(site_name)` and now binds `task_id -> site_name`
   in the small persistent `config/task-authority-index.json`.
3. `[CODE]` `src/netconsole/services/job_center/handlers/site_jobs.py::site_import`
   calls `SitePackageService.import_site`; its result validates the target
   Registry/database but does not move the task snapshot to the target site.
4. `[CODE]` `JobCenterQueryService` now checks the requested site's database,
   then resolves the task's recorded site from the authority index for detail
   and log reads. Ambiguous duplicate IDs are not guessed.
5. `[CODE]` the renderer stops detail polling after a complete terminal
   snapshot and stops log polling after a `finished`, `error`, `cancelled`, or
   terminal state event. A 404 after a valid terminal snapshot is ignored for
   that selected view; a never-seen task still displays 404.

## Invariant

```text
TASK_ID_STABLE_WITHIN_OPERATIONAL_LIFETIME = TRUE
CURRENT_ACTIVE_SITE != TASK_IDENTITY
CURRENT_ACTIVE_SITE != TASK_EXISTENCE
TERMINAL_TASK_DURABLE_BEFORE_SITE_CONTEXT_SWITCH = TRUE
```

This does not create a permanent Task Detail archive. Once the user retires a
terminal task, its task-owned operational rows and authority-index entry are
removed; `GET task_id -> 404` is then the intended result.

## Regression evidence

- `[FIXTURE]` `tests/test_task_center_multisite_routing.py` covers local and
  external tasks, restart, explicit same-ID site disambiguation, and the
  `site_import` A -> B case with detail and event/log reads.
- `[FIXTURE]` `apps/desktop_renderer/src/stores/tasks.test.ts` covers terminal
  detail polling, terminal log polling, late terminal 404 defense, and a
  never-existing task 404.
- `[NOT RUN]` real GUI/device installation acceptance; this change does not
  claim that boundary.
