# Phase 11.6 回归报告

日期：2026-11-09。

## 本轮实际执行

| 套件 | 结果 |
|---|---|
| pnpm exec vitest run src/components/mesh-analysis/MeshMetricChart.test.ts src/components/mesh-analysis/MeshPhase11Workbench.test.ts | PASS：2 files / 52 tests |
| pnpm exec vitest run src/components/mesh-analysis/meshBusinessMetrics.test.ts src/components/mesh-analysis/meshMonitorTooltip.test.ts src/components/mesh-analysis/meshCharts.mount.test.ts src/components/mesh-analysis/meshChartViewport.test.ts src/components/mesh-analysis/meshLoadingState.test.ts | PASS：5 files / 80 tests |
| .venv/Scripts/python.exe -m pytest tests/test_mesh_business_statistics.py tests/test_mesh_analysis_query_service.py tests/test_mesh_analysis_web_api.py tests/test_mesh_monitor_sampling.py tests/test_mesh_monitor_nearest.py tests/test_mesh_series_semantics.py | PASS：179 passed，3 warnings |
| git diff --check | PASS（仅有行尾转换提示） |
| vue-tsc -b / Vite build | PASS；Vite 保留既有大 chunk warning |

历史可引用但不重新冒充本轮结果的证据：Phase 11.5 Renderer 206 files / 1508 tests、Mesh Python 197 tests、Phase 11.2 真实 Service 只读 JSON、Phase 11.3 Renderer 206 files / 1505 tests。当前工作树另有用户既有 DataRoot 变更，不将其测试结果归入本轮。

## 解释

本轮组件修改只涉及共享 MESH 图表，不改变数据库/API/导出契约。真实 Electron、Excel/WPS、原生 DPI 和长稳测试不属于已执行套件。
