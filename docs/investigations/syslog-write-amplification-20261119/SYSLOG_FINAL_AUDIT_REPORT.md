# Syslog Write Amplification Final Audit

Main: `f6b1498c85cc7ed42cae74f690720a83a01d5d6f`; version `v1.5.15`; scope is read-only code audit plus isolated synthetic loopback benchmark. Product business code was not changed.

The historical `186,971` SQL result was not reused. A fresh untargeted run measured `237,818`; detailed five-repeat classification measured 314,812-811,771 SQL per 400 MR repeat. A phase-separated run attributed 616,149 pipeline SQL statements to 161 `ValueError: ground unattended raw file not found` commit failures and 161 rollbacks. The runtime retains the batch and retries it, causing repeated WMESH SELECT/INSERT, timeline INSERT and raw checkpoint work.

One detailed 400 MR repeat classified 452,982 traced statements: `SELECT=195,292`, `INSERT=202,362`, `UPDATE=37,367`, `BEGIN=1,358`, `COMMIT=1,211`, `ROLLBACK=146`. UPSERTs are embedded in INSERT templates (`ON CONFLICT`), so they are not counted as a separate SQLite trace prefix. These are execution attempts, not final row counts.

| Question | Result |
| --- | --- |
| SQL composition | `ISSUE_FOUND`: SELECT/INSERT/UPDATE and retry amplification. |
| Necessary writes | Raw evidence, accepted history, changed position state, checkpoints and required boot state. |
| No-op UPDATE | `ISSUE_FOUND`: no explicit field-aware no-op gate for current/boot projections. |
| Same event repeated | `ISSUE_FOUND`: projection work repeats after failed transactions; raw duplicates remain evidence. |
| State projection amplification | `ISSUE_FOUND`. |
| Independent commits | `ISSUE_FOUND`: 3,030 connections and 1,358 BEGIN in one 400 MR repeat. |
| Queue backlog | `PARTIAL`: bounded loopback queues pass; sustained external wait not verified. |
| UDP loss risk | `NOT_VERIFIED`. |
| Event ordering | `PARTIAL`: sequence and PositionEngine controls exist; real burst not verified. |
| SQLite/concurrency risk | `PARTIAL`: rollback/latency amplification is proven; the primary reproduced error is raw metadata ordering, not a final SQLite lock exception. |
| Data integrity | `PARTIAL`: loopback had zero application drops and clean stop; crash/real network not verified. |

Do not implement broad SQL changes yet. First instrument projection exception class and transaction owner, then run a narrow fix benchmark while preserving raw-first durability, bounded spools, ordering, site isolation and replay.

Validation: detailed 50/100/200/400 MR benchmark, five repeats; synthetic data only; Syslog/spool targeted tests `33 passed`; Ruff PASS; py_compile PASS; Workspace Layout PASS; full suites NOT RUN by scope.

```text
MR_SCALE=50/100/200/400, 5 repeats
EVENTS_RECEIVED=100/200/400/800 per run
EVENTS_PERSISTED=application counters matched received in loopback
EVENTS_DROPPED=0 in loopback
SQL_TOTAL=2,798 avg at 50 MR; 536,364 avg at 400 MR
SELECT_COUNT=195,292 (detailed 400 MR repeat)
INSERT_COUNT=202,362 (detailed 400 MR repeat)
UPDATE_COUNT=37,367 (detailed 400 MR repeat)
UPSERT_COUNT=embedded in INSERT templates
COMMIT_COUNT=1,211 (detailed 400 MR repeat)
CONNECTION_COUNT=3,030 (detailed 400 MR repeat)
QUEUE_MAX_DEPTH=NOT_RECORDED
QUEUE_WAIT_P95=NOT_RECORDED
PERSIST_LATENCY_P95=NOT_RECORDED
DUPLICATE_UPDATE_FOUND=ISSUE_FOUND
NO_OP_UPDATE_FOUND=ISSUE_FOUND
TRANSACTION_AMPLIFICATION=ISSUE_FOUND
STATE_PROJECTION_AMPLIFICATION=ISSUE_FOUND
UDP_LOSS_RISK=NOT_VERIFIED
EVENT_ORDERING=PARTIAL
SQLITE_LOCK_RISK=PARTIAL
DATA_INTEGRITY=PARTIAL
```

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
REAL_DEVICES_ACCESSED=0
FINAL_STATUS=ISSUE_FOUND_SYSLOG_WRITE_AMPLIFICATION
```
