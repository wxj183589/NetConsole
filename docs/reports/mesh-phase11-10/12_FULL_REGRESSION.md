# 全量与定向回归

| 类别 | 命令 / 范围 | 结果 |
| --- | --- | --- |
| Renderer 定向 | meshBusinessMetrics、MeshMetricChart、meshCharts.mount、MeshPhase11Workbench | 4 files / 106 tests passed |
| Renderer 全量 | apps/desktop_renderer pnpm exec vitest run | 211 files / 1541 tests passed，45.72 s |
| Python MESH / AC-MESH | test_mesh_*.py、test_ac_mesh_link_*.py、test_mr_mesh_identity_shadow.py | 491 passed，3 warnings |
| Renderer build | apps/desktop_renderer pnpm run build | PASS；3445 modules；仅 chunk >500 KB warning |
| Electron main build | apps/desktop_electron pnpm run build:main | PASS；typecheck + build |
| Ruff | MESH 相关 src / tests | PASS；All checks passed |
| compileall | src/netconsole | PASS |
| diff check | git diff --check | PASS；仅 LF→CRLF 提示 |
| Workspace layout | python -m scripts.check_workspace_layout | BLOCKED baseline：既有顶层 docs |

Renderer 全量测试中出现过既有测试后台对 localhost:3000 的 ECONNREFUSED
console 输出，但测试结果为 1541 passed，没有失败项；未把 console 噪声写成测试失败。

本轮新增自动化回归：

- MeshMetricChart：ECharts 无 point data 时使用 native dblclick fallback。
- meshBusinessMetrics：视觉有界采样仍保留 endpoints、continuity boundary 和 gap。

没有运行与本轮无关的完整发布打包，也没有触碰 fping。
