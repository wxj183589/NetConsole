# Legacy Device History COPY-only Migration

## Status

This maintenance capability copies supported legacy `*_history` rows from one
resolved `devices.db` into the existing monthly HistoryStore shards. New target
writes use [History Storage V2](./HISTORY_STORAGE_V2.md), while existing V1-only
and mixed V1/V2 shards remain readable. It is
explicitly invoked, defaults to off, and never runs during application startup
or installation.

Migration remains COPY-only for source data. After a verified copy, query authority
can be switched explicitly for one source table in an isolated catalog:

- source rows remain preserved and are never updated or deleted; their query
  authority is selected only by the recorded per-table authority state;
- migrated shard events use `event_type=legacy` and remain hidden from normal
  HistoryStore queries while that table has legacy query authority, preventing legacy
  + shard duplicate results;
- a `VERIFIED`, error-free table first reaches `SHARD_VERIFIED`; an explicit,
  revision-CAS protected cutover with a non-empty reason may change it to
  `SHARD_AUTHORITY`, and explicit rollback returns it to `LEGACY_AUTHORITY`;
- there is no source-delete, table-drop, compaction, replacement, or VACUUM API;
- there is no automatic or production cutover; production authorization and any
  source-delete design require separate approval.

## Inventory

`HistoryLegacyMigrationService.inventory()` discovers every table whose name
ends in `_history` and writes `LEGACY_HISTORY_INVENTORY.json`. Each table is
classified as `SUPPORTED`, `UNSUPPORTED`, or `UNKNOWN_SCHEMA` and records its
schema, primary key, indexes, entity mapping, timestamp, identity and nullable
columns, source schema version, target shard schema, row count and time range.

The ten Phase 1 mappings already supported by `HistoryStore` are accepted only
when their required `id`, timestamp and business identity columns exist.
`ac_fit_ap_unauthenticated_history` and
`ac_station_online_summary_history` are explicitly unsupported because no
target event contract exists. Any other history schema is unknown and makes a
run `NOT_READY`; rows are never guessed into a target shape.

## Identity And Duplicate Projections

The durable source database identity combines the site identity, schema
version, page size, discovered history schemas, primary-key ranges and the
first/last stable source rows. It does not depend only on a path and does not
hash the entire database. A migration ID cannot resume against another source
identity, site or schema version.

Most target event IDs use `source_table + source primary key`. Two retired AP
projection pairs require a canonical business identity:

- `ac_fit_ap_lldp_history` / `ap_lldp_history`;
- `ac_fit_ap_optical_history` / `ap_optical_history`.

The authoritative `ac_fit_ap_*` source is always copied first and every
authoritative row keeps its own `source_table + source PK` event identity. A
retired projection row is matched to an authoritative source row using the
shared normalized business fields, then verifies that authoritative target
event without writing another event. It increments `duplicate_count` without
collapsing distinct authoritative rows or overwriting their payloads.

## Journal And Recovery

The existing history `catalog.db` owns three additive migration tables:

- `legacy_history_migrations`: migration/source identity, requested state,
  totals, commit telemetry and overall status;
- `legacy_history_migration_tables`: per-source-table range, last source key,
  counts, error and status;
- `legacy_history_migration_ranges`: source key range + target month, stable
  source/target digests, deterministic samples, counts, latency and budget.

V2 does not repeat `legacy_source_table` and `legacy_source_id` in every target
payload. The range journal is the durable provenance for source table, source
key range, month, digest and sample; an explicit cutover requires a `VERIFIED`
range instead of inferring provenance from duplicated payload metadata. The same
catalog owns each table's authority state, monotonic cutover revision, reason,
timestamps and append-only authority transition audit row.

Only `PENDING`, `COPYING`, `VERIFYING`, `VERIFIED` and `FAILED` are valid. A
chunk writes one target-month transaction at a time, verifies exact event IDs,
stable digests and deterministic samples, then advances the source checkpoint.
If the process exits after target commit but before checkpoint, resume repeats
at most the last chunk and `INSERT OR IGNORE` makes it idempotent. If it exits
after checkpoint, resume starts after the durable last source key.

Authority is independent of the migration status. Successful verification moves a
table from `LEGACY_AUTHORITY` to `SHARD_VERIFIED`; the explicit cutover and rollback
operations run under the existing maintenance lock and require the caller's expected
revision and a reason. Both operations retain the legacy source table and report
`DELETE=NO`, `DROP=NO`, `VACUUM=NO`.

Invalid timestamps and unsupported row shapes are not dropped silently. Only
source table, source key and a reason code are written to
`LEGACY_HISTORY_INVALID_ROWS.jsonl`; any such row makes the result `NOT_READY`.

## Priority And Commands

The maintenance class is `site-database-maintenance`. The implementation
reuses the existing cross-process database maintenance lock for its own run.
SiteRetention currently uses a different lock family, so unifying all future
retention and migration operations remains `SHARED_CHANGE_REQUIRED` and is not
claimed by this branch.

`start` and `resume` require explicit `--apply`. `pause` changes the requested
state; a running process observes it after the current transaction/checkpoint.
An active unattended callback pauses before admitting another chunk. The
elapsed budget likewise decides whether another chunk may start and never
interrupts a SQLite transaction. Chunk sizes are restricted to 100, 250 or
500 rows.

```powershell
$env:PYTHONPATH = "D:\study\worktrees\NetConsole\device-history-legacy-migration\src;D:\study\worktrees\NetConsole\device-history-legacy-migration"
& "D:\study\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history inventory `
  --data-root "D:\NetConsoleData" --site-id "<site-id>" --light

& "D:\study\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history start `
  --data-root "D:\study\test-data\NetConsole\device-history-migration\<run-id>\runtime" `
  --site-id "<registered-test-site>" --source-db "D:\study\test-data\NetConsole\device-history-migration\<run-id>\devices.db" `
  --history-root "D:\study\test-data\NetConsole\device-history-migration\<run-id>\history" `
  --diagnostics-dir "D:\study\diagnostic\NetConsole\device-history-migration\<run-id>" `
  --immutable-source --chunk-rows 500 --apply
```

The benchmark entry supports isolated synthetic or snapshot runs and reports
rows/second, source/target bytes, chunk latency, target/checkpoint commits,
months, duplicates and errors:

```powershell
& "D:\study\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.benchmark_device_history_legacy_migration `
  --synthetic-rows 10000 --chunk-rows 500 `
  --output-dir "D:\study\diagnostic\NetConsole\device-history-migration\<run-id>\benchmark-medium"
```

Storage profiling and V1/V2 query comparison are separate read-only tools. Both
accept only paths under `D:\study`; profiling VACUUM is limited to rebuildable
diagnostic scratch databases and never applies to the source snapshot.

## Remaining Gates

- Real Windows Server HDD long-duration migration remains pending until a
  separately approved maintenance window; SSD/synthetic delay is not an HDD
  substitute.
- Isolated-catalog query cutover compatibility is covered by regression tests, but
  no automatic or production cutover workflow is authorized. Source tables must
  remain intact and readable so an explicit rollback can restore legacy authority.
- Source delete design, retention and physical file shrink are not started.
