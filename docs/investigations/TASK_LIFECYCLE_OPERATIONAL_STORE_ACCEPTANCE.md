# Task Lifecycle / Operational Store Acceptance

**Date:** 2026-09-10
**Branch:** `codex-A/task-lifecycle-operational-gc`
**Base:** `github/main` at `510ea6e3a293f3ef7f6e5c58d43cd6806dda4a8b`
**Evidence:** `[CODE]` source; `[FIXTURE]` automated isolated data; `[DB-READONLY]` real production profile; `[OSS]` official references; `[NOT RUN]` not executed.

## PRODUCT_SEMANTICS

`TASK_CENTER_ROLE = CURRENT_AND_RECENT`.

Task Center contains active tasks (`PENDING`, `STARTING`, `RUNNING`,
`STOPPING`) and recent terminal tasks (`COMPLETED`, `FAILED`, `CANCELLED`)
until the user explicitly removes/cleans them. It is not a permanent task
archive. `PERMANENT_TASK_DETAIL_REQUIRED = NO`.

Long-term ownership is split as follows:

```text
Task Center  -> current/recent operational execution metadata
Log Center   -> long-term application logs
Artifact     -> exported files, reports and formal file outputs
Business DB  -> formal domain facts and imported site data
tasks.db     -> OPERATIONAL_TASK_STORE
```

No permanent Task History system, Archive Browser, second Log Store, new
retention framework, scheduler, or external task engine was added.

## ROOT_CAUSE

`ROOT_CAUSE_IDENTIFIED = YES` and `SITE_IMPORT_FALSE_TASK_NOT_FOUND = FIXED`.

The actual failure was `COMBINATION`:

1. `[CODE]` `site_storage_router._submit` stored the task under the active
   source site A, which is correct for the task's execution authority.
2. `[CODE]` `site_jobs.site_import` published the imported site B and validated
   B, but did not relocate the task snapshot from A to B.
3. `[CODE]` before this change, `JobCenterQueryService.get_task()` and
   `get_logs()` selected only the current site's `tasks.db`. After the active
   site switched to B, the valid T1 rows in A appeared absent.
4. `[CODE]` after a terminal snapshot/event, the renderer kept polling. A later
   404 then replaced valid terminal detail/log state with a false red error.

This was not an import failure, early terminal deletion, lost business data,
or changed task ID.

## CURRENT_TASK_STORAGE

`tasks.db` remains per-site and is the SQLite authority for task snapshots,
events, immutable result metadata/blobs, operational session mappings and
anti-resurrection tombstones. A small persistent
`config/task-authority-index.json` records `task_id -> site_name/task_type`
for routing after site switch/restart; it does not duplicate task history.

The operational writer and query boundaries are:

```text
TaskApplicationService -> TaskRepository -> sites/<site>/db/tasks.db
JobCenterQueryService  -> read-only tasks.db query
TaskCleanupService     -> reference checks
TaskRepository         -> one SQLite deletion transaction
```

## REMOVED_TASK_BEHAVIOR_BEFORE

The old GUI chain was:

```text
GlobalTaskCenter / TaskDetailDrawer
  -> tasks store
  -> POST /api/job-center/tasks/{id}/dismiss or /api/job-center/cleanup
  -> JobCenter router
  -> TaskApplicationService
  -> TaskCleanupService compatibility path
  -> TaskRepository.dismiss_task / cleanup_history
  -> UPDATE task_snapshots.dismissed_at
```

The effective behavior was a soft hide: the list excluded the snapshot, but
`task_events`, `task_results`, result blobs and the snapshot row remained. The
new GUI path is operational retirement: it validates terminal state and
references, deletes task-owned rows, inserts a tombstone, and reports skipped
tasks. A legacy repository soft-dismiss facade remains only for compatibility
callers and is not used by the current GUI.

## OSS_REFERENCE

`[OSS]` The comparison is in
[`TASK_LIFECYCLE_OSS_REFERENCE.md`](TASK_LIFECYCLE_OSS_REFERENCE.md). The
selected concepts are stable execution identity, terminal-state durability,
separate live/history objects, explicit cleanup, and independent logs/results.

## SELECTED_PATTERN

```text
task_id stable for operational lifetime
  + site is routing context, not identity
  + terminal state durable before site-context switch
  + terminal detail/log polling stops
  + explicit user removal -> reference-checked operational GC
  + Log Center / Artifact / Business DB remain independent
```

`TASK_ID_STABLE_WITHIN_OPERATIONAL_LIFETIME = TRUE`.

## DATA_OWNERSHIP

See [`TASK_DATA_OWNERSHIP_MATRIX.md`](TASK_DATA_OWNERSHIP_MATRIX.md). In
particular:

- task snapshots/events/results are task-operational metadata;
- `app_logger` and `SystemMaintenanceApplicationService.list_logs()` own the
  Log Center application log files;
