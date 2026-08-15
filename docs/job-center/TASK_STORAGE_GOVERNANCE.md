# Task Storage Governance

## Phase 1 Result

Task storage governance starts with read-only profiling. Phase 1 does not
delete, archive, compact, VACUUM, change the user-visible retention period or
split `tasks.db`.

The production snapshot assessed on 2026-08-15 is 419,778,560 bytes with
102,485 4-KiB pages, `freelist_count=0` and a zero-byte WAL. Its size is live
logical content rather than deleted-page or WAL bloat. `task_events` is
dominated by event payloads, `task_snapshots` by terminal `result_json`, most
large terminal results occur in both the current snapshot and latest
`finished` event, and high-frequency producers append consecutive identical
progress events.

The duplicate terminal representation is not changed in Phase 1 or B2. Event
replay, live WebSocket delivery, Online MR reconciliation and Site Package merge
contracts consume it. The consumer audit, four design options, recommended
authoritative `task_results` model, retention proposal, index proposal and
maintenance-exclusive owner are recorded in
[Task Terminal Result Consumer Matrix](./TASK_TERMINAL_RESULT_CONSUMER_MATRIX.md).

## B3 Immutable Result Compatibility Phase

Schema version 4 adds immutable `task_results` with deterministic `result_id`,
`task_id`, terminal event type, canonical UTF-8 JSON, SHA-256, byte size,
schema version and creation time. `result_id` derives from task identity,
terminal event type and result hash, so a retry of the same semantic result is
idempotent. A trigger rejects updates to an existing authority row.

Schema capability is separate from the per-database write rollout. New and
upgraded databases both initialize the persisted state to `LEGACY_DUAL_FULL`;
the presence of schema version 4 or an empty `task_results` table never enables
dual-write. The four modeled states are:

| State | Write behavior | Current apply availability |
| --- | --- | --- |
| `LEGACY_DUAL_FULL` | full snapshot + full event; no new `task_results` row | default |
| `TASK_RESULTS_DUAL_WRITE` | full snapshot + full event + immutable result | explicit CAS transition only |
| `TASK_RESULTS_VERIFIED` | compatibility validation completed; still no ref authority | apply disabled |
| `RESULT_REF_AUTHORITY` | future single full result plus refs/summaries | production apply disabled |

The current state, revision, timestamp, actor, reason and schema version live in
the same `tasks.db`. Transitions use an expected revision and append an
immutable audit row. The only enabled transitions are explicit
`LEGACY_DUAL_FULL -> TASK_RESULTS_DUAL_WRITE` and the non-destructive rollback
that stops future dual-writes while retaining all existing result rows.

When `TASK_RESULTS_DUAL_WRITE` is explicitly active, `finished/error/cancelled`
events containing an object result perform result insert/validation, snapshot
update and terminal event insert in one `BEGIN IMMEDIATE` transaction. The live
WebSocket payload uses the persisted and verified identity. In the default
state, terminal persistence remains equivalent to B2 and performs no result
authority insert. Query paths remain enabled in every rollout state and verify
result id/hash/size/task ownership while supporting:

- legacy rows with only full `result_json`;
- B3 rows with `result_id` plus the old full snapshot/event result;
- future ref-only fixtures that read through `task_results`.

Site Return Package import also remains independent of local rollout state. A
package may merge valid `task_results` without changing future local writes.
Artifact finalization may update the snapshot projection but cannot change an
immutable terminal authority row. Ref-only writing and historical backfill are
not enabled.

Site Return Package now merges `task_results`, `task_snapshots`, `task_events`
and `online_mr_task_sessions` in that order inside one transaction. Immutable
result/event or Online MR mapping conflicts fail closed; same-content retries
are no-ops, incomplete/wrong-site references are rejected, and Artifact events
do not create authority results.

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
$env:PYTHONPATH = "$PWD\src;$PWD"
& ".\.venv\Scripts\python.exe" -m scripts.maintenance.profile_tasks_db `
  --data-root "D:\NetConsoleData" --site-id "<site-id>"

& ".\.venv\Scripts\python.exe" -m scripts.maintenance.profile_tasks_db `
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
databases under `D:\study`. It compares a legacy dual-full baseline, the real
guarded default, explicit `TASK_RESULTS_DUAL_WRITE` and future ref-only
simulation at 100/1,000/10,000 small-result tasks. Bounded actual samples cover
medium and approximately 4.5 MB results without creating a multi-GB cross
product. The report includes DB/WAL bytes, bytes/task, write and read-through
latency, result hash cost, plus the existing 3,000-event progress sampling
comparison. Explicit dual-write deltas are compatibility overhead; only the
future ref-only delta is labelled potential. Terminal layout capacity is
measured after a common WAL checkpoint/truncate so checkpoint timing cannot
double-count pages; progress sampling retains live DB/WAL measurements.

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
& ".\.venv\Scripts\python.exe" -m scripts.maintenance.benchmark_tasks_db_governance `
  --output-dir "D:\study\diagnostic\NetConsole\tasks-db-governance\<run-id>"
```

Rollout status and the two approved transitions use the explicit maintenance
CLI. Status output contains only schema/state/revision/count flags; transitions
require `--expected-revision`, a reason and `--apply`:

```powershell
& ".\.venv\Scripts\python.exe" -m scripts.maintenance.manage_task_result_rollout `
  status --data-root "<data-root>" --site-id "<site-id>"

& ".\.venv\Scripts\python.exe" -m scripts.maintenance.manage_task_result_rollout `
  enable-dual-write --data-root "<data-root>" --site-id "<site-id>" `
  --expected-revision 1 --reason "approved compatibility validation" --apply
```

## Deferred Work

- Destructive retention is `NOT STARTED`.
- Retention periods are `USER_POLICY_REQUIRED`; soft-dismiss expiry does not
  authorize physical deletion.
- Stopping the old full snapshot/event result copies, event archive/shards and
  database split are deferred.
- Artifact filesystem truth remains owned by
  `ArtifactReconciliationService`; the profiler reports DB references only.
- Adding an `event_time` retention index is a schema migration and is deferred.
- Typed retention is preview-only inside the existing `SiteRetentionService`.
  It reports snapshot type/status, event 14/30/90-day proposals, result rows and
  estimated bytes, but its candidate is unsafe, apply-disabled and performs no
  task DELETE or VACUUM.
- History migration and Site Retention now share
  `site-database-maintenance:<site_id>` through `database_maintenance_lock()`;
  future compact must reuse the same key.
- Real Electron GUI, long-running Agent/Online MR/Ground activity, target HDD
  and result-ref-only production cutover remain separate acceptance gates.
- `TASK_RESULTS_VERIFIED` evidence approval and `RESULT_REF_AUTHORITY` are
  separate future gates; this phase exposes no apply transition for either.
