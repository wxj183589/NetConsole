# Ground Unattended R3 Real-Data Replay Validation

Status: `PASS_WITH_LIMITATIONS` for the read-only service-level replay queries recorded below. Full Electron interaction and the full export matrix remain `NOT VERIFIED` in this validation.

## Data and Method

- HZL9 site: `hzdt-09`, run `ground_20261125_e7c1aa3cdaaa`, 2026-11-25 14:49:04 to 17:48:18 +08:00.
- HZL10 site: `hzl10`, run `ground_20261122_0f7e9d778582`, 2026-11-22 07:00:01 to 23:01:40 +08:00.
- Query code: current branch `GroundHistoryQueryService`, `GroundRawStreamQueryService`, and repository read methods.
- Ground index: the task's isolated HZL9/HZL10 SQL-index candidates under Workspace `test-data/NetConsole`.
- Raw/archive files: the already isolated HZL9/HZL10 DataRoots under Workspace `test-data/NetConsole/real-data-20261125-*`. Candidate index raw-file registrations were resolved to those isolated file trees. HZL9 source and candidate registrations agree on 77 files and 19,015 Syslog records. HZL10 candidate has two additional files for the separately recorded synthetic mixed-query run. The replay filters the selected real run and excludes that synthetic run.
- SQLite connections used `mode=ro` and `PRAGMA query_only=ON`. Candidate database and WAL sizes/timestamps remained unchanged. Read-only SQLite refreshed candidate SHM metadata. No source archive, Production, real development business data, or device configuration was modified.

## Results

| Source | HZL9 | HZL10 |
| --- | ---: | ---: |
| Selected historical run | `ground_20261125_e7c1aa3cdaaa` | `ground_20261122_0f7e9d778582` |
| Timeline first page | 25 rows, has next page; 5-run P50/P95 10.23/11.01 ms | 25 rows, has next page; 5-run P50/P95 98.67/102.02 ms |
| Parsed MESH rows registered for run | 6,818 | 174,277 |
| MESH query sample | 500 rows, 500 confirmed intervals in sample | 500 rows, 500 confirmed intervals in sample |
| Syslog Raw replay | 19,015 records, 25-row page, `ARCHIVED_RAW`, no truncation; 48.95 ms | 259,887 records across 17 one-hour windows, all complete and not truncated; window P50/P95/max 173.40/191.04/197.29 ms |
| Heartbeat replay | 678 real resident samples for one CT MR; all effective; 678 plotted points; repeated query P50/P95 54.61/54.66 ms | 57,430 real resident samples for one CT MR; all effective; 999 bounded chart points; repeated query P50/P95 1,204.69/1,213.82 ms |
| Quick Ping history | 2 actual runs | 0 runs, `NOT AVAILABLE` |

Heartbeat remains the resident raw stream while the selected historical run provides the time context. Its timestamps are filtered to the run window. Chart points are bounded to 1,000 and do not replace the raw sample counts.

HZL10 Syslog replay uses one-hour windows because a whole-run query exceeds the product's bounded file/record scan budget. All 17 windows reported complete results, and their record totals sum to the Ground Raw registry count for the selected run. The service-level replay therefore covered the entire selected run without disabling the bounded-query contract.

## Scope Limits

This validation exercised actual product query services over actual isolated records. It did not launch Electron during this run. It covered timeline first pages, sampled MESH interval projection, selected-run Syslog, and one CT Heartbeat target per line. It did not exercise all 21 HZL10 MRs, every event-type filter, every Quick Ping sample page, or the complete export matrix. Existing prior Electron and CSV evidence remains separate and is not attributed to this run.
