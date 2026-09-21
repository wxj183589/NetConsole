# Production Write Entrypoint Inventory

> P7.3-A audit evidence, 2026-09-21. This document is a repository-tracing
> inventory only. It does not authorize an operation and it does not change
> any product source, database, schema, migration, rollout, MESH state, or
> Production data.

## Baseline and boundary

| Item | Value |
| --- | --- |
| Repository | `https://github.com/wxj183589/NetConsole.git` |
| Audit branch | `codex/production-write-entrypoint-inventory-20260921` |
| Audit baseline | `27fd85ea542f168fc330fa1658ee53b1e27435a4` |
| P7.1 baseline | Retired-task GC allowlist guard, merged and validated |
| P7.2 baseline | Production task-result compaction allowlist guard, merged and validated |
| Phase B | `PAUSED_SAFETY_BUG`; this audit does not resume it |
| Source changes | `NO` |
| Production access | `NO`; no `D:\NetConsoleData` or `D:\NetConsoleData-dev` access was performed |

The inventory treats a path as a Production write entrypoint when the source
can mutate a Production database, schema, registry, authoritative derived
state, backup/rollback artifact, or a Production site file. It includes direct
maintenance CLIs, HTTP-to-worker chains, startup recovery, scheduled cleanup,
and destructive site/storage actions. Ordinary task/device/result CRUD and
normal telemetry ingestion remain outside this P7 maintenance inventory unless
the entrypoint is a schema, repair, migration, rollback, or destructive
cleanup operation.

The audit did not execute any of the following: database open in writable mode,
schema upgrade, migration, rollout, MESH rebuild/remap, GC, compaction,
backup/restore/rollback, file replacement, or real-data validation.

## Inventory summary

The matrix contains 22 logical write-capable entries in the P7 boundary:

| Status | Count | Meaning |
| --- | ---: | --- |
| `SAFE_CANONICAL` / `FIXED_P7_1` / `FIXED_P7_2` | 3 | Canonical Production site/database scope and operation gate are present or the P7 fix is complete |
| `PARTIALLY_GUARDED` | 13 | Some site, operation, confirmation, transaction, or rollback control exists, but the P7 canonical Production authority is not consistently enforced |
| `UNGUARDED` | 6 | A Production-reachable write path has no canonical Production site authority and/or no fail-closed Production operation gate |
| `UNKNOWN` | 0 | No unresolved write family was left without a status |

The six `UNGUARDED` entries are the current safety bug surface. Phase B must
remain paused until each one has an explicit disposition and the required
follow-up is implemented and validated.

## Authority model

### Site scope authority

The canonical Production site authority is the combined contract implemented
by [`production_database_maintenance.py`](../../src/netconsole/services/production_database_maintenance.py):

1. `PRODUCTION_SITE_ALLOWLIST` accepts only the nine registered Production
   site IDs.
2. `SiteRegistryRepository` supplies the persisted site record and registered
   root; a directory scan, display name, raw CLI directory, or database
   existence is not an authority source.
3. The resolved site root and database path must be the canonical child of the
   canonical data root and must not cross reparse/link boundaries.
4. Database names are separately restricted by
   `PRODUCTION_DATABASE_ALLOWLIST`.

`SiteRegistry` alone is useful for normal application routing, but it is not
equivalent to the P7 Production allowlist. A `PathResolver` alone is a path
calculator, not a Production authorization boundary.

### Operation authority

Operation authority is separate from site authority. It includes the explicit
Production authorization token/flag, `--apply` or equivalent mode, plan digest,
expected revision, user confirmation, maintenance window/lock, writer
quiescence, backup/rollback owner, and domain preflight. An operation gate
cannot repair an arbitrary site path, and a canonical site path cannot by
itself authorize a destructive operation.

### Shared Production flags and their limitation

