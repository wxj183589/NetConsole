# SQL Phase 4 Final Report

## Result

`PARTIAL_SQL_PHASE4`

Phase 4 completed the evidence-based history archive read optimization. Mesh-Link and dynamic Heartbeat were profiled and their existing bounded/shared-read implementations were retained; no speculative cache or duplicate refactor was introduced. This report does not claim that every SQL module is fully optimized.

## Scope and changes

- Branch: `codex-A/sql-phase4-deep-read-20261118`
- Modified source: `src/netconsole/services/ground_unattended/history_query.py`
- Regression coverage: `tests/test_ground_unattended_history_query.py`
- History counts are combined and detail rows are fetched per source batch.
- Site isolation, public response shape, pagination and export consistency remain covered.

## Gate results

| Gate | Result |
| --- | --- |
| Mesh profile and consumer tests | PASS |
| Heartbeat profile and consumer tests | PASS |
| History batch regression and archive tests | PASS |
| Targeted suite | `145 passed, 1 warning` |
| Ruff / py_compile / diff check | PASS |
| Workspace and direct-SQL guards | PASS |
| Production data modified | 0 |
| Databases removed | 0 |
| Dev real data modified | 0 |

## Review boundary

No PR or merge was created in this task. Codex review and CI are pending after the feature branch commit/push. Main was not modified.
