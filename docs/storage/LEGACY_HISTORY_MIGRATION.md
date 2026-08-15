# Legacy Device History COPY-only Migration

## Status

This maintenance capability copies supported legacy `*_history` rows from one
resolved `devices.db` into the existing monthly HistoryStore shards. It is
explicitly invoked, defaults to off, and never runs during application startup
or installation.

Phase 1 is COPY-only:

- source rows remain authoritative and are never updated or deleted;
- migrated shard events use `event_type=legacy` and remain hidden from normal
  HistoryStore queries, preventing legacy + shard duplicate results;
- there is no source-delete, table-drop, compaction, replacement, or VACUUM API;
- a future source cutover/delete design requires separate approval.

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

Only `PENDING`, `COPYING`, `VERIFYING`, `VERIFIED` and `FAILED` are valid. A
chunk writes one target-month transaction at a time, verifies exact event IDs,
stable digests and deterministic samples, then advances the source checkpoint.
If the process exits after target commit but before checkpoint, resume repeats
at most the last chunk and `INSERT OR IGNORE` makes it idempotent. If it exits
after checkpoint, resume starts after the durable last source key.

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

## Remaining Gates

- Real Windows Server HDD long-duration migration remains pending until a
  separately approved maintenance window; SSD/synthetic delay is not an HDD
  substitute.
- Normal query cutover remains disabled, so copied events intentionally do not
  replace legacy reads.
- Source delete design, retention and physical file shrink are not started.