| Source | Flag/marker | Current behavior | Finding |
| --- | --- | --- | --- |
| `src/netconsole/core/runtime_environment.py` | `NETCONSOLE_ALLOW_PRODUCTION_WRITE=1` | Allows `require_data_root_write_allowed()` to pass when the root is marked Production | Boolean capability only; it does not resolve a canonical site or database |
| `scripts/maintenance/upgrade_ap_extension_schema.py` | `--allow-production-write` | Enables the shared environment flag for direct DB or `--all-sites` apply | Insufficient without canonical site/database resolution |
| `scripts/maintenance/manage_task_result_rollout.py` | `--allow-production-write` | Enables the shared environment flag for rollout state mutation | SiteRegistry path is not checked against the Production allowlist |
| `scripts/maintenance/rebuild_mesh_parsed_data.py` | `--allow-production-write` | Enables the shared environment flag for derived-state repair | Raw `--site` and `--data-root` remain directly accepted |
| `scripts/maintenance/remap_mesh_identity.py` | `--allow-production-write` | Enables the shared environment flag for identity/source rebuild | No canonical Production site resolver |
| Electron/backend launchers | `--allow-production-write` / environment propagation | Carries the capability into a runtime process | Not an independent write authority and must not substitute for scope checks |

The cleanup GC has a separate `--allow-production --apply` operation gate. The
P7.1/P7.2 implementations do not rely on the shared boolean as their site
authority.

## Entrypoint matrix

