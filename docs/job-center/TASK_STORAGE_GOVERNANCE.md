# Task Storage Governance

## Phase 1 Result

Task storage governance began with read-only profiling. That Phase 1 evidence
remains below as capacity context; the current retention policy is the bounded
Task Center rule documented in [Bounded Retention](#bounded-retention).

The production snapshot assessed on 2026-08-15 is 419,778,560 bytes with
102,485 4-KiB pages, `freelist_count=0` and a zero-byte WAL. Its size is live
logical content rather than deleted-page or WAL bloat. `task_events` is
dominated by event payloads, `task_snapshots` by terminal `result_json`, most
large terminal results occur in both the current snapshot and latest
`finished` event, and high-frequency producers append consecutive identical
progress events.

The duplicate terminal representation is not changed in Phase 1. Event replay,
WebSocket recovery, Online MR reconciliation and Site Package merge contracts
consume it, so removing one copy requires a separate shared-contract design.
The recommended current option is D: bound proven write amplification first,
then implement the now-confirmed bounded retention policy.

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

## Bounded Retention

普通终态 Task Center 记录按 `site_name + task_type` 保留最近 10 个有效任务。
`TaskRepository.retain_recent_terminal_tasks()` 在事务中删除旧任务的
`task_events`、`task_snapshots` 和无引用 `task_results`；活动任务、Online MR
mapping、Ground/MESH/Online MR 业务引用保持不变。该操作不删除 Artifact、raw、
MESH source、Online MR session 或 Ground archive。

## Deferred Work

- 生产 DataRoot 的 DELETE、DROP、VACUUM、数据库 replacement 和 backup retirement
  仍不执行；本轮只完成实现与隔离测试。
- Terminal result representation, event archive/shards and database split are
  unchanged.
- Artifact filesystem truth remains owned by
  `ArtifactReconciliationService`; the profiler reports DB references only.
- Adding an `event_time` retention index is a schema migration and is deferred.
- Site Return Package treatment of `online_mr_task_sessions` requires a product
  contract decision.
