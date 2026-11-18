# Batch and Transaction Analysis

Parsed events, timeline events, position states and raw checkpoints are committed by `commit_wmesh_projection_batch` under `BEGIN IMMEDIATE`. Raw metadata registration is deferred to a worker. Failed projection commits return `False` while the in-memory batch remains pending.

| MR | repeats | SQL average | connections average | rollback total | position P95 average |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 5 | 2,798 | 271 | 0 | 761 ms |
| 100 | 5 | 5,025 | 467 | 0 | 768 ms |
| 200 | 5 | 26,199 | 965 | 38 | 2,241 ms |
| 400 | 5 | 536,364 | 3,411 | 811 | 39,009 ms |

At 400 MR SQL and latency varied widely (314,812-811,771 statements). A phase-separated run found 161 `ValueError: ground unattended raw file not found` commit failures and 161 rollbacks; the runtime leaves the batch pending and retries it. This is a concrete metadata ordering/retry amplification path, not a stable capacity result.

Status: `ISSUE_FOUND`.
