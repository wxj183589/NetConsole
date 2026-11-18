# History Cursor Design

## API shape

The existing page-number contract remains the default:

```text
GET /api/rail-transit/ground-unattended/history?page=...&page_size=...
```

An optional opaque `cursor` enables continuation:

```text
GET /api/rail-transit/ground-unattended/history?page_size=100&cursor=<next_cursor>
```

The response keeps `items`, `total`, `page`, `page_size` and `sources`, and adds:

- `has_more`: whether another continuation page exists;
- `next_cursor`: an empty string at the end, otherwise an opaque continuation token.

No frontend page component was changed. The renderer API/type additions are backward-compatible for existing callers.

## Token binding

The token contains a versioned, URL-safe encoded payload plus a digest. It is rejected when malformed, tampered, used for another site, used with another filter set, used with another sort direction, or used with another page size. This prevents a cursor from silently selecting records under changed criteria.

The anchor contains timestamp, data type, source table, source identity and source rowid. The rowid is only a deterministic final tie-breaker; it is not used as a cross-table identity.

## Mixed ordering

Timestamp direction follows `sort_order`; all tie fields remain ascending. The continuation predicate therefore uses `<` for the timestamp in descending mode and `>` in ascending mode, followed by ascending lexicographic tie comparisons. Null timestamp placement is preserved explicitly.

## Mutation behavior

Each request still uses one read snapshot. A record inserted before the current anchor in the selected order is not returned by a later cursor page; a record inserted after the anchor can be returned. Deleting the anchor does not invalidate the token because the predicate is value-based. A changed filter/site/sort/page size rejects the token.

This is the same practical consistency boundary as the existing archive API: it is not a multi-request point-in-time snapshot.

## Compatibility and scope

- Existing OFFSET page jumps, totals, filters, export behavior and site checks remain.
- No global cache was introduced.
- No schema, index, Syslog, Heartbeat, AC, FIT-AP, Mesh-Link, ARP or Job Center code was changed.