| ID | File and function/class | Operation/domain/invocation | Write or destructive effect | Production reachability and target resolution | Site scope authority | Operation authority before first mutation | Backup/rollback/transaction | First mutation and path behavior | Status / risk / follow-up |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `PROD_DB_MAINTENANCE` | `scripts/maintenance/production_database_maintenance.py`; `ProductionMaintenanceCapability` | Explicit Production database maintenance capability | Schema/DB replacement, execute, rollback, manifest/evidence updates | Production only; canonical `resolve_production_site_scope()` and `resolve_production_database_scope()` | Allowlist + persisted `SiteRegistry` + canonical path + anti-reparse + DB allowlist | Explicit authorization, evidence/manifest binding, maintenance lock, writer quiescence, mode gates | Candidate/backup, validation, atomic switch, restore path | All target checks precede candidate/backup mutation; provider failure is fail-closed | `SAFE_CANONICAL`; baseline to reuse |
| `GC_CLEANUP_P7_1` | `scripts/maintenance/cleanup_retired_tasks.py`; `TaskCleanupService` / `TaskAuthorityIndex` | Explicit task-owned retired-task GC; CLI `--apply` | Deletes task-owned rows and authority-index rows | Production reachable only through canonical site expansion; `--all-sites` expands the allowlist, not directories | P7.1 `resolve_production_site_scope()` | `--apply` + `--allow-production`, active-task checks, maintenance boundary | No business-data backup; DB transaction and task-authority consistency checks | First DB mutation occurs after scope and active-task checks | `FIXED_P7_1`; baseline validated |
| `TASK_RESULT_COMPACTION_P7_2` | `scripts/maintenance/compact_task_result_production.py`; plan/apply functions | Production `tasks.db` task-result compaction | `VACUUM INTO`, parity check, atomic DB replacement | Exact Production root plus canonical `tasks.db` scope; no direct arbitrary DB target | P7.2 canonical resolver and registry re-resolution | Exact authorization token, plan digest, stale-source check, maintenance lock, pre/post parity | External backup and restore on postcheck failure | Candidate creation follows authorization; `os.replace()` follows parity checks | `FIXED_P7_2`; baseline validated |
| `TASK_RESULT_ROLLOUT` | `scripts/maintenance/manage_task_result_rollout.py`; `main`, `TaskResultRolloutService` | `disable-dual-write --apply`; enable path is intentionally disabled | Changes rollout state and audit/revision state in `tasks.db` | Production reachable with arbitrary `--data-root` containing a registry site | `SiteRegistry` supplies a site path, but no Production allowlist/reparse validation | `--apply` + `--allow-production-write` + expected revision + reason | CAS-style DB state transition; no independent backup/rollback owner | First state mutation is rollout CAS after the shared boolean gate | `PARTIALLY_GUARDED`; HIGH; P7.3-B |
| `TASK_RESULT_REF_ONLY_CLOSURE` | `scripts/maintenance/close_task_result_ref_only.py`; plan/apply | Production task-result ref-only closure | Updates canonical JSON/ref-only task-result rows and trigger state | Arbitrary `--data-root`; source is only checked as `root/db/tasks.db` | Path containment and plan site ID only; no canonical Production allowlist/registry resolution | Magic authorization + plan digest; no canonical site authorization | Backup before transaction; `BEGIN IMMEDIATE`, postcheck, restore on failure | Backup is the first side effect after local path checks | `PARTIALLY_GUARDED`; HIGH; P7.3-B |
| `AP_EXTENSION_SCHEMA_UPGRADE` | `scripts/maintenance/upgrade_ap_extension_schema.py`; `upgrade_database`, `upgrade_all_site_databases` | AP extension schema upgrade; direct `--db` or `--all-sites` | Schema metadata and AP extension schema mutation | Default/data-root may be `D:\NetConsoleData`; `--all-sites` uses `sites/*/db/devices.db` discovery | None; raw DB path or directory glob | Shared `--allow-production-write` boolean only; `--force` bypasses version precondition; `--no-backup` disables backup | Optional backup; SQLite context/commit; no complete operation journal or rollback contract | Backup is first side effect when enabled; `executescript` is first schema mutation | `UNGUARDED`; CRITICAL; P7.3-A |
| `MESH_DERIVED_REBUILD_CLI` | `scripts/maintenance/rebuild_mesh_parsed_data.py`; `build_plan`, `apply_plan` | Explicit MESH parsed/derived-state repair | Rebuilds parsed/derived DB and repair journal; raw source is read-only | Direct `--data-root` + required raw `--site`; plan is built before Production gate | None; `PathResolver` plus raw site string | `--apply` + shared `--allow-production-write`; no canonical Production resolver | Hash/preflight and service repair; no CLI-bound canonical plan digest/revision gate | Service repair starts journal/staging/derived writes after only boolean gate | `UNGUARDED`; HIGH/CRITICAL; P7.3-C |
| `MESH_IDENTITY_REMAP_CLI` | `scripts/maintenance/remap_mesh_identity.py`; `build_plan`, `apply_plan` | Explicit MESH identity/source remap and rebuild | Derived DB, source index/catalog identity projection and revision state | Direct `--data-root` + required raw `--site`; per-entry rebuild loop | None; direct site path resolution | `--apply` + shared `--allow-production-write`; no canonical resolver or per-entry revision binding | Read-only plan; per-entry exception handling; no complete rollback owner | First source/derived rebuild mutation occurs after only the boolean gate | `UNGUARDED`; HIGH/CRITICAL; P7.3-C |
| `STORAGE_RETIREMENT_CLI` | `scripts/maintenance/retire_unmanaged_storage.py`; preview/apply | Retire unmanaged/legacy storage candidates | Copies to retirement sibling, then deletes source files and writes manifest | Arbitrary `--data-root` and plan candidates can point at a Production root | Registry/protection manifest is a data-protection input, not the canonical Production allowlist | Plan digest, candidate protection, explicit apply; no Production mode/confirmation | Copy/hash verification and copy-back rollback on failure | Creates retirement destination before source deletion; source `unlink()` follows per-file copy | `UNGUARDED`; CRITICAL; P7.3-D |
| `UNIFIED_DATA_ROOT_MIGRATION` | `scripts/maintenance/migrate_unified_data_root.py`; `migrate`, execute/recover | Whole data-root migration and abandoned-staging recovery | Creates staging/registry/config and atomically publishes files/root children | `--target` defaults to `D:\NetConsoleData`; arbitrary target accepted | Direct target/source paths; no Production allowlist | `--execute` only; no Production authorization or maintenance window | Staging/hash/SQLite validation; recovery can remove abandoned staging; no P7 owner | Lock/staging creation is first mutation; `os.replace`/move publishes later | `UNGUARDED`; CRITICAL; P7.3-D |
| `LEGACY_RUNTIME_DATA_MIGRATION` | `scripts/maintenance/migrate_legacy_runtime_data.py`; plan/apply | Copies legacy runtime data into configured data root | Writes destination files and migration manifest | Destination defaults to runtime data root and can be Production | Direct destination path; no canonical Production resolver | `--apply` only; no Production authorization | No-overwrite copy and manifest; no full rollback owner | Destination directory/file copy is first mutation | `UNGUARDED`; HIGH; P7.3-D |
| `HTTP_TASK_CENTER_CLEANUP` | `src/netconsole/backend/api/job_center_router.py`; `/cleanup` -> task service/worker | User-requested task cleanup | Deletes task-owned result/event rows and authority state | Current site from authenticated desktop application context | Normal app site context/registry; not the P7 Production allowlist | Desktop/session and feature gate, explicit cleanup request/confirmation, active-task protection | Service transactions and authority checks; no P7 Production backup contract | Worker begins after request validation and current-task checks | `PARTIALLY_GUARDED`; HIGH for P7 scope; P7.3-B/C decision |
| `HTTP_SITE_RETENTION` | `site_storage_router.py`; retention scan/apply -> `SiteRetentionService` | Site retention, database backup/archive/delete, expired Online MR raw deletion | Deletes/archive files and writes retention reports | SiteRegistry record + controlled root; can operate on current Production site | Registry root and controlled relative paths, scan-token revalidation; not Production allowlist | Desktop/persistent-storage dependency, scan token, active-task lock, candidate policy | Backup archive for DB candidates; raw deletion has evidence but no restore archive | Retention report is persisted before apply; candidate file/DB action follows lock/recheck | `PARTIALLY_GUARDED`; HIGH; P7.3-D/C boundary |
| `HTTP_SITE_LIFECYCLE` | `site_storage_router.py`; create/update/trash/restore/demo rebuild | Site registry lifecycle and destructive site cleanup | Registry changes, staging, `.trash` move, restore, demo replacement | Site IDs resolve through application SiteRegistry; target paths are service-controlled | SiteRegistry and lifecycle path checks; not the P7 Production allowlist | Desktop/persistent storage, display-name confirmation, no-active-task checks, task worker | Staging, trash retention, restore; operation journals/locks | Staging or controlled trash move is first mutation after request checks | `PARTIALLY_GUARDED`; HIGH for destructive branches; P7.3-D |
| `HTTP_SITE_IMPORT_MIGRATE` | `site_storage_router.py`; export/import/site migrate/data-root migrate | Package import/replacement and site/data-root migration | Copies packages/staging, registry updates, atomic publish, possible replacement | Explicit destination/package paths after service validation; Production is a normal target | Registry and package inspection; destination is not P7 allowlisted | Desktop/persistent storage, package inspect, no-active-task checks; no P7 Production operation gate | Staging, SQLite validation, replacement backup/restore in import path; old data retained for root migrate | Staging creation/copy is first mutation; publish after validation | `PARTIALLY_GUARDED`; HIGH/CRITICAL; P7.3-D |
| `HTTP_DATABASE_UPGRADE_BACKUP` | `database_upgrade_router.py`; `DatabaseUpgradeManagementService` / `DatabaseUpgradeCoordinator` | Schema upgrades, backup lifecycle, restore/delete | Shadow DB build, atomic switch, backup/rollback/delete | Active application site and database-upgrade descriptors; normal Production path | Active site/registry context and controlled descriptor paths; not the P7 allowlist at this boundary | Desktop/feature gate, batch validation, confirmation, maintenance lock and coordinator preflight | Strong journal, backup validation, shadow smoke test, rollback and restore | Journal creation precedes backup; switch follows validated shadow | `PARTIALLY_GUARDED`; MEDIUM/HIGH; P7.3-A/D authority alignment |
| `HTTP_MESH_REPAIR_DELETE` | `mesh_analysis_router.py`; delete source(s), maintenance, rebuild | User-requested MESH source delete, parser maintenance, rebuild | Raw/source deletion or derived/identity rebuild depending operation | Current site and session IDs from HTTP/app context | Current SiteRegistry/app context; no P7 Production resolver in route/worker chain | Feature gates, task control, explicit confirmation and session preflight | Worker/service-specific locks and rebuild checks; no common P7 rollback owner | Task worker begins after route checks; domain service performs first mutation | `PARTIALLY_GUARDED`; HIGH; P7.3-C |
| `HTTP_AC_EXTENSION_ROLLBACK` | `ac_management_router.py`; `/extensions/audits/{audit_id}/rollback` | AC extension import apply/rollback and local rebuild | Devices DB extension rows/files and audit state | Current site from application context | App site context and audit identity; no P7 Production allowlist | Capability feature gate + explicit confirmation + audit lookup | Audit rollback/import service owns transaction/backup as applicable | Service operation starts after audit/confirmation checks | `PARTIALLY_GUARDED`; MEDIUM/HIGH; P7.3-A |
| `HTTP_BASE_DATA_ROLLBACK` | `rail_transit_base_data_router.py`; import apply and `/import-operations/{id}/rollback` | Rail-transit base-data import/rollback | Business DB tables and import operation state | Current site/app data root | Application site context; no P7 Production allowlist | Preview/operation ID and rollback request/confirmation | Import service transaction and operation journal | Apply/rollback transaction starts after operation validation | `PARTIALLY_GUARDED`; MEDIUM/HIGH; P7.3-A/D |
| `STARTUP_UPGRADE_RECOVERY` | `backend/api/main.py` -> `recover_incomplete_upgrades()` | Automatic recovery of interrupted DB switches | Journal status, shadow/rollback/backup file moves, active DB restore | Current `PathResolver` runtime root; can be Production | Persisted journal + controlled-path checks and lock; no explicit P7 allowlist | Persisted incomplete operation is the authority; no human confirmation at startup | Designed rollback/recovery and journal state; fail status is persisted | Journal recovery lock/status update is first write; file moves follow controlled paths | `PARTIALLY_GUARDED`; MEDIUM/HIGH; P7.3-A/D |
| `STARTUP_SITE_STAGING_RECOVERY` | `backend/api/main.py` -> `SitePackageService.recover_orphaned_staging()` | Automatic package staging cleanup/recovery | Staging files/registry/package recovery records | Current runtime root; Production is possible by normal app design | Service-controlled staging paths and package journal; no P7 allowlist | Persisted staging state and startup recovery policy | Staging recovery keeps failure diagnostics; rollback semantics are service-specific | Staging scan/recovery record precedes file cleanup | `PARTIALLY_GUARDED`; MEDIUM; P7.3-D |
| `AUTO_TASK_EVENT_RETENTION` | `backend/api/main.py` -> `TaskApplicationService.run_due_task_event_retention()` -> `TaskEventRetentionService.run_due()` | Deferred automatic terminal task-event retention | Deletes `task_events` rows and updates retention setting | Active site task repository; can be Production | PathResolver/site application context; no canonical Production allowlist | Automatic schedule and terminal/external-owner protection; no human confirmation or Production operation token | Per-batch DB operations and fail-closed external owner reads; no backup/restore | First row delete occurs after preview/protection reads; settings update follows | `PARTIALLY_GUARDED`; HIGH for destructive Production maintenance; P7.3-B/C decision |

