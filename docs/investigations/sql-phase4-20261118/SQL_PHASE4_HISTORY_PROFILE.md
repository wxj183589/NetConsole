# SQL Phase 4 History Profile

## Baseline finding

The read-only history service planned a separate `COUNT(*)` for every available source and then fetched each page item with an individual `SELECT * ... WHERE rowid=? AND site_id=?`. Export repeated the item lookup for every row.

## Change

- Combine source counts through one `SELECT COALESCE(SUM(item_count), 0) FROM (...)` query.
- Group page/export rows by fixed source table and fetch details once per source with `rowid IN (...)`.
- Keep the source whitelist and site predicate in both the union query and detail query.
- Preserve JSON detail projection, pagination ordering, export snapshot and missing-row behavior.

## Post-change evidence

On 620 synthetic timeline rows, page size 100:

- total: 620; page items: 100;
- one combined count query;
- one detail batch query for the source table;
- no per-row `WHERE rowid=?` detail query;
- repeated warm wall samples: 1.93–2.82 ms after the first read (5.72 ms cold).

The regression test uses `sqlite3.Connection.set_trace_callback`, asserts the batch shape and checks that only the requested site is returned.

Final gate refresh: the batch implementation is included in PR #122 HEAD `8c1aed0184`; no schema or API change was introduced.
