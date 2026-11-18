# History Query Plan Analysis

## Baseline plan

The synthetic plans at every measured depth reported:

```text
SEARCH s USING INDEX idx_ground_events_timeline (site_id=?)
USE TEMP B-TREE FOR ORDER BY
```

The source index is used for the site restriction, but the `UNION ALL` result still needs a temporary global sort. OFFSET then discards the preceding sorted rows.

## Cursor plan

The cursor plan reported the same source index and `USE TEMP B-TREE FOR ORDER BY`. The optimization therefore does not claim to remove the temporary sort. Its measured gain comes from applying the lexicographic continuation predicate before `LIMIT`, so the query does not materialize and discard an ever-growing prefix of the ordered result.

The production query order is now:

```sql
CASE WHEN julianday(ts) IS NULL THEN <null-rank> ELSE <non-null-rank> END ASC,
julianday(ts) ASC|DESC,
data_type ASC, source_table ASC, source_identity ASC, source_rowid ASC
```

The null rank preserves SQLite's previous null placement for both directions. No index or schema was added. Existing source indexes remain unchanged.

## SQL count and connection profile

The synthetic comparison recorded four SQL statements and one read connection for both modes: the combined count, the page query, and grouped detail reads. The count is intentionally retained for the existing `total` contract. Cursor requests fetch `page_size + 1` rows to calculate `has_more`, then project only the requested page.

## Decision

The current plan is acceptable for a compatible additive cursor mode. A future schema/index optimization may target the union sort, but it requires separate authorization and compatibility analysis.