## Unsafe and partially guarded entries requiring follow-up

### P7.3-A — AP extension schema upgrade

`upgrade_ap_extension_schema.py` is a direct Production-capable schema writer.
The `--db` branch accepts an arbitrary database path and the `--all-sites`
branch discovers `sites/*/db/devices.db` by directory glob. The shared
`--allow-production-write` marker is checked only at the data-root level. It
does not prove that the selected site is an allowlisted persisted site, that
the database is the canonical `devices.db`, or that a reparse/link boundary
was not crossed. `--no-backup` and `--force` further weaken recovery and
precondition behavior. Backup creation is the first side effect when enabled;
schema `executescript` is the first database mutation.

Required contract: resolve one canonical site/database through the P7 helper;
make `--all-sites` expand `PRODUCTION_SITE_ALLOWLIST` only; validate schema
version and required tables before any backup or write; fail closed on helper,
registry, provider, or path errors; bind the plan to registry/revision evidence;
retain a tested backup/rollback owner. Expected files are the script and its
targeted contract tests. No database migration is part of this audit.

### P7.3-B — Task-result rollout and ref-only closure

`manage_task_result_rollout.py` correctly requires an expected revision and
reason for the effective disable transition, but its Production gate is still
the shared boolean and its site path is only a `SiteRegistry` lookup under an
arbitrary root. `close_task_result_ref_only.py` has a useful path containment
check, plan digest, backup, transaction, postcheck, and restore, but the
`data_root` and site identity are not resolved through the canonical Production
allowlist/registry contract.