- `WebArtifactStore` manifests/files remain intact;
- Online MR and Ground mappings block retirement while referenced;
- unknown/unreadable references are protected;
- task-result shared blobs are only orphan-collected after result-reference
  recheck.

## CODE_CHANGES

- Added atomic persistent task-authority routing index and task-site binding on
  local/external task creation.
- Made detail/log query authority task-aware across active-site changes and
  restart; ambiguous duplicate IDs are not guessed.
- Routed GUI single removal and batch cleanup through the same
  `TaskCleanupService` operational retirement logic. The API batch path covers
  indexed site authorities without introducing a cross-database transaction.
- Added terminal detail/log polling stop and terminal-404 renderer defense;
  never-seen 404 remains visible.
- Added UTF-8 byte-accurate cleanup payload metrics, FK/quick checks and stable
  deletion ordering.
- Added default-dry-run
  `scripts.maintenance.cleanup_retired_tasks`, guarded against production
  apply unless explicitly authorized.

## DB_CHANGES

The deletion transaction removes only task-owned rows in child-to-parent order:

```text
task_events -> task_results -> task_snapshots
```

It inserts `task_retention_tombstones`, removes only now-orphaned shared result
blobs, commits atomically, then runs `PRAGMA quick_check` and
`PRAGMA foreign_key_check`. No external file, app log, business DB, Ground
mapping or Online MR mapping is deleted.

## GC_SEMANTICS

- Active states are never eligible.
- Only terminal states are eligible.
- Unacknowledged failed/warning tasks remain protected.
- Active resource keys, Online MR mappings, Ground references, unreadable
  metadata and unknown result references remain protected.
- A verified Artifact manifest is preserved; it does not force duplicate task
  metadata to remain, and the file is never deleted by task GC.
- Single and batch GUI actions use the same decision and deletion service.
- There is no age-based automatic retention and no VACUUM per click.

## SITE_IMPORT_FIX

`SITE_IMPORT_RECENT_TASK = PASS`.

`[FIXTURE]` The A -> B regression creates a `site_import` task in A, persists
progress and `COMPLETED`, switches to B, then reads Task Center detail and task
logs successfully through the authority index. Restart and same-ID explicit
site cases are also covered.

`TERMINAL_TASK_DURABLE_BEFORE_SITE_CONTEXT_SWITCH = TRUE` for the task writer
path: terminal persistence completes in the execution site's database before
the UI can observe a successful switch result.

## LOG_CENTER_PRESERVATION

`LOG_CENTER_PRESERVED = PASS` for the isolated fixture. The test writes an
application log entry through `app_logger` to `PathResolver.app_log_path`,
retires the task, then reads it using the same Log Center reader. The task
event tail is operational and is intentionally removed with the retired task;
it is not the Log Center's canonical long-term store.

## ARTIFACT_PRESERVATION

`ARTIFACT_PRESERVED = PASS` for the isolated fixture. A manifest-linked task
is retired while its report file remains byte-for-byte present. Unreadable or
unknown manifest scope is protected. No Artifact deletion code was added.

## BUSINESS_DATA_PRESERVATION

`BUSINESS_DATA_PRESERVED = PASS` at the ownership/fixture boundary: task GC
only opens the task repository plus read-only reference stores and does not
delete domain site databases, imported site directories or formal business
outputs. Real GUI/site-import/device acceptance remains separate.

## SPACE_BEFORE_AFTER

`[DB-READONLY]` The aggregate profile covers nine production site
`tasks.db` files on 2026-09-10:

| metric | value |
| --- | ---: |
| production file bytes before | 402,067,456 |
| sum page_count | 98,161 |
| sum freelist_count | 160 |
| free-page bytes | 655,360 |
| production after | NOT RUN |
| reclaimed bytes | NOT RUN |

`dbstat` was attempted through the host Python SQLite build but is unavailable;
the table allocation values are therefore reproducible logical estimates,
normalized to each file size. See
[`TASKS_DB_TABLE_SPACE.json`](TASKS_DB_TABLE_SPACE.json).

The major estimated allocations are:

| table | rows | table bytes | index bytes | percentage |
| --- | ---: | ---: | ---: | ---: |
| `task_events` | 422,934 | 271,524,525 | 47,769,118 | 79.4130% |
| `task_snapshots` | 7,487 | 69,348,689 | 3,033,374 | 18.0025% |
| `task_result_blobs` | 3,539 | 6,783,011 | 277,001 | 1.7559% |
| `task_results` | 4,562 | 1,469,084 | 1,853,238 | 0.8263% |

The dominant growth is task event payload plus terminal snapshots; result
metadata/blob rows are materially smaller in physical allocation, even where
their logical uncompressed result bytes are large.

## REMOVED_TASK_RESIDUAL_PROFILE

`[DB-READONLY]` The legacy GUI soft-hidden residual profile found:

| metric | value |
| --- | ---: |
| removed terminal tasks | 7,207 |
| event rows | 407,073 |
| snapshot rows | 7,207 |
| result rows | 4,455 |
| logical residual payload bytes | 411,153,338 |
| safe candidates after current checks | 6,568 |
| protected candidates | 639 |

The 411,153,338 bytes are the exact logical payload metric (UTF-8 event and
snapshot fields plus immutable `task_results.byte_size`), not a claim that a
DELETE immediately shrinks the SQLite file by that amount. Shared compressed
blob references include 37 still-shared references and remain protected until
the repository's orphan check proves they are unreferenced.

Details are in [`REMOVED_TASK_RESIDUAL_PROFILE.json`](REMOVED_TASK_RESIDUAL_PROFILE.json).

## TESTS

Executed with explicit worktree `PYTHONPATH`:

- `[FIXTURE]` Python relevant lifecycle/cleanup/authority/architecture set: **233 passed**.
- `[FIXTURE]` Python focused cleanup/site-storage subset: **26 passed**.
- `[FIXTURE]` Renderer task-center store/components: **36 passed** (`tasks.test.ts`: 16).
- `[FIXTURE]` covers site-import A -> B, restart, task/event/snapshot GC,
  running-task protection, active Ground reference, Artifact preservation,
  Log Center preservation, tombstone anti-resurrection and global batch GC.
- `[FIXTURE]` renderer covers terminal snapshot polling stop, terminal log
  polling stop, late 404 defense and never-existing 404.
- `[NOT RUN]` full Python/renderer integration gates after final mainline merge;
  required by the final integration owner.
- `[NOT RUN]` real GUI installation, real device, production task deletion or
  production VACUUM.

## PRODUCTION_DATA_STATUS

```text
PRODUCTION_DATA_TOUCHED = NO (read-only profile and preview only)
PRODUCTION_TASKS_DB_GC = READY_NOT_RUN
TASKS_DB_AFTER = NOT RUN
TASKS_DB_RECLAIMED = NOT RUN
```

The one-time command is default dry-run:

```powershell
$env:PYTHONPATH = "D:\study\NetConsole-Workspace\worktrees\task-lifecycle-operational-gc\src"
& "D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.cleanup_retired_tasks `
  --data-root "D:\NetConsoleData" --all-sites `
  --output "D:\study\NetConsole-Workspace\diagnostic\task-lifecycle-operational-gc\production-space\TASK_RETIREMENT_PREVIEW.json"
```

No `--apply`, production replacement, or `VACUUM INTO` was run.

## OPEN_ITEMS

- Final integration must refresh `github/main`, reconcile any parallel changes,
  and rerun Change Impact plus the required full gates on the final HEAD.
- Production one-time GC remains an owner-authorized maintenance action. Review
  the preview, stop writers, take the required recovery copy, revalidate each
  candidate and run controlled apply only under the production maintenance
  authorization process.
- Because the current preview intentionally reports protected candidates, no
  production physical after-size or reclaimed-byte claim is made here.
- Legacy tasks created before the authority index was introduced are covered by
  explicit-site/maintenance paths; a future index backfill, if needed, must be
  separately scoped and read-only first. No broad startup scan was added.

## FINAL_STATUS

```text
TASK_CENTER_ROLE = CURRENT_AND_RECENT
PERMANENT_TASK_DETAIL_REQUIRED = NO
ROOT_CAUSE_IDENTIFIED = YES
SITE_IMPORT_FALSE_TASK_NOT_FOUND = FIXED
SITE_IMPORT_RECENT_TASK = PASS
TERMINAL_STATUS_POLLING = STOPPED
TERMINAL_LOG_POLLING = STOPPED
REAL_UNKNOWN_TASK_404 = PASS
MANUAL_TASK_CLEANUP_GC = PASS
RUNNING_TASK_PROTECTION = PASS
REMOVED_TASK_RESIDUAL_PROFILE = COMPLETE
LOG_CENTER_PRESERVED = PASS
ARTIFACT_PRESERVED = PASS
BUSINESS_DATA_PRESERVED = PASS
ONLINE_MR_MAPPING = PASS (protected when mapped; production apply not run)
GROUND_MAPPING = PASS (protected when referenced; production apply not run)
RECOVERY = PASS (tombstone/late-event and existing recovery fixtures)
TASKS_DB_ROLE = OPERATIONAL_STORE
PERMANENT_TASK_HISTORY_SYSTEM = NO
NEW_RETENTION_FRAMEWORK = NO
NEW_TASK_ENGINE = NO
PRODUCTION_DATA_TOUCHED = NO
TASKS_DB_BEFORE = 402067456 aggregate production file bytes
TASKS_DB_AFTER = NOT RUN
TASKS_DB_RECLAIMED = NOT RUN
TASK_LIFECYCLE_INTEGRATION_READY = YES (pending final-mainline gates)
```
