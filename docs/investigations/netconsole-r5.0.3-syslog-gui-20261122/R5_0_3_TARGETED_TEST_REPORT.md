# R5.0.3 Targeted Test Report

## Python

Command: `python -m pytest -q tests/test_ground_unattended_syslog_manual_join.py tests/test_ground_unattended_position_projection.py tests/test_ground_unattended_ac_reconciliation.py tests/test_ground_unattended_monitoring.py tests/test_ground_unattended_quick_ping.py tests/test_ground_unattended_quick_ping_ip_exclusivity.py tests/test_ground_unattended_timeline_v2.py`

Result: `68 passed, 1 warning` (Starlette/httpx deprecation warning).

The wider preceding R5.0.3 targeted Python suite was recorded as `204 passed`.

## Renderer

The six Ground Unattended/Heartbeat/Quick Ping/Syslog presentation test files passed: `92 passed`.

## Build

`pnpm run build` in `apps/desktop_renderer` passed (`vue-tsc` and Vite build). Vite emitted only the existing large-chunk advisory.

`PYTHON_TARGETED_TESTS=PASS`; `RENDERER_TARGETED_TESTS=PASS`; `ELECTRON_BUILD=PASS (runtime startup/build evidence)`; `FULL_TEST_SUITE=NOT_RUN`.
