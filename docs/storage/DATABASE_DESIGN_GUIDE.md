# Database Design Guide

## Scope

This guide applies to new and modified NetConsole SQLite schemas, repositories, raw-file indexes,
and persistent projections. It must be used with the machine-readable
[storage registry](../../config/storage_registry.yaml), [storage architecture](./STORAGE_ARCHITECTURE.md),
and [data root rules](./DATA_ROOT.md).

Database optimization is functionally transparent. It may change storage representation, row
layout, indexes, sharding, compression, and disk use; it may not change business results, query
ordering, timestamp precision, recovery behavior, user workflow, or the availability of protected
raw evidence.

## Register Before Writing

Before a module creates a database or persistent file set, add one registry entry that names:

- stable store ID and `PathResolver`-relative pattern;
- producer and repository/service owner;
- all known operational, query, export, package, and recovery consumers;
- one primary data class plus allowed/forbidden classes;
- authority statement and rebuildability;
- retention owner, package policy, backup policy, migration policy, and schema version;
- source locations used by the architecture guard.

Do not derive purpose from a filename. Do not add a generic “SQLite owner” for unrelated domains.
If any field is unresolved, register the store as `UNKNOWN_PROTECT` and leave it untouched until
consumer and lifecycle evidence is complete.

## Separate Current, History, And Raw

Use the narrowest representation that preserves semantics:

| Need | Preferred representation |
| --- | --- |
| Restart/current state | one operational row per stable business identity, updated transactionally |
| Immutable event/measurement history | append-only fact rows or bounded time shards with stable identity |
| Long-range aggregation | versioned trend rows linked to the raw fact range |
| Original command/log/file evidence | one managed raw Artifact with content hash and stable reference |
| Parsed/rebuildable analysis | versioned derived database selected through a catalog/manifest |
| Import/export work | managed staging with no authority until validated publication |

A parsed row should normally carry `source_id`, event timestamp, parser/schema version,
`artifact_ref`, and source/content hash. Do not copy complete raw command output into Task result,
Task event, parsed database, Artifact, ZIP, and report merely for convenience. A compatibility copy
may remain while old consumers exist, but it must be identified as compatibility data and have an
explicit exit gate.

## Identity And Idempotency

Every historical or imported source needs a deterministic identity. Choose identity from stable
business keys and content evidence, not local auto-increment IDs or filenames alone.

- Raw import: source/content SHA-256 plus scoped source metadata.
- Parsed projection: source identity plus parser/schema version.
- Task result: task ID, terminal result type, and canonical result hash.
- History migration: source database identity, source table, and source primary key/range.
- Package merge: stable site UUID, baseline revision, stable entity/task/event IDs, and checksums.

Reimporting or reparsing the same source must be a no-op, a verified replacement of the same
projection, or an explicitly versioned new projection. It must not append a duplicate full payload.
Hash equality alone does not authorize deletion when ownership is unknown.

## Measurements

RSSI, optical RX/TX, Ping RTT, Channel Busy, throughput, jitter, loss, voltage, temperature, and
similar measurements are `HISTORICAL_RAW_FACT` unless a domain contract says otherwise.

- Preserve the source timestamp and its precision. Do not round or coarsen raw history to save
  space.
- Keep units and null/error semantics stable. A missing sample, timeout, zero, and measured zero
  are distinct states.
- Compression and compact payload dictionaries are allowed only when decode restores the same
  values and shape.
- Trend tables may use windows such as minute/hour/day, but must record algorithm version, source
  range, sample count, and completeness. Raw history remains queryable.
- Index design must support the current entity/time and kind/time consumers without changing
  ordering or pagination.

## State And Snapshot Amplification

LLDP neighbors, interface mode, AP association, topology, administrative status, and similar state
can amplify storage when the same state is polled repeatedly. Measure amplification at 100, 1,000,
and 10,000 unchanged observations before selecting a design.

The preferred candidate, when business semantics permit it, is:

```text
current UPSERT
    + history on semantic change
    + optional low-frequency checkpoint/heartbeat
```

The fingerprint must contain only business-significant fields. Collection UUID, raw path, write
time, retry metadata, and other envelope fields must not create false changes. Telemetry fields that
must remain continuous belong in raw measurement history or a heartbeat payload, not in a state
fingerprint by accident.

This pattern may be adopted only after before/after parity covers latest-state reads, time ranges,
ordering, pagination, exports, package merge, restart/recovery, and every domain consumer. Until
then, existing repeated rows are protected.

## Payloads And Large Objects

For every candidate table, profile row count, logical payload bytes, TEXT/BLOB distribution,
indexes, freelist, timestamp range, source/artifact identity, duplicate content, current/history
ratio, and rebuildable ratio. Optimize the measured dominant component.

- Normalize repeated enums and repeated payload shapes only when query and decode cost are bounded.
- Prefer a stable Artifact reference over a second large TEXT/BLOB copy.
- Use compact or compressed payloads only with explicit codec/schema versions and fail on unknown
  versions.
- Never hide raw evidence inside an opaque database BLOB without source identity and export/recovery
  behavior.
- Remove an index only after all query plans and consumers have been checked. Add indexes for actual
  predicates/orderings, not speculative combinations.
- Logical deletion does not reclaim file bytes. Physical compaction is a separate destructive
  maintenance decision with backup, free-space, lock, and rollback gates.

## SQLite And Repository Rules

- Resolve all locations through `PathResolver`; never use `Path.cwd()` or a UI-supplied path.
- Keep SQLite connections process/thread local. Use project connection helpers, WAL/busy timeout,
  foreign keys, and explicit transactions as required by the repository.
- Perform schema migration in the owner service or a registered database-upgrade adapter. Router,
  Renderer, and Electron Main do not run SQL.
- Use SQLite Online Backup for a consistent copy of a live database. Copying only the main file
  while WAL contains data is not a snapshot.
- Validate shadow or imported databases before atomic publication. Failure retains the previous
  authority and produces diagnosis without creating an empty replacement.
- Database suffix handling must include `.db`, `.sqlite`, and `.sqlite3` wherever a contract claims
  generic SQLite coverage.
- Unknown schema versions, codecs, ownership, or package relations fail closed.

## Migration And Compatibility

An authority migration is staged:

```text
inventory -> copy/build -> verify -> consumer parity -> publish authority
          -> observation -> optional retirement plan -> separately authorized retirement
```

Copy/build completion is not cutover. Cutover is not source deletion. A rollback path remains valid
until retirement is separately approved. Migration reports must distinguish current authority,
compatibility reads/writes, verified projections, pending consumers, and unsupported/unknown rows.

Legacy data must not be guessed into a new shape. Unsupported rows stay at the source and make the
retirement gate fail. Production source `DELETE`, `DROP`, `VACUUM`, database replacement, and data-root
relocation require a separate maintenance authorization; development-only rehearsal under
`D:\study` is not production approval.

## Definition Of Done

A database design is complete only when:

1. the registry chain and lifecycle owner are complete;
2. all existing and new consumers have before/after query parity;
3. restart, cancellation, failure, and interrupted publication preserve authority;
4. duplicate import/reparse and long-running replay pass No-Reinflation checks;
5. Site Package include/exclude/reference behavior is explicit;
6. raw evidence, measurement precision, and source/session mapping are preserved;
7. storage reduction is measured across the recursive site footprint, not just one main database;
8. automated evidence is separated from real-site, HDD, production, and long-duration evidence;
9. unresolved items remain `PENDING` or `UNKNOWN_PROTECT` rather than being described as complete.
