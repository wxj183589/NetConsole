# NetConsole Storage Architecture

## Purpose

This document defines how NetConsole assigns authority and lifecycle ownership to every
SQLite database and persistent file set. It supplements the physical [data layout](./DATA_LAYOUT.md)
and domain documents; it does not authorize production migration, deletion, compaction, or
retention.

The machine-readable source is
[`config/storage_registry.yaml`](../../config/storage_registry.yaml). A store is not governed
merely because its filename ends in `.db` or `.sqlite`: its producer, repository/service,
consumer, authority, retention owner, package policy, backup policy, and migration policy must
all be known. New SQLite access is rejected by the storage registry architecture guard unless
its source location or owner is registered.

## Authority Model

Every persistent store must be traceable through this chain:

```text
database/table or file set
    -> producer
    -> repository/application or domain service
    -> consumer
    -> lifecycle owner
```

The lifecycle owner is responsible for creation, validation, recovery, retention, and final
retirement. A directory owner is not automatically the owner of every database found below that
directory. Filename, age, file size, and content hash are evidence, not ownership proof.

The registry resolves a physical store only from a unique path contract. A database that can hold
more than one data class must also provide exact `table_rules`; each rule carries the table's
authority, producer, consumers, lifecycle owner, rebuildability, and source-code evidence. Tables
without an exact rule fail closed to `UNKNOWN_PROTECT`. The audit does not infer lifecycle from a
database filename, a `_history` suffix, or the raw profiler's observed classification.

Authority follows these rules:

1. One fact has one declared raw or canonical authority. Other copies are references,
   compatibility projections, exports, rollback material, or rebuildable derivatives.
2. A database should store `source_id`, event time, parsed facts, `artifact_ref`, and content
   hash instead of repeating a complete raw payload already owned by a managed file or package.
3. A rebuildable projection remains protected until its source identity, rebuild path, consumer
   parity, and atomic replacement behavior are all proven.
4. A backup is rollback material, not a second operational authority.
5. Staging and cache have no business authority and must have an explicit cleanup or recovery
   owner.
6. Any unresolved store or table is `UNKNOWN`. `UNKNOWN = PROTECT`: it is non-rebuildable,
   non-deletable, and cannot be silently omitted from a package that claims complete authority.

## Data Classes

The registry accepts only the following classes:

| Class | Meaning | Default lifecycle |
| --- | --- | --- |
| `OPERATIONAL_CURRENT` | Current state required for normal operation or restart | Keep available; migrate through an owner-specific compatible path |
| `HISTORICAL_RAW_FACT` | Immutable or append-only historical business fact | Preserve precision and provenance; shard/archive only after query parity |
| `HISTORICAL_TREND` | Long-term aggregate derived from raw measurements | Keep linked to raw history and version the aggregation rule |
| `ARTIFACT_OR_RAW_FILE` | Raw evidence or managed user-visible artifact | Store once with hash, source identity, and stable reference |
| `CACHE_REBUILDABLE` | Rebuildable acceleration data with no authority | Owner may rebuild or clean after active-use checks |
| `STAGING_TEMPORARY` | Unpublished transaction work | Clean on success/failure; recover or retire after interruption |
| `BACKUP_ROLLBACK` | Bounded, verified rollback material | Retain by revision-aware owner policy; never treat as current |
| `DISPOSABLE_DERIVED` | Parsed or calculated data reproducible from protected authority | Delete only after rebuild and consumer parity are proven |
| `UNKNOWN` | Ownership, authority, or recovery contract is incomplete | `PROTECT`; no automatic migration, cleanup, or omission |

`HISTORICAL_TREND` does not replace `HISTORICAL_RAW_FACT`. RSSI, optical power, Ping RTT,
Channel Busy, and other measurements retain their original timestamp precision; trend layers may
only accelerate long-range queries.

## Registered Storage Domains

The registry contains the detailed store-by-store map. The table below summarizes its current
authority boundaries without replacing that map.

