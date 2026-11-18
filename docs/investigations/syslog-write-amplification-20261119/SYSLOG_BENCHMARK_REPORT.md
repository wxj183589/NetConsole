# Syslog Benchmark Report

Method: isolated SQLite and synthetic inventory under `temp/analysis/syslog-write-amplification-20261119/`; existing UDP loopback harness; 50/100/200/400 MR, five repeats; two synthetic IPs per MR; exact duplicate payload pair per MR. SQL was traced by operation, table, normalized template, connection and transaction prefix.

| MR | sent | received | parsed | dropped | SQL avg | SQL min-max | position P95 avg | rollbacks |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 100 | 100 | 100 | 0 | 2,798 | 2,776-2,830 | 761 ms | 0 |
| 100 | 200 | 200 | 200 | 0 | 5,025 | 4,986-5,046 | 768 ms | 0 |
| 200 | 400 | 400 | 400 | 0 | 26,199 | 20,518-31,582 | 2,241 ms | 38 |
| 400 | 800 | 800 | 800 | 0 | 536,364 | 314,812-811,771 | 39,009 ms | 811 |

The earlier fresh untargeted 400 MR run measured 237,818 SQL statements; it is retained separately. The detailed run is authoritative for template classification. Application integrity passed in the loopback runs, but real UDP loss, crash recovery and device behavior were not tested.

Related targeted tests: `33 passed` (`tests/test_ground_unattended_syslog_v2_stress.py`, `tests/test_udp_syslog_reliable_spool.py`); Ruff and py_compile passed. Full suites were not run.
