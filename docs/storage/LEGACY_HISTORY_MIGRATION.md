# Legacy Device History Migration And Non-destructive Cutover

## Status

This maintenance capability copies supported legacy `*_history` rows from one
resolved `devices.db` into the existing monthly HistoryStore shards. New target
writes use [History Storage V2](./HISTORY_STORAGE_V2.md), while existing V1-only
and mixed V1/V2 shards remain readable. It is
explicitly invoked, defaults to off, and never runs during application startup
or installation.

The initial migration remains COPY-only. A3 adds an explicit, per-source-table
query-authority state machine, but cutover is non-destructive:

- source rows are never updated or deleted;
- before cutover, source rows remain authoritative and migrated
  `event_type=legacy` shard rows remain hidden from normal HistoryStore queries;
- after an explicit table cutover, the matching legacy table is excluded from
  the ordinary query and the verified shard rows become authoritative;
- there is no source-delete, table-drop, compaction, replacement, or VACUUM API;
- rollback only changes query authority while the source remains intact.

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
- `legacy_history_authority_transitions`: immutable per-table revision history
  for cutover, rollback and observation-gate transitions.

V2 does not repeat `legacy_source_table` and `legacy_source_id` in every target
payload. The range journal is the durable provenance for source table, source
key range, month, digest and sample; a future cutover must require a `VERIFIED`
range instead of inferring provenance from duplicated payload metadata.

Migration status remains one of `PENDING`, `COPYING`, `VERIFYING`, `VERIFIED`
and `FAILED`; it does not imply query authority or source-delete eligibility. A
chunk writes one target-month transaction at a time, verifies exact event IDs,
stable digests and deterministic samples, then advances the source checkpoint.
If the process exits after target commit but before checkpoint, resume repeats
at most the last chunk and `INSERT OR IGNORE` makes it idempotent. If it exits
after checkpoint, resume starts after the durable last source key.

Invalid timestamps and unsupported row shapes are not dropped silently. Only
source table, source key and a reason code are written to
`LEGACY_HISTORY_INVALID_ROWS.jsonl`; any such row makes the result `NOT_READY`.

## Authority, Rollback And Delete-plan Preview

Each supported source table independently moves through:

```text
LEGACY_AUTHORITY -> SHARD_VERIFIED -> SHARD_AUTHORITY
                                     -> SOURCE_DELETE_ELIGIBLE
```

`SOURCE_DELETED` is reserved in the schema but cannot be entered by current
code. `SHARD_VERIFIED` is set only after the table and all ranges verify.
`cutover` requires an expected revision and reason, then changes only that
table's ordinary query authority. Other tables may remain under legacy
authority. `rollback` returns `SHARD_VERIFIED`, `SHARD_AUTHORITY` or
`SOURCE_DELETE_ELIGIBLE` to `LEGACY_AUTHORITY` without copying or changing the
source.

The observation gate requires query validation, consumer validation and no
integrity mismatch. Eligibility is then recalculated from current supported
source rows, verified ranges, source/target digests and canonical projection
mapping. Unsupported/invalid rows are permanently excluded. Retired projection
duplicates are eligible only when their canonical source mapping and target
event both revalidate.

`preview-delete-plan` writes `LEGACY_HISTORY_DELETE_PLAN.json` with exact
source key ranges, row/verified counts, per-range digests, authority revision,
eligibility and exclusions. `validate-delete-plan` rechecks the source database
identity, current range proof, revision and stable plan digest. Both commands
are preview/validation only; no DELETE executor exists.

## Priority And Commands

The maintenance class is `site-database-maintenance`. The implementation
uses the shared cross-process key `site-database-maintenance:<site_id>`.
History migration/cutover and Site Retention scan/apply now use the same key;
Site Retention acquires it before its narrower storage lock. Future compact
must use this helper instead of introducing a second lock family.

`start` and `resume` require explicit `--apply`. `pause` changes the requested
state; a running process observes it after the current transaction/checkpoint.
An active unattended callback pauses before admitting another chunk. The
elapsed budget likewise decides whether another chunk may start and never
interrupts a SQLite transaction. Chunk sizes are restricted to 100, 250 or
500 rows.

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
& ".\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history inventory `
  --data-root "D:\NetConsoleData" --site-id "<site-id>" --light

& ".\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history start `
  --data-root "D:\study\test-data\NetConsole\device-history-migration\<run-id>\runtime" `
  --site-id "<registered-test-site>" --source-db "D:\study\test-data\NetConsole\device-history-migration\<run-id>\devices.db" `
  --history-root "D:\study\test-data\NetConsole\device-history-migration\<run-id>\history" `
  --diagnostics-dir "D:\study\diagnostic\NetConsole\device-history-migration\<run-id>" `
  --immutable-source --chunk-rows 500 --apply

& ".\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history cutover `
  --data-root "<isolated-data-root>" --site-id "<site-id>" `
  --migration-id "<migration-id>" --source-table "<verified-table>" `
  --expected-revision 1 --reason "consumer validation passed" --apply

& ".\.venv\Scripts\python.exe" -m scripts.maintenance.migrate_device_history preview-delete-plan `
  --data-root "<isolated-data-root>" --site-id "<site-id>" `
  --migration-id "<migration-id>" --source-table "<eligible-table>" `
  --diagnostics-dir "D:\study\diagnostic\NetConsole\device-history-cutover\<run-id>"
```

The benchmark entry supports isolated synthetic or snapshot runs and reports
rows/second, source/target bytes, chunk latency, target/checkpoint commits,
months, duplicates and errors:

```powershell
& ".\.venv\Scripts\python.exe" -m scripts.maintenance.benchmark_device_history_legacy_migration `
  --synthetic-rows 10000 --chunk-rows 500 `
  --output-dir "D:\study\diagnostic\NetConsole\device-history-migration\<run-id>\benchmark-medium"
```

Storage profiling and V1/V2 query comparison are separate read-only tools. Both
accept only paths under `D:\study`; profiling VACUUM is limited to rebuildable
diagnostic scratch databases and never applies to the source snapshot.

`validate_history_migration_server_hdd.py` only evaluates previously captured
migration, host diagnostic and operational-observation JSON. It never opens the
source database or runs migration. Missing real HDD performance counters,
backend/outbox/Unattended/Syslog/MR/Ping evidence, or any failed observation
keeps `SERVER_HDD_STORAGE_V2_TEST=PENDING`.

## Remaining Gates

- Real Windows Server HDD long-duration migration remains pending until a
  separately approved maintenance window; SSD/synthetic delay is not an HDD
  substitute.
- Query cutover is implemented but requires an explicit per-table command and
  has not been applied to production data.
- Source-delete eligibility and a digest-protected preview plan are implemented;
  source DELETE, DROP, production VACUUM and physical shrink remain unavailable.
