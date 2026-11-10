# NetConsole MESH 原始日志分析 Phase 11.9 第七轮最终报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
基线产品提交：`e9ff4275`（第六轮交付 `b6d8b16c`、`e9ff4275`）

## 最终结论

`PHASE_11_9_SEVENTH_ROUND=PARTIAL_WITH_CORE_MESH_ACCEPTANCE`

本轮没有发现已完整缓存范围内的 MESH 数据重复查询。真实 Electron 已严格证明 A+C 的 raw gap 请求只覆盖 B，并完成分段/一次性派生字段对照；ECharts、Canvas、listener、ResizeObserver 的实际生命周期计数也闭环。整体保持 PARTIAL，原因是 Workspace 顶层既有 `docs` blocker、TEST catalog 查询期 metadata 写入风险，以及第七轮未重复完整 30 分钟长稳。

## 五个必须回答的问题

### 1. 第六轮 HTTP 94、SQL 9 来自哪里？

94 条由 6 条首次必要加载、10 条区间 transition 取消、7 条显式详情/分页/AP/路径/事件页面、5 条第二次冷/重入加载、65 条后台 overview 刷新、1 条 parse-issues 刷新组成；HTTP=81 成功、13 FAILED。9 条 SQL 精确来自两轮 business/active-build-order/raw-links：`1+1+3+1+3=9`。逐请求分类和 operation/参数见 `seventh-round/REQUEST_ATTRIBUTION.md`、`seventh-round/HTTP_SQL_TRACE.json`。

### 2. 热缓存范围内真实 Electron 是否还产生 MESH 数据查询？

否。等待初始化完成后执行 5 次工作台重入/滚轮循环，raw counters 前后均为 HTTP=1、SQL=3；实际 hot cached data 增量为 HTTP=0、SQL=0。唯一新增 trace 是未预加载的 links page 分页请求，已单独排除，不是热缓存前提内的操作。

### 3. A+C 是否真的只查询 B？

是。真实 raw HTTP 的 A、C、ABC operation 分别只请求 A、C 未覆盖前缀和 B=`18:33:00.001–18:34:59.999`；ABC SQL ranges 的 target_count/target_rows 均为 B 的 181 条，另有 1 条不可见 boundary context。一次性 full window 为 723 条可见记录；segmented/full 均为 724 raw rows、723 derived rows，逐字段 compare `equal=true`、`firstMismatch=null`。同一 ABC 第二次调用 HTTP=0、SQL=0。

### 4. ECharts 和监听器是否存在生命周期泄漏？

观测范围内没有。13 个图表加载后为 13 实例/13 Canvas/13 wheel/13 dataZoom/13 tooltip/13 ResizeObserver/52 native listeners；离开工作台后全部为 0，累计 init/dispose、mount/unmount 平衡；返回时 lazy 图表按可见数量重新建立，滚动到全部后仍为 13 对 13。真实快照见 `seventh-round/ECHARTS_LIFECYCLE_EVIDENCE.json`。

### 5. 隔离 catalog 为什么变化？

已归因为 `EXPECTED_RUNTIME_WRITE`。TEST runtime 的 `_schedule_catalog_backfill()` 调用 `MeshCatalogIndexService.rebuild_now()`，正常 rebuild 会刷新 `mesh_catalog_index_state.updated_at` 和已有 `mesh_source_fingerprints.updated_at`。session index、lifecycle/events、原始 mesh.sqlite、parsed DB、raw gzip 内容和 schema 均未变化。没有回滚 catalog、删除 WAL/SHM 或恢复 mtime。详见 `seventh-round/CATALOG_CHANGE_ANALYSIS.md`。

## 修改内容

- 在 renderer API client 建立仅 DEV/TEST 的实际 MESH fetch trace，记录 operation、request id、HTTP 参数、SQL count/ranges、raw coverage、取消和 active 请求数。
- 在 raw links DTO 中暴露 `target_count`、`target_rows`、`boundary_context` 的精确 SQL query ranges，供真实 A+C/B 验收使用。
- 修复 `MeshPhase11Workbench.loadMetric()` 命中 metric cache 后仍继续查询 raw/metric source 的重复调用路径；命中后直接渲染并返回。
- 增加 raw cache coverage snapshot、dev-only workbench `set_window`/`raw_samples` 诊断和 direct detail/nearest trace。
- 在既有 `MeshMetricChart` 生命周期位置增加仅 DEV/TEST 的 ECharts、Canvas、listener、ResizeObserver、mount/unmount 计数；不 monkey-patch 全局 API。
- 为 Electron `dev:codex` 增加可选 `NETCONSOLE_DEVTOOLS_PORT`，形成可重复的 CDP 验收入口。
- 增加对应 renderer/Python 回归和本轮 12 份交付报告。

## 主要文件

- `apps/desktop_renderer/src/api/client.ts`
- `apps/desktop_renderer/src/api/meshHttpTrace.ts`
- `apps/desktop_renderer/src/components/mesh-analysis/MeshPhase11Workbench.vue`
- `apps/desktop_renderer/src/components/mesh-analysis/MeshMetricChart.vue`
- `apps/desktop_renderer/src/components/mesh-analysis/meshLifecycleDiagnostics.ts`
- `apps/desktop_renderer/src/components/mesh-analysis/meshRawSampleCache.ts`
- `apps/desktop_electron/scripts/dev.mjs`
- `src/netconsole/models/api/mesh_analysis.py`
- `src/netconsole/services/rail_transit/mesh_analysis_query_service.py`
- `tests/test_mesh_raw_sample_query.py`
- `docs/reports/mesh-phase11-9/seventh-round/`

## 测试与数据影响

- Renderer MESH：33 files / 341 passed。
- Python MESH/AC-MESH/identity/rebuild：495 passed，3 个既有弃用 warning。
- Renderer build、Electron typecheck/main build、Ruff、compileall、`git diff --check`：PASS。
- Workspace full/repo-only：均因既有顶层 `D:\study\NetConsole-Workspace\docs` FAIL，分类见 `WORKSPACE_BASELINE_CHECK.md`。
- 只使用 Workspace 隔离测试根；`D:\NetConsoleData`、`D:\NetConsoleData-dev` 未作为运行时写入目标，未复制整站/整库，未修改 Production、Dev Authority、设备或 `D:\study\fping`。
- 隔离 catalog 的 metadata 时间戳按运行时索引流程变化，已逐表归因；原始 mesh/parsed/raw 内容 SHA/size 保持不变。

## 本地交付与遗留

本轮按要求只做本地产品和 DevStatus 提交，不 Push、Merge 或 Release。产品和 DevStatus 的 commit hash 在本地提交后由交接记录给出。

遗留问题集中在 `seventh-round/REMAINING_ISSUES.md`：既有 Workspace baseline blocker、TEST catalog metadata 写入策略、第七轮未重跑完整 30 分钟长稳，以及真实 Electron 边界矩阵未对每个逆序/多缺口/LRU 场景逐项重跑。不能把本轮结果写成现场设备、Excel/WPS GUI、安装包或最终发布许可通过。
