# Syslog SQL Write Classification

| Class | Path | Assessment |
| --- | --- | --- |
| Raw INSERT/UPSERT | `upsert_raw_file` registry | Necessary metadata; one update per file close is expected. |
| WMESH INSERT | `_insert_wmesh_events` | Necessary once per accepted event; repeated attempts are amplification. |
| Timeline INSERT | `_insert_timeline_events` | Necessary history; already uses `executemany`. |
| Position UPSERT | `_upsert_syslog_position_states` | Necessary for changed current state; no explicit field-aware no-op gate. |
| Raw checkpoint UPDATE | `commit_wmesh_projection_batch` | Necessary replay progress. |
| Boot/identity UPDATE | `touch_boot_syslog` | Conditional projection, currently separately transacted per verified event. |
| Dedup SELECT | `_insert_wmesh_events` | Necessary idempotency checks, expensive when a batch is retried. |

One detailed 400 MR repeat sent 800 messages and completed with `received=800`, `written=800`, `parsed=800`, `dropped=0`, but traced 452,982 SQL statements: WMESH SELECT 156,503; WMESH INSERT 78,251; timeline INSERT 78,251; position-state INSERT 44,249; raw-file SELECT 38,778; raw-file UPDATE 37,361; ROLLBACK 146.

78,251 structured inserts cannot be necessary for 800 messages. A phase-separated 400 MR run traced 616,149 pipeline SQL statements and captured 161 matching `ValueError: ground unattended raw file not found` commit failures and 161 rollbacks. The batch is retried after the failure, so the repeated SELECT/INSERT work is projection retry amplification, not 78,251 final rows.

Status: `ISSUE_FOUND`.
