# Storage Testing Guide

## Objective

Storage validation must prove two properties at the same time:

1. recursive site footprint and future growth are controlled;
2. every existing function, business result, query, recovery path, and user workflow remains
   unchanged.

A smaller database is a failure if it loses raw evidence, changes ordering or precision, breaks
Ground restart, detaches MR/session mapping, changes Ping/Syslog correlation, or leaves package
staging/backups growing without an owner.

## Evidence Artifacts

A complete storage audit emits six machine-readable storage reports and three functional-parity
reports. Their exact generators are owned by the maintenance/rehearsal implementation; this guide
defines the minimum evidence, not a second report format. Final evidence mode requires both the
site-root and data-root-global inventories plus measured optimization impact, and binds every
storage report to the Git HEAD, storage-registry SHA-256, and finalizer-script SHA-256.

### Storage reports

| Report | Minimum content |
| --- | --- |
| `SITE_STORAGE_INVENTORY.json` | Recursive site files/databases, sizes, store ID/class, SQLite tables/indexes/freelist/time ranges, raw/artifact identity, and unknown findings |
| `DATABASE_OWNER_MAP.json` | `database/table -> producer -> repository/service -> consumer -> lifecycle owner`, authority, rebuildability, package/backup/migration policy |
| `STORAGE_DUPLICATION_AUDIT.json` | exact and semantic duplicate groups across raw/ZIP/import/DB/Task/Event/Artifact/report, bytes, hashes/source identity, protected and removable conclusions |
| `STORAGE_LIFECYCLE_PLAN.json` | current authority, target lifecycle, prerequisites, owner, before/after/history/protected/duplicate bytes, rollback, status, and future growth behavior |
| `DATA_LIFECYCLE_CLASSIFICATION.json` | every file and database table mapped to one mandatory lifecycle class, with unresolved content remaining `UNKNOWN_PROTECT` |
| `SITE_STORAGE_FOOTPRINT.json` | recursive site plus data-root-global before/after/history/duplicate/protected bytes, authority, and future growth behavior by required storage group |

### Functional reports

| Report | Minimum content |
| --- | --- |
| `FUNCTIONAL_BASELINE.json` | immutable before-state queries, consumer results, recovery state, precision, performance, and source evidence |
| `FUNCTIONAL_AFTER.json` | the same observations against the isolated optimized copy, bound to the matching baseline and final HEAD |
| `FUNCTIONAL_COMPATIBILITY.json` | per-consumer semantic, ordering, precision, recovery, API/export, and performance comparison with fail-closed overall status |

`scripts/maintenance/validate_database_functional_compatibility.py` first produces the direct
database Before/After core comparison. `scripts/maintenance/benchmark_database_functional_queries.py`
then records p50/p95/max and deterministic result hashes for the real isolated Device, FIT-AP,
LLDP, History, Task, MESH, and Ground query paths. Final reports are published only by
`scripts/maintenance/finalize_functional_compatibility.py`, which requires PASS evidence for the
core comparison, integrated Site Package, No-Reinflation, performance, final Storage footprint,
and separate TARGETED/FAST/CONSUMER/FULL Gate reports bound to the same Git HEAD. The TARGETED
report is produced by `scripts/quality/run_storage_targeted_gate.py` in an isolated test data root.
Before the core comparison, `scripts/maintenance/collect_functional_consumer_observations.py`
binds every final consumer to canonical results from the integrated Site Package, performance,
and No-Reinflation evidence. The final consumer matrix rejects any Before/After query-digest
difference even when both individual observation manifests claim PASS.

Each SQLite table must report, where applicable:

- row count and estimated logical payload bytes;
- large TEXT/BLOB counts, total bytes, and largest values without exposing sensitive content;
- indexes and measured database/index pages;
- page size, page count, freelist, WAL/SHM state, and integrity result;
- minimum/maximum timestamps and timestamp precision;
- source ID, artifact reference, parser/schema version, and content hash coverage;
- exact/semantic duplicate content;
- operational-current versus history ratio;
- rebuildable versus protected ratio.

Unknown schema, owner, source identity, or lifecycle becomes `UNKNOWN_PROTECT` in the report. The
auditor must not infer purpose from a database filename.

## Before/After Functional Parity

For every optimized store, record a stable before/after comparison of:

- row counts by semantic class and protected identity;
- latest-state reads, entity/time and kind/time ranges, ordering, limits, offsets, and pagination;
- null, error, timeout, duplicate, and missing-artifact behavior;
- timestamp values and precision for measurements;
- hashes or canonical summaries of API DTOs, exports, Task detail, and report inputs;
- restart/recovery state, active task state, session mapping, and Artifact references;
- legacy/current/mixed-format reads and rollback after failed cutover;
- SQLite integrity and query plans for critical predicates.

History or state-change compaction requires parity against every registered consumer, not only a
repository unit test. If a consumer cannot be exercised, status stays `PENDING` and its source data
stays protected.

The final consumer matrix includes Device Management, Interfaces, LLDP, Optical, FIT-AP and Radio,
Trackside AP, AP Identity, Rail Base Data, History, Task Center, REST, WebSocket, Agent, Online MR,
Ground, MR collection/raw import, MESH and RSSI/link/switch analysis, Ping, Syslog, Artifact,
import/export, Site Package, restart/recovery, performance, and No-Reinflation. A full-suite PASS
without the real Before/After and Site Package evidence does not populate this matrix.

## No-Reinflation Replay