Required contract: make both operations resolve the canonical site and
`tasks.db` before plan acceptance; bind plan/revision/site/database identity;
keep authorization before backup/DB mutation; preserve current P7.2
maintenance-lock and rollback patterns; fail closed when registry/provider/path
validation is unavailable. Decide explicitly whether ref-only closure belongs
under the P7.2 compaction capability or a separate task-result maintenance
capability.

### P7.3-C — MESH derived rebuild and identity remap

The two CLIs accept `--data-root` and a raw `--site` value, build a plan before
the shared Production gate, and then call a service that writes derived state.
The parsed rebuild protects raw input with hashes, while identity remap
rebuilds eligible sources and updates identity/revision projections. These are
valuable domain preflights, but neither is a Production site authorization.
The remap loop also handles per-entry errors without a common operation-level
rollback owner.

Required contract: canonical site resolution before planning; explicit
Production operation capability; plan digest plus raw/catalog revision binding;
writer quiescence and maintenance lock; separate raw-source, derived-state,
identity-projection, and revision-state authorization; fail closed on any
provider/path/revision mismatch; define rollback or a durable recovery owner.
The HTTP MESH repair/delete chain must either reuse this contract or document a
separate equivalent contract before Phase B can resume.

### P7.3-D — Storage and data-root migration/retirement

