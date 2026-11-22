# R5.0.4 Targeted Test Report

Renderer command:

```text
pnpm exec vitest run src/components/ground-unattended/GroundHistoryPlayback.test.ts src/components/ground-unattended/mrMonitoringChartOptions.test.ts src/components/ground-unattended/quickPingChartOptions.test.ts src/components/ground-unattended/quickPingReplay.test.ts src/components/ground-unattended/MrMonitoringDrawer.test.ts src/views/rail-transit/GroundUnattendedView.test.ts src/views/rail-transit/GroundUnattendedView.behavior.test.ts
```

Result: `7 files passed, 70 tests passed`.

Additional backend safety regression (no backend code changed): `44 passed, 1 warning` across timeline, Quick Ping, and history query tests. The warning is the existing Starlette/httpx deprecation.

`pnpm run build` in `apps/desktop_renderer` passed (`vue-tsc` + Vite). `pnpm run typecheck` in `apps/desktop_electron` passed. Full repository tests were not run.

`TARGETED_TESTS=PASS`; `RENDERER_BUILD=PASS`; `ELECTRON_TYPECHECK=PASS`; `FULL_TEST_SUITE=NOT_RUN`.
