# ADR: Storage Authority And Lifecycle

## Metadata

| Item | Value |
| --- | --- |
| Status | Accepted as an architecture rule; production cutover and destructive maintenance are not authorized |
| Date | 2026-08-16 |
| Scope | All NetConsole SQLite databases, raw/Artifact files, derived stores, staging, cache, and backups |
| Machine-readable contract | [`config/storage_registry.yaml`](../../config/storage_registry.yaml) |
| Explicitly excluded | Production DELETE/DROP/VACUUM, production database replacement, HDD/data-root migration, and claims of completed long-duration observation |

## Context

Optimizing only `devices.db` and `tasks.db` cannot control total site growth. Ground/Unattended,
Online MR, MESH imports, Syslog/Ping, trackside measurement, analysis, Artifact, Site Package,
backup, cache, and staging owners can each retain the same raw payload or create repeated full
database copies. Filename- or directory-based cleanup cannot distinguish operational recovery
state, immutable raw evidence, rebuildable projections, and abandoned temporary work.

The same fact may currently appear in a raw log or ZIP, an imported copy, parsed rows, Task result,
Task event payload, Artifact, and report. Without a declared authority and stable source identity,
deduplication risks deleting evidence or breaking a consumer. Conversely, treating every copy as
permanent makes future storage growth unbounded.

## Decision

1. NetConsole uses `config/storage_registry.yaml` as the machine-readable map from store to
   producer, repository/service, consumer, authority, lifecycle owner, package policy, backup
   policy, and migration policy.
2. Every persistent store uses one of the registered data classes. `UNKNOWN = PROTECT`; unresolved
   ownership or authority fails closed.
3. Operational current state, historical raw facts, trends, raw/Artifact authority, derived data,
   staging, cache, and rollback backups are separate lifecycle concepts even when they share a
   directory or SQLite file.
4. Raw evidence is stored once where practical. Databases prefer stable source identity, timestamp,
   parsed facts, Artifact reference, and hash over repeated complete raw payloads.
5. Measurement history preserves original timestamp precision. Trend layers may accelerate queries
   but do not replace raw history.
6. Repeated state may move toward current UPSERT plus history on semantic change and optional
   checkpoint only after full consumer query parity.
7. Every import, parse, package, and backup operation must be idempotent by stable source or revision
   identity and must pass No-Reinflation replay.
8. Site Package transport must preserve or explicitly exclude all relevant authority. Generic
   SQLite handling covers `.db`, `.sqlite`, and `.sqlite3`; field and return packages remain partial
   contracts.
9. Staging/cache have no business authority and require success, failure, cancellation, and restart
   cleanup/recovery. Backups are revision-aware, bounded rollback material.
10. Storage optimization is functionally transparent. Before/after business/query/recovery parity
    and protected-data reconciliation are mandatory.

## Consequences

- New SQLite/DDL source locations require a registry declaration and architecture guard coverage;
  a source may use only the physical database filename patterns of its bound store and cannot borrow
  another store's global `*.sqlite` declaration.
- Storage inventories are recursive across the whole site and report authority, protected bytes,
  duplicates, and expected future growth, not only file size.
- Domain owners retain responsibility until a shared lifecycle adapter has actually been
  implemented and tested; the registry does not imply shared-framework adoption.
- Derived databases can be rebuilt only from registered, protected source identity with validated
  atomic publication and consumer parity.
- Cleanup becomes an explicit owner operation with preview, plan digest, revalidation, rollback,
  and post-action evidence.
- Some compatibility duplication remains temporarily valid. It must be reported as compatibility
  data with an exit gate rather than deleted speculatively.
- Dynamic `MRDatabase`, legacy `analysis/mesh/<id>/analysis.sqlite`, and legacy
  SiteDatabaseRecovery material remain `UNKNOWN_PROTECT` until their production consumers, source
  identities and recovery contracts are proven.

## Rejected Alternatives

| Alternative | Reason rejected |
| --- | --- |
| Classify by `.db` filename or directory | Same suffix/path can contain current state, history, derived data, or rollback material |
| Keep every copy permanently | Allows silent reinflation and hides authority conflicts |
| Delete all duplicate hashes | Hash equality does not prove ownership, consumer independence, or recovery safety |
| Replace raw measurements with aggregates | Loses timestamp precision and prevents future reanalysis |
| Treat Site Package as automatic full authority | Field/return packages are intentionally partial; references and exclusions matter |
| Treat backup or staging as a second authority | Creates ambiguous recovery and unbounded copies |
| Declare derived data disposable by design alone | Rebuildability and consumer parity require executable evidence |

## Evidence And Status Boundary

The architecture rule is accepted. Current implementation contains the registry/guard, History V2
and compatibility paths, Task result authority work, owner-specific MESH/Online MR/Ground lifecycle
logic, and Site Package snapshot/staging behavior. Adoption and verification differ by owner and
must remain explicit in current documentation and test evidence.

This ADR is not evidence that a real production site was changed, that all No-Reinflation scenarios
passed, that a Windows Server HDD observation completed, or that production source data can be
deleted. Those remain separate gates defined by the
[Storage Testing Guide](../storage/STORAGE_TESTING_GUIDE.md) and
[Database Lifecycle](../storage/DATABASE_LIFECYCLE.md).
