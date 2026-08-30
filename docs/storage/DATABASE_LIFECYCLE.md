# Database And Persistent Storage Lifecycle

## Lifecycle Contract

Every registered store has one lifecycle owner. That owner must handle creation, active use,
snapshot/rotation, validation, recovery, retention, and retirement without transferring authority
implicitly to a backup, staging directory, export, or cache.

```text
DECLARED
  -> CREATED / IMPORTED
  -> ACTIVE
  -> SNAPSHOT or SHADOW_BUILD
  -> VERIFIED
  -> PUBLISHED / SEALED
  -> RETAINED or REBUILDABLE
  -> RETIREMENT_ELIGIBLE
  -> separately authorized RETIRED
```

Any failed validation returns to the previous valid authority or a recoverable failed state. It
must not publish a partially copied site, empty database, incomplete archive, or unverified parsed
projection.

## Rules By Data Class

| Class | Create/use | Archive/rebuild | Retirement gate |
| --- | --- | --- | --- |
| `OPERATIONAL_CURRENT` | Created and migrated by its repository/owner; remains restart-safe | Consistent snapshot only; never reconstructed from assumptions | Replacement validated, smoke-tested, and reversible |
| `HISTORICAL_RAW_FACT` | Append with stable identity and original time precision | Seal/shard/archive with manifest and query parity | Retention policy, complete consumers, and separate authorization |
| `HISTORICAL_TREND` | Build from declared raw ranges with versioned algorithm | Rebuild when source or algorithm changes | Raw authority remains available and trend consumers can tolerate rebuild |
| `ARTIFACT_OR_RAW_FILE` | Write once or atomically publish; record hash/reference | Package or relocate with manifest-preserved identity | Domain retention plus reference and legal/evidence checks |
| `CACHE_REBUILDABLE` | Bounded, owner-scoped, never authoritative | Drop/rebuild after active-use check | Source and rebuild path verified |
| `STAGING_TEMPORARY` | Unique operation directory below a managed staging/temp root | Resume, roll back, or remove after interruption | No published authority or live operation references it |
| `BACKUP_ROLLBACK` | Create from a consistent source and verify manifest/integrity | Reuse the same verified source revision; keep bounded owner groups | Newer valid recovery chain and explicit owner policy |
| `DISPOSABLE_DERIVED` | Build from registered raw/source identity | Validate and atomically select a replacement | Rebuild parity and all consumers proven |
| `UNKNOWN` | Read-only inventory only | None | Never automatic; resolve owner/authority first |

## Operational And History Owners

`devices.db` and `tasks.db` stay operational. The runtime HistoryStore has been fully retired:
current state, recovery metadata, and the four bounded device/AC history projections remain in the
operational databases. Legacy HistoryStore/catalog/shard material is maintenance-only evidence;
any source retirement is separately authorized and does not move active state or unresolved
compatibility data.

Ground `index.sqlite` remains operational because unattended restart, active schedules, event
references, and session queries depend on it. Historical Ping/Syslog/MR facts move only under the
Ground raw/archive contract. The READY archive cannot be treated as complete until its manifest and
members verify, and `active/` cannot be retired while restart or active-run consumers still need it.
If a process stops after READY publication, retry first idempotently binds every CLOSED/RECOVERED
raw-file row to the verified archive, then removes `active/` only when no unarchived row remains.
Record-level Syslog rewrites use a durable old/new SHA-256 and Registry-revision journal; startup
rolls back an uncommitted file replacement or finalizes a metadata-committed replacement.

MESH raw logs are long-term evidence. Catalog source identity prevents duplicate import; parsed
aggregate and source-detail databases may be rebuilt only from registered raw sources and only
after atomic replacement and consumer parity. Online MR uses the same principle, but its raw
directory and session ZIP require an explicit manifest authority decision to avoid permanently
keeping or prematurely deleting two full raw copies.

Legacy Online MR parsed schemas remain mixed stores: timestamped `collector_logs`, Ping samples,
radio raw indexes, live measurements and events are historical facts; `ping_summary` is a trend;
`live_switch_history_latest` is an operational compatibility projection; analysis/index metadata
is derived. Store-level `derived` naming never overrides these per-table contracts, and trend or
latest projections never replace the original measurement precision.

## Backup Lifecycle

A backup record must identify source store, source revision/fingerprint, operation, creation time,
size, hash, integrity result, and owner group. Creating another full copy of the same source revision
does not add recovery value; the owner should reuse the verified backup or explain why a new backup
is required.

