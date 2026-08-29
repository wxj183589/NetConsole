# Task Storage Governance

## Current Result

The original Phase 1 profiling and write-amplification work is complete. The
current DEV-only integration also completes a bounded terminal-result
authority migration and candidate compaction contract. It does not migrate
Production, change the user-visible retention period, split `tasks.db`, or
claim that all task history has moved to `TaskHistoryStore`.

The production snapshot assessed on 2026-08-15 is 419,778,560 bytes with
102,485 4-KiB pages, `freelist_count=0` and a zero-byte WAL. Its size is live
logical content rather than deleted-page or WAL bloat. `task_events` is
dominated by event payloads, `task_snapshots` by terminal `result_json`, most
large terminal results occur in both the current snapshot and latest
`finished` event, and high-frequency producers append consecutive identical
progress events.

The shared compressed `task_result_blobs` row is now the canonical body for new
terminal results. `task_snapshots` and terminal events retain only the result
reference and bounded summary; pre-existing full-only or dual-write
`task_results.canonical_json` rows remain readable through compatibility
read-through. New runtime writes do not populate that retired full-body
projection, so a later compacted database cannot reinflate duplicate payloads.
Snapshot/event replay, WebSocket recovery, Online MR reconciliation and Site
Package merge continue to validate the same immutable result identity.

The explicit `TaskCleanupService` preview/cleanup path can remove only
task-owned rows after reference checks and a terminal-state recheck. It never
deletes Ground, Online MR, history, raw evidence or external Artifact files.
Soft-dismiss remains reversible UI state and is not physical deletion.

## Read-only Profiler

`scripts/maintenance/profile_tasks_db.py` supports two modes:

- LIGHT is the default and reads file/page/sidecar/schema metadata only;
- DEEP is restricted to a regular isolated snapshot under `D:\study`, requires
  an empty WAL, opens SQLite with `mode=ro&immutable=1`, and performs exact
  table/field/event analysis.

DEEP reports top tables/indexes, status/task type/time distribution, payload
percentiles, semantically duplicated terminal results, consecutive identical
progress/log events, orphan relations and 7/30-day logical growth projections.
It never includes raw payloads, task IDs or sensitive samples.

Python SQLite on the assessed host does not provide `dbstat`. The profiler
therefore marks allocation values as estimated and normalizes exact logical
field/index-key weights to live database bytes. It does not present those
values as exact page attribution. If `dbstat` is available on another host, it
uses actual page allocation automatically.

```powershell
$env:PYTHONPATH = "D:\study\worktrees\NetConsole\tasks-db-governance\src;D:\study\worktrees\NetConsole\tasks-db-governance"
& "D:\study\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.profile_tasks_db `
  --data-root "D:\NetConsoleData" --site-id "<site-id>"

& "D:\study\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.profile_tasks_db `
  --data-root "D:\NetConsoleData" --site-id "<site-id>" --deep `
  --database "D:\study\test-data\NetConsole\tasks-db-governance\<run-id>\tasks.db" `
  --output-dir "D:\study\diagnostic\NetConsole\tasks-db-governance\<run-id>"
```

## Safe Write Fix

`TaskRepository.record()` now checks `event_id` inside `BEGIN IMMEDIATE` before
updating the snapshot. A retried event ID leaves both snapshot and event
history unchanged and returns `False`.

For `progress` only, the repository compares the immediately preceding task
event. When that event is also progress, the entire payload is exactly equal,
and less than 30 seconds have elapsed, no database write is performed. The
application guard still returns success, so the current event continues to be
broadcast to live UI subscribers. A changed field, an intervening event, an
invalid/non-monotonic timestamp, or the 30-second heartbeat writes the snapshot
and event normally.

State, finished, error, cancelled, log, notification and Artifact events are
never sampled. Current progress remains accurate because only semantically
identical payloads are skipped; the next changed progress is durable.

## Benchmark

`scripts/maintenance/benchmark_tasks_db_governance.py` writes only isolated
databases under `D:\study`. It covers 100/1,000/10,000 terminal tasks, one
3,000-event high-frequency progress stream, a 30-second sampled comparison and
a large terminal result. It reports DB/WAL bytes, event rows, events/task,
throughput and commit latency percentiles.

## Completed In This Integration

- DEV candidate migration and `VACUUM INTO` compaction for shared result blobs,
  with hash/byte/parity/quick-check verification and atomic replacement.
- Exact duplicate result-body retirement without deleting task, event or
  snapshot rows; old result rows remain readable.
- Task Center list/detail/restart recovery and site-sync compatibility tests for
  blob-first result authority.
- Explicit cleanup preview and repository-owned transactional deletion of
  task-owned rows, with tombstones preventing old-event reinflation.

## Deferred Work

- Generic retention policy and arbitrary task deletion remain `NOT_STARTED`;
  `TASK_HISTORY_SCOPE_LIMIT` is not a user-facing deletion authorization.
- Broad `task_events`/`task_snapshots` retention, event archive/sharding,
  `TaskHistoryStore` cutover and database splitting remain deferred.
- Artifact filesystem truth remains owned by
  `ArtifactReconciliationService`; cleanup protects references but never
  deletes external files or manifests.
- Production migration and generic physical cleanup remain disabled. The
  production-safe ref-only closure tool is an explicit, target-scoped,
  digest-bound maintenance operation. Generate a preview with
  `scripts/maintenance/close_task_result_ref_only.py preview`, review every
  authority/hash/count check, and apply only with an external SQLite backup,
  `PRODUCTION_MAINTENANCE_AUTHORIZED`, and the exact plan digest. The operation
  updates only `task_results.canonical_json`; it does not delete tasks, events,
  snapshots, result rows, or blobs. It does not run `VACUUM`; physical
  compaction is a separate target gate.
- When a target `tasks.db` has at least 16 MiB or 5% freelist after ref-only,
  `scripts/maintenance/compact_task_result_production.py` may build a
  `VACUUM INTO` candidate under production staging. It requires an external
  recovery copy and validates full user-table parity, result/Blob authority,
  and task/Online-MR/Ground/Artifact orphan checks before atomic replacement.
  A post-replace mismatch restores that external copy; the existing rollback
  owner is not modified.
- A target database change, WAL, authority, hash, count, consumer, or restart
  failure aborts only the affected target phase. Unrelated log/cache growth or
  another site's database does not invalidate an otherwise unchanged target.
  Do not infer ownership from a filename or use generic task/event retention.
- Adding an `event_time` retention index and changing Site Return Package
  treatment of `online_mr_task_sessions` remain separate contract decisions.
