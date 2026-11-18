# NetConsole SQL Phase 4 Audit

## Scope

- Branch: `codex-A/sql-phase4-deep-read-20261118`
- Scope: Mesh-Link, dynamic Heartbeat, history archive paging/statistics, and remaining clear read-side N+1.
- Data boundary: synthetic SQLite fixtures only. No production or real development database was opened.
- Safety: `PRODUCTION_DATA_MODIFIED=0`, `DATABASES_REMOVED=0`, `DEV_REAL_DATA_MODIFIED=0`.

## Findings

| Area | Finding | Action |
| --- | --- | --- |
| Mesh-Link | Phase 3 already batches current-link peer identity and bounded snapshot reads. Synthetic scale profile stays approximately constant at 27 SQL / 6 connections while rows scale. | No speculative cache or duplicate refactor added. Existing site and freshness contracts remain covered by Mesh tests. |
| Dynamic Heartbeat | Inventory, snapshots, ARP projection, Mesh page and loss interval reads are bounded shared reads. SQL count grows only with bounded page/metadata work, not one query per MR. | No cache added; revision, site, stop and dynamic-target semantics are preserved. |
| History archive | `_plan()` issued one count per source and `_item()` issued one detail query per result row. | Batch detail reads by source table with `rowid IN (...)`; combine source counts with one `SUM` over a `UNION ALL`. |

## Architecture and compatibility

- History source table names remain fixed `_SOURCES` whitelist values.
- Every detail batch retains `site_id=?` and the original page row identities.
- Public `query()` and `iter_export_rows()` result shapes are unchanged.
- No schema, index, version, API, or production-data change was made.
- Change Impact audit classified the modified history service/test paths as L2; Mesh and Heartbeat were consumer-audited because their shared read behavior was profiled.

## Evidence

- Baseline synthetic profile: `temp/analysis/sql-phase4-profile-20261118-a.json` (kept outside Git).
- Heartbeat synthetic profile: `temp/analysis/sql-phase4-heartbeat-profile-20261118-a.json` (kept outside Git).
- Post-change trace regression is in `tests/test_ground_unattended_history_query.py`.

## Final gate refresh (2026-11-18)

- PR #122 latest HEAD: `8c1aed0184981b2f65763af1f057c835306bb38f`.
- CI Run `44255040507`: six checks PASS; Python Required Check remained IN_PROGRESS at this inspection.
- Latest Codex Review covered `8c1aed0184` and reported no major issues.
- Current gate status: `PARTIAL_SQL_PHASE4` pending Python completion.