`retire_unmanaged_storage.py`, `migrate_unified_data_root.py`, and
`migrate_legacy_runtime_data.py` are not covered by the P7 boolean gate. They
can receive a Production root through a direct argument or default, and they
perform copy, replace, delete, registry/config, or staging operations. Their
local plan/protection/rollback behavior is not a substitute for Production
site and operation authority.

Required contract: explicit source/target scope with canonical registry
binding; no directory discovery or broad root replacement; Production mode,
maintenance window, operator confirmation, and writer quiescence; durable
backup/rollback owner; reparse/provider checks before each mutation; recovery
must never silently delete or publish a root. Legacy migration should be
dev-only or removed from the Production-capable surface.

### Application and startup chains

The HTTP site lifecycle, database upgrade, MESH, AC/base-data, and startup
recovery paths are intentionally separate follow-ups because they have
different domain owners and already contain different transaction/rollback
contracts. The automatic task-event retention path is a destructive DB writer
without a human Production operation gate; its intended status must be
decided explicitly rather than inheriting the P7.1 GC contract by name.

## Path and invocation safety findings

| Pattern | Observed entries | Assessment |
| --- | --- | --- |
| Raw `--data-root` + raw `--site` | MESH rebuild/remap, task rollout, several migration tools | Path calculation is not site authorization; direct follow-up required |
| Direct `--db` | AP schema upgrade, task-result tools | Must resolve canonical site/database before accepting the path |
| Directory glob/discovery | AP `--all-sites`, bootstrap inspection, read-only audits | Production mutation must never expand a directory as an authority source |
| `--all-sites` | AP schema upgrade, dev-only task tools, P7.1 GC | P7-safe meaning is allowlist expansion only; other uses need explicit disposition |
| Environment override | `NETCONSOLE_ALLOW_PRODUCTION_WRITE` | Boolean capability must remain subordinate to canonical site and operation checks |
| Default Production literal | AP upgrade and unified root migration | Dangerous because omission of a path can select Production |
| Reparse/link handling | Strong in P7 helper and some storage services; absent in MESH/AP/task rollout | Every mutation target and ancestor requires fail-closed checks |
| Provider/registry unavailable | Shared boolean paths can continue if marker is present | Provider/registry failure must be a hard refusal before backup or mutation |
| Plan built before authorization | Both MESH CLIs | Plan construction may read data, but apply must rebind scope and revision before any side effect |
| Backup optional or absent | AP `--no-backup`, legacy migration, normal retention/raw deletion | Must be an explicit contract decision, not an accidental capability |

