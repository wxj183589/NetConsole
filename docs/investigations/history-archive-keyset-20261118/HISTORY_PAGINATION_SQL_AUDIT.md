# History Pagination SQL Audit

Date: 2026-11-18
Scope: NetConsole legacy, Ground unattended history archive only.

## Call path

- API: `src/netconsole/backend/api/ground_unattended_router.py`, `history()` (`GET /api/rail-transit/ground-unattended/history`). It accepts the existing filters, `page`, `page_size` (1..500), `sort_order`, plus the new optional `cursor`.
- Application service: `src/netconsole/services/ground_unattended/application_service.py`, `history()`; it enforces the requested site and forwards the query unchanged.
- Query service: `src/netconsole/services/ground_unattended/history_query.py`, `GroundHistoryQueryService.query()`.
- Sources: `_plan()` builds one `UNION ALL` branch per available allowlisted table: runs, train_runs, ping_summaries, heartbeat_states, quick_ping_runs, raw_files, wmesh_events, ac_snapshots, deep_operations, and events.
- Detail reads: `_items()` groups returned rows by source table and performs one `rowid IN (...)` read per source table.
- Export: `iter_export_rows()` reads the same filtered union in the same global order inside one read snapshot.

## Baseline SQL

The baseline page query was:

```sql
SELECT * FROM (<source UNION ALL>)
ORDER BY julianday(ts) DESC|ASC,
         data_type, source_table, source_identity
LIMIT ? OFFSET ?;
```

The count is a `SUM` over per-source `COUNT(*)` branches. Every branch contains `site_id=?`; optional time, type, identity and event filters are applied before the union. The previous implementation did not include a final physical row tie-breaker.

## Findings

- Deep pages pay for scanning and globally sorting all preceding rows.
- The union-level order produces `USE TEMP B-TREE FOR ORDER BY` in the synthetic plans.
- Existing source indexes help the per-table site lookup but cannot remove the global union sort without a schema/index redesign.
- Existing exports and the page path already use one read connection and batched detail reads; this task does not repeat or replace that Phase 4 work.
- Source timestamps can collide, so a timestamp-only cursor is insufficient. The implementation retains the legacy logical keys and adds `source_rowid ASC` as the final deterministic tie-breaker.

Evidence: `D:\study\NetConsole-Workspace\temp\analysis\history-archive-keyset-20261118\metrics.json` and the focused history query tests.
