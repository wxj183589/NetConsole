# Targeted validation

Branch: `codex-A/syslog-write-amplification-fix-20261119`, based on `github/main=f6b1498c85cc7ed42cae74f690720a83a01d5d6f`. Tests use the project virtual environment and Workspace `test-data/NetConsole/syslog-phase5-20261119` for temporary files.

| Gate | Result |
| --- | --- |
| Nine AC/Ground Raw/Syslog test modules | 141 passed, 1 third-party StarletteDeprecationWarning |
| Ground health DTO regression | Existing failing AC health test and new internal-metric boundary test PASS |
| Added delayed/failed metadata, concurrent rotation and no-op checkpoint tests | PASS |
| 50/100/200/400 MR loopback, five repeats each | PASS; metrics in benchmark report |
| Direct SQL architecture audit | PASS, 0 findings, 0 waived |
| Ruff (four changed Python files) | PASS |
| `py_compile` (four changed Python files) | PASS |
| Workspace Layout (Workspace + repository) | PASS |
| `git diff --check` | PASS |
| Full Python/Renderer/Electron/Release Gate | NOT RUN, by task scope |

The third-party warning comes from FastAPI TestClient importing deprecated Starlette/httpx compatibility. It is not a test failure and this task does not change dependencies.

The final code tests specifically assert checkpoint retention through delayed registration, failed registration and forced Repository rollback. Existing suites cover UDP overflow spool, clean stop/restart, bounded replay, raw lifecycle and position ordering. No tests were removed, skipped or weakened.

GitHub CI Run `44380612477` on prior HEAD `35efac96` failed the Python regression with `1 failed, 5610 passed, 4 skipped`: `test_ac_health_marks_backoff_degraded_and_keeps_failed_poller` raised 19 Pydantic `extra_forbidden` errors. The receiver's new internal metrics were passed through `GroundUnattendedApplicationService.health()` into the strict public `GroundHealthDTO`. The service now passes only declared DTO fields. The public API model and internal metric snapshot remain unchanged. This is a confirmed regression from this task, fixed in the follow-up HEAD; its CI result must be checked separately.