| Domain | Operational/current authority | History, raw, or derived authority | Lifecycle owner |
| --- | --- | --- | --- |
| Devices | `devices.db`, including current state and History outbox | `db/history/catalog.db` plus verified monthly shards | `DeviceRepository`, `HistoryStore`, `SiteRetentionService` |
| Tasks | `tasks.db`, active state, lightweight snapshots, immutable result references and recovery | `task_result_blobs` is the current terminal-result body authority; legacy full rows and future HistoryStore archives remain compatibility/history evidence | `TaskRepository`, `TaskResultBlobRepository`, `TaskHistoryStore`, `SiteRetentionService` |
| Agent | `agents.db`; Agent-local acknowledged/unacknowledged task package state is separate | Agent packages remain outside Controller Site Package authority | `AgentRepository`, Windows Go Agent lifecycle |
| Ground/Unattended | `ground_unattended/index.sqlite` for recovery, current schedule, and structured references | active NDJSON is raw authority until a verified READY archive; the READY ZIP is historical raw authority | Ground repository, raw lifecycle, and archive service |
| MESH | `catalog.sqlite` owns source fingerprint and selected projection metadata | raw logs are evidence authority; `mesh.sqlite` and per-source `*.mesh.sqlite` are rebuildable projections | MESH catalog/storage and derived-data maintenance services |
| Online MR | current vehicle MR state, per-session metadata, and legacy latest-switch projection | session raw is evidence; parsed measurement/event rows preserve historical facts, Ping summary is trend, remaining analysis/index rows are derived; a ZIP is authority only when its manifest explicitly says so | Online MR session lifecycle |
| Network measurements | traffic, iPerf, wireless-scan, and trackside session databases own declared scalar facts | raw device output remains in the corresponding raw tree when registered as evidence | domain repository or collection lifecycle |
| WPS sync | `sync/wps_sync.sqlite` owns current sync state and bounded audit references | full repeated request/result payload is not a second authority | `WpsSyncRepository` |
| Artifacts | database rows carry stable references | `sites/{site_id}/artifacts/**` owns managed reports/downloads/raw artifacts | Artifact lifecycle |
| Backups | none | upgrade, migration, base-data import, and Site Sync rollback sets | the registered backup or operation owner |
| Runtime work | none | Site Package and database-upgrade staging; job/export/cache work | `PathResolver`-scoped transaction or cleanup owner |

Code and Git history identify the retired `snmp.db` producer as `SiteSnmpRepository`, old
`raw/config/**` as Config Lifecycle raw evidence, and `downloads/files/**` as legacy managed device
downloads. They are registered legacy authorities, but that identification does not authorize the
active product to read, rewrite, or delete them. Retired SNMP/MIB data remains protected under the
removed-feature preservation contract.

Material without a proven content owner remains in the inventory rather than being assigned to the
nearest directory owner. Current examples include old FIT-AP and Ground rollback copies, dynamic
`MRDatabase` storage, legacy `SiteDatabaseRecoveryService` material, Ground Ping-loss intervals,
retired Wi-Fi tables, and unified-migration `unclassified/**` trees. All remain
`UNKNOWN_PROTECT`; registry presence, producer knowledge, or a plausible filename does not make
their contents safe to remove.

The recursive footprint also covers DataRoot-global storage outside `sites/**`. Unified migration
conflicts, source archives/history, reports, manifests, audits, and staging recovery have separate
owners; `unclassified/**` stays protected. Runtime logs, active Job/Export state, upgrade and
retention journals, Electron user/session data, preview/cache roots, legacy Agent data/packages,
global configuration, and retired MIB archives are registered independently so a broad cache or
migration rule cannot hide operational state or raw evidence.

## Ground And Raw Evidence

Ground storage deliberately separates three concerns:

- `index.sqlite` holds restart/current state, structured event references, deduplicated Syslog
  facts, and rebuildable correlations. It is not the authority for every received raw byte.
