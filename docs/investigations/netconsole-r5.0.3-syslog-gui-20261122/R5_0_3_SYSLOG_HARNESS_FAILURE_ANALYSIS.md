# R5.0.3 Syslog Harness Failure Analysis

## Evidence

The four failures were the four tests in `tests/test_ground_unattended_syslog_manual_join.py`: one normal JOIN case and three parameterized unavailable-heartbeat cases. The original failure was raised before the business assertions because the lightweight `_JoinHarness` did not implement the service admission hook `_require_collection_enabled()`.

| # | Scenario | Expected | Actual before fix | Cause | Classification |
|---|---|---|---|---|---|
| 1 | online heartbeat accepts JOIN | task id and audit entry | `AttributeError: '_JoinHarness' object has no attribute '_require_collection_enabled'` | test double omitted admission hook | HARNESS_BUG |
| 2 | offline heartbeat rejected | `MR_NOT_ONLINE` | same `AttributeError` before validation | same harness defect | HARNESS_BUG |
| 3 | stale heartbeat rejected | `MR_HEARTBEAT_NOT_RUNNING` | same `AttributeError` before validation | same harness defect | HARNESS_BUG |
| 4 | paused heartbeat rejected | `MR_HEARTBEAT_NOT_RUNNING` | same `AttributeError` before validation | same harness defect | HARNESS_BUG |

The harness now supplies a no-op `_require_collection_enabled()` that mirrors admission without opening a device session. Product validation and assertions are unchanged. Re-running the original file produced `4 passed`.

## Closure

`HARNESS_ROOT_CAUSES_IDENTIFIED=1` (one shared harness omission affecting four cases); `HARNESS_FAILURES_CLOSED=1`; `PRODUCT_BUG=0` for this failure set. No assertion was removed or weakened.
