# MESH Phase 11.9 第四轮最终报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
实现提交：`67059ab9`
变更级别：L3（共享 Renderer 原始缓存、公共 DTO/API、动态指标路径）
最终状态：`PHASE_11_9_FOURTH_ROUND=PARTIAL`

## 1. 交付结论

本轮完成了 raw sample 统一缓存、毫秒闭区间缺口规划器到真实 HTTP/SQL 的接入、窗口起点 predecessor context、跨 lane 的 counter/continuity 派生，以及指标/历史/时间定位/右侧详情对共享 raw cache 的复用。

自动化 MESH 回归和真实宁波地铁12号线 raw Router/SQLite 验证通过；真实两段与一次性窗口的 raw 记录数量、边界 context、顺序和身份一致。由于真实 Electron 工作台、真实 Renderer 派生字段逐条对照、冷/热缓存全链路、Heap/长稳和 GUI 未执行，本轮不能标记 PASS。

## 2. 主要修改文件

- `apps/desktop_renderer/src/components/mesh-analysis/meshRawSampleCache.ts`：raw scope、sample/lane identity、coverage、context、LRU、counter/continuity 派生。
- `apps/desktop_renderer/src/components/mesh-analysis/MeshPhase11Workbench.vue`：指标、历史、时间定位共享 raw cache；gap 请求、in-flight 去重、取消和旧后端 request-local fallback。
- `apps/desktop_renderer/src/components/mesh-analysis/meshCompleteMetricCache.ts`：导出既有 `Interval`，由 raw cache 复用既有 gap planner。
- `src/netconsole/services/rail_transit/mesh_analysis_query_service.py`：raw SQL、截断完整性、批量 predecessor、版本/上下文/SQL trace DTO。
- `src/netconsole/backend/api/mesh_analysis_router.py`、`src/netconsole/models/api/mesh_analysis.py`、`apps/desktop_renderer/src/types/meshAnalysis.ts`：API/DTO 合同。
- `apps/desktop_renderer/src/components/mesh-analysis/*.test.ts`、`tests/test_mesh_raw_sample_query.py`：Renderer 与真实 FastAPI/SQLite fixture 测试。
- `docs/reports/mesh-phase11-9/`：本报告及第四轮差距、缓存、连续性、分段、真实数据、HTTP/SQL、性能、测试和剩余问题报告。

## 3. 关键函数与数据流

```text
Workbench
  -> meshRawScopeKey / MeshRawSampleCache.missing
  -> meshMissingIntervals（既有毫秒闭区间 planner）
  -> listMeshLinks(raw_samples=true, include_context=true)
  -> SQL 目标区间 + predecessor context
  -> raw version/completeness/downsampled 校验
  -> sample key 去重、lane 排序
  -> deriveMeshRawSamples（previous/delta/rate/gap/role）
  -> 指标图表、历史、时间定位、右侧详情
```

关键函数：`meshRawScopeKey()`、`meshRawSampleKey()`、`meshRawLaneKey()`、`MeshRawSampleCache.missing/put/all/visible()`、`deriveMeshRawSamples()`、`loadRawInterval()`、`loadRawSamples()`、`MeshAnalysisQueryService.list_link_details()`、`_raw_context_rows()`。

raw sample 与 derived metric 版本分别为 `mesh-raw-v1` 和 `mesh-derived-v1`。完整、非降采样 raw 响应才推进 coverage；context 不显示、不计数、不推进 coverage；取消、失败、截断和版本不匹配不污染缓存。

## 4. 验收矩阵

| 验收项 | 本轮结论 | 证据/限制 |
|---|---|---|
| 原始采样统一缓存、raw/derived 分离 | PASS（代码/fixture） | raw cache 与派生复制计算、版本和 coverage 规则 |
| 跨区间 counter previous/delta/rate | PASS（fixture）；真实 derived PENDING | context fixture 与 4 条 lane 断言通过；未在真实 Electron 逐字段对照 |
| ACTIVE/STANDBY、lane continuity | PASS（fixture/真实 raw 角色保留）；真实 derived PENDING | lane identity 含 source/radio/peer/establish/peer radio；真实窗口角色未合并 |
| 缺口 planner 接入真实 HTTP/SQL | PASS_WITH_LIMITATIONS | raw gap 请求、真实 Router/Service、SQL count 通过；未做真实浏览器网络抓包 |
| 多区间精准补齐 | PASS（fixture/真实两段） | 5.001–9.999 gap 与真实 20 秒两段对照；未覆盖所有逆序/重叠组合 |
| 指标/历史/时间定位/右侧详情共享 | PASS_WITH_LIMITATIONS | 主工作台非 zero-link 路径共享；include_zero、AP、build order 等保留独立查询 |
| 真实 HTTP/SQL 统计 | PASS_WITH_LIMITATIONS | 最小 FastAPI app 返回 raw/metric/nearest SQL count；不是全应用 profiler |
| 宁波地铁12号线真实验证 | PASS_WITH_LIMITATIONS | 只读真实 SQLite/Router；未启动完整 Electron |
| 一次性与分段业务字段完全一致 | PENDING | raw record 对照和 fixture 派生对照通过；真实 Renderer derived 逐条对照未执行 |
| 性能/Heap/长稳/GUI | PENDING | 有 Service raw 时间和 SQL 计数；没有 Electron/Heap/100 操作/30 分钟证据 |

## 5. 真实数据与性能摘要

数据为 `D:\NetConsoleData-dev` 的宁波地铁12号线、Session `7c7b6df2-e67b-452a-ab1a-91760014501f:1`、`列车03-MR-CW`、Radio 1。parsed `mesh_links=110058`，时间范围 `00:00:32.413–18:01:07.949`。

- 20 秒 raw：61 个可见目标、64 items、3 context、SQL 3、约 33.54 ms。
- 两段 raw：31+30 个可见目标；items 34+33；各有 3 context；均 complete=true、SQL 3。
- 一次性 20 秒：61 个可见目标、64 items、3 context、SQL 3、HTTP query duration 30.40 ms。
- 5 分钟 raw：905 个目标、complete=true、SQL 3、约 65.99 ms。
- 1 小时 raw：10820 个目标、complete=true、SQL 3、约 660.3 ms。
- metric counter 20 秒：61 个目标、SQL 2、Service 约 31.52 ms。
- nearest 20 秒：1 条、SQL 5、约 600.99 ms；包含既有 raw gz/zero-link 工作，不代表图表绘制时间。

完整可见 id 与两段可见 id 串联一致，真实分段 raw 重复 0、遗漏 0；前端 fixture 的 counter tuple 也与一次性派生结果一致。

## 6. 数据安全

本轮未访问 `D:\NetConsoleData`，未连接现场设备，未修改 schema、raw 日志或设备配置，未复制完整真实 Site。catalog、index DB、parsed 主 DB、parsed WAL、raw gz 的内容 SHA 前后一致；parsed SHM 内容 SHA 一致但 mtime 漂移，已原样记录在 `REAL_DATA_VALIDATION.md`，不宣称所有文件系统元数据零变化。

## 7. 未完成与下一步

剩余重点为：在受控只读 Electron 中采集同一真实窗口的一次性/两段/三段/逆序 derived JSON，逐字段比较 counter、rate、gap、ACTIVE/STANDBY 和 nearest；补全工作台 HTTP/SQL trace、JS Heap、100 次操作和长稳；评估 active scope pin/refcount；再决定是否关闭第四轮。

产品本轮不 Push、不 Merge、不 Release；DevStatus 将单独本地提交，保留现有并行任务 dirty 状态。