Backup policy is owner-specific:

- database upgrade backups live in the registered upgrade backup center;
- database migration and base-data import backups remain tied to their migration/import operation;
- Site Sync rollback sets remain tied to one package SHA-256/base revision/mode; identical replay
  returns the completed audit result without creating another full snapshot;
- sealed raw/history authority is not duplicated as a routine backup merely because it is large.

Unknown legacy backup names or schemas stay protected. Empty, corrupt, or unreadable files are
diagnostic evidence until their owner decides otherwise; an automated cleaner must not infer that
they are safe from size alone.

Unified DataRoot migration keeps conflicts and source archives/history as rollback material,
reports/manifests/audits as historical facts, and unmatched source trees as
`UNKNOWN_PROTECT`. Knowing that the migration tool copied an `unclassified/**` file identifies the
producer but not the file's business owner or retirement policy.

## Staging, Cache, And Temporary Data

Every operation that writes staging must define all terminal paths:

| Outcome | Required behavior |
| --- | --- |
| Success | Validate, atomically publish, close SQLite handles, then remove operation staging |
| Validation or write failure | Leave previous authority unchanged; remove disposable staging or retain a registered diagnostic reference |
| Cancellation | Stop at a transaction/chunk boundary; remove unpublished work owned only by the operation |
| Process interruption | Journal enough state to resume, roll back, or identify and safely retire the abandoned directory |
| Restart | Reconcile operation state before creating another projection or full backup for the same revision |

Site Package temporary directories use `PathResolver.temp_dir`. Database upgrade shadows use their
registered temporary/journal roots. Generic cache cleanup is limited to registered cache/runtime
owners; it does not recurse into site databases, raw evidence, artifacts, backups, migration
material, or `.trash/`.

## Site Package Export And Import

Export must snapshot all SQLite files covered by the package contract using Online Backup, including
`.db`, `.sqlite`, and `.sqlite3`. Manifest and checksums are written from those snapshots, not from a
mix of live main files and WAL state.

Import is a transaction across files, databases, and Registry publication:

1. extract only into managed staging;
2. validate paths, links, sizes, checksums, manifest, SQLite integrity, package type, site identity,
   and relation summaries;
3. migrate/initialize only the staged databases required by the package contract;
4. close handles before Windows atomic publication;
5. publish or merge according to package type;
6. on any failure, restore the pre-import rollback set and remove files added by that operation;
7. clean staging on success and failure; reconcile interrupted staging on restart.

`collection_return` additionally journals `PREPARING -> PREPARED -> APPLYING -> APPLIED`. Recovery
removes an incomplete pre-apply snapshot, restores databases/metadata and exact created paths for an
interrupted APPLYING operation, or retains an APPLIED result only when its package hash, audit and
applied revision agree.

`field_collection` and `collection_return` remain partial synchronization contracts. They must not
be presented as a replacement for full operational, History, Task History, Ground, MESH, Online MR,
or Artifact authority.

## Retention And Destructive Actions

Inventory, scan, preview, delete plan, validation, and execution are separate steps. A scan token or
successful size estimate is not deletion authorization.

Before a destructive action, the owner must revalidate:

- resolved path remains inside the allowed store root and is not a symlink/junction escape;
- source/store identity, revision, schema, hash, and plan digest still match;
- no active task, Ground run, writer, WAL transaction, import, migration, or package operation needs
  the target;
- all protected source rows/files and all current consumers remain available;
- rollback material is verified and sufficient free space exists;
- exact row/file counts match the approved plan;
- post-action integrity, query parity, and recursive footprint are recorded.

`DELETE`, `DROP`, `VACUUM`, source replacement, and raw-file retirement are never implied by a
registry classification. Current production storage remains read-only for audit. Destructive
rehearsal is limited to isolated data below `D:\study`; it cannot be promoted to production merely
because automated tests pass.

## Current Boundaries

- History COPY/verify and query-authority transition exist, but production source deletion and
  physical replacement are not authorized.
- Task history cleanup in the product remains preview-only while policy and rollout gates are
  pending.
- Shared database-upgrade adoption is partial; domain-specific owners remain responsible until a
  dedicated adapter is implemented and tested.
- Full Site-wide No-Reinflation, real Windows Server HDD observation, production cutover, and any
  data-root/HDD migration remain `PENDING` unless a separate evidence record explicitly completes
  them.
- Dynamic `MRDatabase` and legacy site database recovery remain `UNKNOWN_PROTECT`.
