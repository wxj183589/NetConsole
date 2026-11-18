# Syslog Phase 5 implementation acceptance

Project: NetConsole legacy v1.5.15. Base main: `f6b1498c85cc7ed42cae74f690720a83a01d5d6f`. Audit evidence: `3c7cdd6d121704580bda8a96637b34394ef358e3`. Implementation branch: `codex-A/syslog-write-amplification-fix-20261119`. PR: [#124](https://github.com/wxj183589/NetConsole/pull/124). The exact final HEAD and CI status must be checked from that PR after this review fix is pushed; this document does not imply CI passed before it runs.

The Raw File registration/Checkpoint race is fixed by a per-file metadata completion barrier before the projection transaction. Raw writer file-table/handle operations are serialized across writer and projection threads. Identical checkpoint status skips an otherwise unnecessary UPDATE. The Repository gains optional bounded transaction/SQL observability, and receiver health gains Raw/Projection/queue timings and counters. No schema/index/API/Raw contract/version change was made.

Final isolated five-repeat load: 400 MR / 800 synthetic IPs, `4,000 received = 4,000 raw = 4,000 projected`, `0 dropped`, `0 missing`, `0 projection failures`, `0 rollbacks`, `0 SQLite lock errors`, `0 failed stops`. SQL full-trace average fell from historical `536,364` to `19,215`; UPDATE from historical single-run `37,367` to current five-run average `1,269`. COMMIT remained about `1,211` per run. Queue wait P95 averaged `1,371 ms`; Raw registration P95 `13 ms`; Projection P95 `834 ms`; position P95 `2,148 ms`. The separate observed 400 MR run measured transaction P95 `14.30 ms` using a narrower Repository-only trace. Historical 161 missing-file errors were not reproduced after the fix in these isolated runs.

Failure and rollback behavior: pending registration blocks the checkpoint before SQL; a true missing file still fails explicitly; transaction failure rolls back and retains the batch; metadata failure remains visible for stop/restart recovery. Existing bounded replay and stop/restart tests passed. Actual process kill, external UDP loss, concurrent live Heartbeat/Quick Ping/Supervisor/Job Center/Mesh-Link, field devices and long-duration stability remain `NOT_VERIFIED`; they are not part of this isolated acceptance. The task did not run full suites or a Release Gate.

Codex Review on initial PR HEAD `99c26d0797514eb8f050c99a0707dc00e28fc039` found a permanent-block risk after metadata error-map overflow. The follow-up adds read-only Site/Run/file-status reconciliation before clearing the overflow fence, with OPEN/CLOSED recovery tests. Review and CI for the follow-up HEAD are pending.

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
REAL_DEVICES_ACCESSED=0
FULL_TESTS=NOT_RUN
CI_STATUS=PENDING_FOLLOW_UP_HEAD
FINAL_STATUS=PARTIAL_SYSLOG_WRITE_OPTIMIZATION
```

The final status remains partial until the final HEAD has passing required checks. No PR merge is authorized by this task.
