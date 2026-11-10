# MESH Phase 11.9 第五轮测试报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
总体：`PARTIAL`

## 已执行

| 命令/范围 | 结果 |
|---|---|
| `python -m scripts.check_workspace_layout` | PASS；未跟随 Reparse Point |
| `pnpm exec vue-tsc -b --pretty false`（desktop_renderer） | PASS |
| `pnpm exec vitest run src/components/mesh-analysis/MeshPhase11Workbench.test.ts src/components/mesh-analysis/meshRawSampleCache.test.ts` | 2 files / 43 passed |
| `pytest tests/test_mesh_raw_sample_query.py tests/test_mesh_analysis_web_api.py tests/test_mesh_analysis_query_service.py tests/test_mesh_monitor_zero_query.py -q` | 134 passed，2 warnings |
| `pnpm run smoke:dev`（desktop_electron） | 隔离 Electron/Vite/Backend smoke 启停证据 PASS |
| `pnpm run dev:codex -- --isolated-test-data ...` | Backend ready；真实 Electron window rect=1920×1080；手动停止，临时根已清理 |
| 宁波12号线只读 Service/Router/SQLite raw 查询 | full/segmented、include_zero、SQL=3、真实字段级 TS 派生对照 PASS |

## 未执行或未完成

- Python 全量、Renderer 全量、Electron 全量及完整发布/安装门禁；
- 真实 Electron 加载宁波12号线后的完整 MESH 工作台交互、截图和全局 trace 导出；
- JS Heap/Chrome DevTools、Canvas/ECharts profile、1/4/8 小时长稳；
- 逆序、多段、重叠 gap 的真实 GUI 交互统计；
- Excel/WPS、真实设备、现场网络验收。

## 数据边界

真实数据只读于 `D:\NetConsoleData-dev`，未复制完整 Site/数据库；Production `D:\NetConsoleData` 未访问。隔离 Electron 和真实 raw 对照产生的临时证据均已删除，只有本报告和结构化测试结果保留在源码仓库。