No-Reinflation is a forward-growth gate, not a one-time VACUUM result. Run the same realistic input
through the current code repeatedly and report total recursive bytes, operational bytes, history
bytes, duplicate payload bytes, backup bytes, staging/cache bytes, and rows by authority after each
cycle.

The executable gate is `python -m scripts.maintenance.validate_storage_no_reinflation`. Every
scenario records a `STORAGE AMPLIFICATION FACTOR` with declared logical input events, SQLite bytes,
WAL/SHM/journal bytes, raw/Artifact bytes, total physical bytes, and bytes per input event. These
physical measurements supplement owner-specific row/authority assertions; they do not authorize
deleting raw measurements or replacing business parity with a byte threshold.

Required scenarios include:

| Scenario | Pass condition |
| --- | --- |
| Devices current/history | Repeated unchanged state uses current UPSERT plus bounded heartbeat/change history; `devices.db` does not regain copied legacy history |
| Task terminal result | One canonical full result identity; compatibility copies do not multiply on retry/replay |
| Ground continuous run | Recovery/current state remains bounded; Ping/Syslog raw grows once per received record and parsed/progress payload is not repeated without need |
| Online MR continuous collection | Session identity remains stable; online and offline replay use raw-file/offset/hash identity, and raw text is not copied repeatedly into parsed DB, Task result/event, Artifact, and ZIP without an explicit authority decision |
| MESH repeat import/reparse | Ten imports and ten forced reparses of the same source hash/fingerprint remain idempotent; reparsing replaces or versions one projection and does not append a second source |
| Raw log repeat import | Stable source identity produces a no-op or an explicit conflict, never silent duplicate facts |
| Site Package export/import | All SQLite suffixes are consistent; success/failure/cancel staging is cleaned; identical return-package replay creates no revision/backup; interrupted APPLYING/APPLIED work is rolled back or retained from durable evidence |
| Backup retry | Same source revision reuses a verified backup; owner retention prevents unbounded full copies |
| State amplification | 100, 1,000, and 10,000 identical LLDP/interface/AP-state observations preserve expected current/history/checkpoint counts |

Pass/fail thresholds belong to the owner-specific plan and must be recorded before the run. “Growth
was smaller than before” is insufficient when growth is still unbounded or authority is duplicated.

## Site Package Matrix

Test all package types separately:

- `full_migration`: operational DBs, History catalog/shards, Task History/results, raw/Artifact
  references, `.db/.sqlite/.sqlite3`, WAL snapshot consistency, replacement, and restart;
- `sanitized_share`: the same structural integrity with credential redaction and explicit excluded
  authority;
- `field_collection`: only the documented field baseline; verify that omitted domains are not
  claimed as transferred authority;
- `collection_return`: baseline/site identity, devices/tasks/history references, stable merge IDs,
  duplicate files, conflicts, rollback, and no implicit deletion.

For export and import, inject failure before extraction, after extraction, during database
validation, during staged migration, before publication, and during merge. Verify previous
authority, rollback material, newly added files, open handles, and staging on success, failure,
cancellation, and restart.

## Validation Sequence

Run validation on the final integrated HEAD in increasing scope:

```text
TARGETED
  -> FAST
  -> registered CONSUMER suites
  -> FULL PYTHON
  -> Renderer
  -> Electron
  -> architecture/static guards
  -> read-only real snapshot regression
```

Targeted storage checks include the affected repository/service tests, migration/retention tests,
Site Package tests, and the storage registry guard. The guard entry point is
`python -m scripts.architecture.check_storage_registry`; it validates registration and scans for
unregistered SQLite/DDL sources. The final suite and commands remain governed by
[Testing Baseline](../testing/BASELINE.md) and Change Impact output.

Ordinary failures are diagnosed, fixed at their owner, and rerun from the appropriate scope. A
branch-local green result does not replace final integrated consumer and full-suite validation.

## Real Data And Safety

- Production `D:\NetConsoleData` and every discovered production database are read-only during
  audit and regression.
- Copies, generated diagnostics, benchmarks, and destructive rehearsals stay below `D:\study`.
- A real Ningbo Line 12 snapshot may be copied to an isolated development path and used for
  read-only source comparison plus destructive work on the copy only.
- Never run source `DELETE`, `DROP`, `VACUUM`, replacement, or cleanup against production merely to
  obtain a smaller number.
- Report recursive whole-site footprint. `devices.db + tasks.db` alone is not the site total.

The final storage summary groups operational databases, History shards, Ground/Unattended,
Online MR, MR raw/MESH, Syslog/Ping, analysis, Site Package staging, cache/temp, backups, and
Artifacts/raw. Every group reports `before_bytes`, `after_operational_bytes`,
`history_moved_bytes`, `duplicates_removed_bytes`, `protected_bytes`, authority, and expected
future-growth behavior.

## Functionally Transparent Definition Of Done

Storage work is `READY` only when the final integrated HEAD has completed all applicable automated
stages and the evidence proves:

- no protected rows/files or raw precision were lost;
- all registered consumers and recovery paths have before/after parity;
- Site Package authority and staging lifecycle are coherent;
- No-Reinflation scenarios pass for every changed producer;
- recursive whole-site bytes and protected bytes reconcile;
- unresolved stores remain `UNKNOWN_PROTECT`;
- production cutover, HDD migration, long-duration observation, and destructive production actions
  are reported independently and remain `PENDING` unless actually completed.

Documentation, registry presence, synthetic tests, or an isolated SSD snapshot must never be used
to claim Server HDD observation, production rollout, or production data migration.
