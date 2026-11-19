# Isolated Syslog benchmark comparison

Method: existing `scripts/dev/syslog_loopback_profile_20261116.py`, synthetic inventory, isolated SQLite and local UDP loopback under Workspace `temp/analysis/syslog-phase5-fix-20261119/accepted-1` through `accepted-5`. Each run sends two payloads per MR (one exact duplicate pair), with two synthetic inventory IPs per MR. Five runs per 50/100/200/400 MR scale. The full-connection SQLite trace is enabled and Repository transaction observability is off for this comparison. Historical before values come from audit commit `3c7cdd6d` and its five-repeat report; they were not rerun against the final code. The audit used the same loopback harness and host class, but elapsed environmental conditions can differ.

| MR / synthetic IPs | SQL before avg | SQL after avg | After range | After median | After SQL/event | After position P50/P95 avg (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 / 100 | 2,798 | 2,761 | 2,736-2,784 | 2,760 | 27.61 | 759 / 762 |
| 100 / 200 | 5,025 | 4,958 | 4,890-5,006 | 4,982 | 24.79 | 772 / 777 |
| 200 / 400 | 26,199 | 9,540 | 9,514-9,558 | 9,546 | 23.85 | 736 / 744 |
| 400 / 800 | 536,364 | 19,215 | 19,097-19,316 | 19,226 | 24.02 | 1,770 / 2,148 |

At 400 MR, the final full-trace average by SQL prefix is SELECT `3,008`, INSERT `3,675`, UPDATE `1,269`, COMMIT `1,211`; UPSERT is a subset of INSERT. Five runs total: `4,000 received = 4,000 raw lines = 4,000 projected event rows`, `0 dropped`, `0 missing-file errors`, `0 projection exceptions`, `0 SQLite lock errors`, `0 rollbacks`, `0 failed stops`. The historical five 400 MR runs had 811 rollbacks in total; one phase-separated run had 161 missing-file ValueErrors and 161 rollbacks. Thus the measured race-error count after the fix is zero in this workload, not a claim about all deployments.

Historical single detailed 400 MR trace: UPDATE `37,367`, COMMIT `1,211`. Final five-run averages: UPDATE `1,269`, COMMIT `1,211`. The UPDATE figures have different aggregation (one historical run versus current average), but show the removed retry amplification. COMMIT did **not** decrease materially; no extra batching benefit is claimed. Historical 400 MR position P95 average was `39,009 ms`, versus current `2,148 ms`.

| MR | Queue wait P95 avg (ms) | Raw registration P95 avg (ms) | Projection P95 avg (ms) | Maximum memory queue depth |
| ---: | ---: | ---: | ---: | ---: |
| 50 | 110 | 11 | 19 | 98 |
| 100 | 354 | 13 | 95 | 197 |
| 200 | 478 | 12 | 468 | 256 |
| 400 | 1,371 | 13 | 834 | 256 |

Queue capacity in this harness is 256; overflow is spooled. The earlier audit did not record queue wait P95, so no before/after queue-latency improvement is claimed. Projection P95 includes waiting for Raw registration; position P95 includes the live path through commit. The 400 MR SQL total is about 96.4% below the historical mean, primarily because the old retry storm is absent, not because raw evidence or events were dropped.

A separate `observed-400` run with Repository transaction observability enabled recorded `800 received/raw/events`, `0 dropped`, `0 failures`, `0 blocked checkpoints`, `0 rollbacks`, `1,210 transaction commits`, `1,771 write connections`, transaction P50 `4.10 ms`, P95 `14.30 ms`, P99 `43.40 ms`. Its Repository `sql_total=9,113` excludes read-only/other connections and cannot be compared with the full trace above. Observability is off in normal production mode.

Real network UDP packet loss, external senders, long-run traffic, process kill and hardware failure were not measured. The isolated fixtures remain in the Workspace analysis container for audit; no real business database was opened.
