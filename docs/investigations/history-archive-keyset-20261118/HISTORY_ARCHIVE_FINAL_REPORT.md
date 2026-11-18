# History Archive Final Report

Date: 2026-11-18
Branch: `codex-A/history-archive-keyset-20261118`
Base: `52447b70d9061756c128f36670280cd8f20bd309` (`v1.5.15`)
HEAD: `085a7ed1d5cb762bbb7a0701b3afdeb0f08f83a9`
PR: [#123](https://github.com/wxj183589/NetConsole/pull/123), OPEN and MERGEABLE; GitHub checks had not started at report time.

## Outcome

`PASS_HISTORY_ARCHIVE_OPTIMIZATION`

The product keeps the existing OFFSET API and adds an optional cursor continuation path. The cursor uses the existing multi-source global ordering with a deterministic `source_rowid` tie-breaker, validates site and filter context, preserves export ordering, and has focused regression coverage. Deep synthetic pages show the expected reduction in prefix-scan cost.

## Acceptance matrix

| Requirement | Result |
| --- | --- |
| History archive deep pagination | PASS |
| 100k/500k/1m synthetic comparison, five iterations | PASS |
| Stable multi-source ordering | PASS |
| Site isolation | PASS |
| Existing page-number API | PRESERVED |
| Export compatibility | PASS |
| Schema changed | 0 |
| Index added | 0 |
| Frontend behavior | Existing UI unchanged; API/type support added |
| Global cache | 0 |
| Full tests | NOT RUN |

## Performance headline

At 1,000,000 synthetic rows and equivalent page 5,000, OFFSET measured 11,364.972 ms P50 / 11,421.435 ms P95; cursor measured 524.274 ms P50 / 619.276 ms P95. The plan still reports a union-level TEMP B-TREE, so the result is a bounded additive optimization rather than a claim of complete sort elimination.

## Required delivery fields

```text
CURRENT_MAIN=52447b70d9061756c128f36670280cd8f20bd309
BRANCH=codex-A/history-archive-keyset-20261118
PR=https://github.com/wxj183589/NetConsole/pull/123
DATASET_SIZE=100k/500k/1m synthetic rows
OFFSET_P50=11,364.972 ms at 1m/page-5000
OFFSET_P95=11,421.435 ms at 1m/page-5000
CURSOR_P50=524.274 ms at 1m/page-5000
CURSOR_P95=619.276 ms at 1m/page-5000
SQL_COUNT_BEFORE=4
SQL_COUNT_AFTER=4
CONNECTION_BEFORE=1
CONNECTION_AFTER=1
TEMP_B_TREE_BEFORE=YES
TEMP_B_TREE_AFTER=YES (union sort remains)
API_COMPATIBILITY=PRESERVED; optional cursor added
SITE_ISOLATION=PASS
PAGINATION_CONSISTENCY=PASS
EXPORT_COMPATIBILITY=PASS
SCHEMA_CHANGED=0
INDEX_ADDED=0
TARGETED_TESTS=57 passed, 1 warning; Ruff, py_compile, vue-tsc, layout and diff checks PASS
FULL_TESTS=NOT_RUN
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
FINAL_STATUS=PASS_HISTORY_ARCHIVE_OPTIMIZATION
```

## Files changed

- Ground history query, application service, router and DTO;
- Renderer history API/type declarations;
- Focused history query and API tests;
- This six-file investigation report set.

No Syslog, Heartbeat, AC, FIT-AP, Mesh-Link, ARP, Job Center, schema, production data or real development data was changed.

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
```