## Backup, rollback, and first-mutation index

| Family | Backup/rollback evidence | First mutation identified |
| --- | --- | --- |
| P7.1 GC | Transaction and authority-index consistency; no business-data backup | First task DB delete after canonical scope, apply, and active-task checks |
| P7.2 compaction | External backup, candidate parity, atomic replace, restore | Candidate creation after auth and stale-source checks; source replacement later |
| AP schema | Optional file backup, no complete rollback owner | Backup creation, or schema `executescript` with `--no-backup` |
| Task rollout/ref-only | CAS or explicit transaction; ref-only has backup/restore | Rollout CAS; ref-only backup |
| MESH rebuild/remap | Domain hash/preflight; no common rollback owner | Repair/rebuild journal/derived/source projection write |
| Storage retirement | Copy/hash then source deletion; copy-back on failure | Retirement destination creation |
| Data-root migration | Staging/hash/SQLite checks and recovery cleanup | Lock/staging creation; later root publication via replace/move |
| HTTP DB upgrade | Journal, backup validation, shadow smoke, rollback | Journal creation; active DB switch only after validation |
| Site retention/lifecycle/import | Scan token, active-task gate, staging/trash/backup varies by operation | Report/staging/trash or archive creation |
| Startup recovery | Persisted journal/locks and controlled moves | Recovery journal update or controlled artifact move |
| Auto task-event retention | External owner protection and DB operation; no backup | First batch deletion of terminal task events |

## Explicit exclusions and read-only paths

These paths were scanned and are not counted as Production authoritative write
entries under this audit:

| Path/family | Reason for exclusion | Status |
| --- | --- | --- |
| `scripts/maintenance/migrate_task_result_blobs.py`, `compact_task_result_storage.py`, `tasks_db_compaction.py` | Apply is restricted to the Development root or an isolated test root | `NOT_PRODUCTION_WRITE` |
| `scripts/maintenance/upgrade_task_cleanup_schema.py` | Current fixed `D:\NetConsoleData` target is explicitly rejected; guard should not be treated as a future canonical authority | `NOT_PRODUCTION_WRITE` |
| `scripts/backfill_ap_optical_treatment_events.py` | Requires Development data and rejects Production; copy-only backfill contract | `NOT_PRODUCTION_WRITE` |
| `scripts/maintenance/backfill_trackside_ap_station_identity.py` | Requires an explicit database copy and rejects symlinks; no Production target | `NOT_PRODUCTION_WRITE` |
| `scripts/maintenance/audit_sites.py` and storage/profile/audit scripts | Read business state and may write an audit/report artifact; they do not mutate authoritative DB/site state | `NOT_PRODUCTION_WRITE` |
| `scripts/maintenance/check_desktop_bootstrap.py --repair` | Repairs Electron bootstrap/config outside the Production site data authority; it does not mutate site DB or authoritative site state | `NOT_PRODUCTION_WRITE` |
| `AppCleanupService` automatic log/cache cleanup | Deletes controlled application logs/cache, not Production site DB, schema, registry, or derived business state | `NOT_PRODUCTION_WRITE` |
| Normal task/device/telemetry/base CRUD | Ordinary product operations, not P7 maintenance unless they enter a repair, migration, schema, rollback, or destructive cleanup path | `OUT_OF_SCOPE` |