- `active/<date>/**` NDJSON preserves high-frequency Ping, Syslog, AC snapshots, and scheduler
  evidence needed before archival.
- A verified READY archive becomes the historical raw authority only after manifest, member,
  size, and hash checks. Active/archive coexistence must remain query-safe and deduplicated.

Progress rows, repeated snapshots, and repeated payloads are disposable only when their business
semantics, recovery consumers, and raw references have been checked. Storage changes must preserve
unattended restart, active tasks, MR/session mapping, Ping/Syslog time association, and historical
queries.

For MESH and Online MR, a raw log, imported copy, parsed database, Task result/event payload,
Artifact, ZIP, and report may describe the same source. The raw authority decision belongs in a
manifest and source-identity record. A portable ZIP is not automatically the authority merely
because it exists, and a parsed database is not automatically disposable merely because raw files
also exist.

## Site Package Authority

Site Package is transport, not an implicit reclassification of every included file.

Registry coverage applies to every store whose path is under `sites/{site_id}/`, including
`unknown.*` PROTECT declarations. An UNKNOWN path may be conditionally carried, but it cannot be
silently omitted from coverage merely because its owner ID is not prefixed `site.`.

| Package | Authority boundary |
| --- | --- |
| `full_migration` | Full-site snapshot transport. Current code snapshots `.db`, `.sqlite`, and `.sqlite3` with SQLite Online Backup and verifies manifest/checksum/integrity before publication. Included authority and references must remain self-consistent. |
| `sanitized_share` | Site snapshot with credential redaction. It is not credential authority and must retain explicit exclusions/redactions. |
| `field_collection` | Deliberately partial field baseline: devices/configuration/point-table scope. It is not Task History, Ground, MESH, Online MR, or full-site authority. |
| `collection_return` | Incremental merge of supported devices/tasks and changed files against a baseline. It is not a complete authority transfer. |

Operational databases, History catalog/shards, Task History/results, and referenced Artifacts must
either be included coherently or be declared excluded by that package contract. Import staging is
`STAGING_TEMPORARY`; it must be removed after success or failure and must be recoverable or safely
retired after interruption. `SitePackageStagingLifecycle` journals user-selected publish staging,
removes only an exact destination-bound hidden file, and recovers known internal staging before the
backend accepts work. Full-site replacement has a separate target/backup journal: startup preserves
an atomically published target or restores the exact rollback directory when the target is absent.
Rollback retention is still explicit and bounded automatic retirement is not inferred from this
recovery behavior. See [Site Package Format](./SITE_PACKAGE_FORMAT.md).

## Implementation Status

The following distinctions are mandatory when reporting storage work:

| Area | Current status |
| --- | --- |
| Registry classification and architecture guard | Implemented in the current tree; it detects unregistered SQLite/DDL source locations and validates `UNKNOWN_PROTECT` and lifecycle fields |
| Devices History V2 and legacy COPY/verify/query-authority tooling | Implemented with V1/mixed compatibility and isolated snapshot evidence; no production source deletion or physical replacement is authorized |
| Task result authority | DEV-only Blob-first authority is integrated: new rows keep the body in `task_result_blobs`, old full-only/dual rows remain readable; Production migration and broad retention remain gated |
| Site Package SQLite suffix and managed staging handling | Current code covers `.db`, `.sqlite`, and `.sqlite3`; full/return/field authority boundaries remain intentionally different |
| Shared database-upgrade framework | Partial adoption; `mesh_derived` is the first adapter, while other stores retain domain-specific migration paths |
| Complete Site-wide No-Reinflation proof | Required by [Storage Testing Guide](./STORAGE_TESTING_GUIDE.md); do not infer completion from one snapshot, one database, or registry presence |
| Production cutover, HDD observation, production delete/VACUUM | `PENDING`; this architecture does not authorize them |

The registry is a design and guardrail source. It does not itself prove that production data has
been migrated, that every consumer passed parity, or that a retention action is safe.