This exclusion does not authorize Production access. It only prevents a report
file or Development-only tool from inflating the P7 authoritative write count.

## Follow-up plan

| Work item | Scope | Reuse | Required disposition |
| --- | --- | --- | --- |
| P7.3-A | AP schema upgrade CLI | `resolve_production_site_scope`, `resolve_production_database_scope`, P7 maintenance lock/backup patterns | Guard direct DB and allowlist-expanded all-sites before backup or schema mutation; define `--force`/`--no-backup` policy |
| P7.3-B | Task-result rollout and ref-only closure | P7.2 task DB scope, plan digest, stale revision, backup/restore | Canonical site/database authority plus separate operation capability; retain CAS and transaction semantics |
| P7.3-C | MESH parsed repair, identity remap, and HTTP repair/delete | MESH domain hashes/revisions and shared maintenance lock; canonical site resolver | Separate raw/derived/identity/revision permissions; plan rebind and rollback/recovery owner |
| P7.3-D | Storage retirement, unified/legacy migration, site import/migrate/lifecycle | SiteRegistry, staging, package validation, existing rollback journals | Explicit source/target authority, Production mode, maintenance window, backup/rollback, no broad discovery/replacement |
| P7.3-E | HTTP DB/AC/base-data schema and rollback paths | Database upgrade coordinator, feature gates, audit/operation journals | Align active-site routing with canonical Production authority or record a documented normal-product exception |
| P7.3-F | Startup recovery and automatic task-event retention | Existing journal/lock and external-owner protection | Decide whether each is a canonical Production capability or must be disabled/limited; prove fail-closed behavior |

Each follow-up is a separate domain contract. Combining them into a single
boolean `allow production` switch would preserve the current authority mix-up.
No follow-up is implemented by this audit.

## Safety and validation

- `SOURCE_CODE_CHANGED=NO`.
- No database, schema, migration, rollout, MESH rebuild/remap, GC,
  compaction, backup/restore, rollback, file replacement, or Production data
  access was performed.
- The audit branch was created from the refreshed `github/main` baseline shown
  above.
- The repository-wide scan covered `scripts`, `src`, `apps`, `tools`, `tests`,
  `docs`, and `config`, with focused tracing of direct write functions,
  Production flags, `--all-sites`, raw path handling, HTTP routes, startup
  hooks, and existing P7.1/P7.2 guards.
- Validation appropriate to this docs-only audit: repository diff check and
  existing targeted P7 contract tests may be run; product build, renderer
  tests, and Python source lint are not required because no product source or
  tests changed.

## Final disposition

`P7_3_A_PRODUCTION_WRITE_INVENTORY=COMPLETED`

`P7_3_FOLLOWUPS_REQUIRED=P7.3-A,P7.3-B,P7.3-C,P7.3-D,P7.3-E,P7.3-F`

`P7_PRODUCTION_MAINTENANCE_AUDIT=PAUSED_SAFETY_BUG`

`PHASE_B=PAUSED_UNTIL_UNGUARDED_ENTRIES_ARE_GUARDED_AND_VALIDATED`
