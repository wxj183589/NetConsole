# Phase 11.9 第四轮差距矩阵

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
结论：`PHASE_11_9_FOURTH_ROUND=PARTIAL`

| 目标 | 本轮实现 | 证据 | 状态 |
|---|---|---|---|
| 原始采样与派生指标分离 | `mesh-raw-v1` DTO、`MeshRawSampleCache`、`mesh-derived-v1` 派生结果 | raw cache 9 项单测、真实 raw HTTP 响应 | 完成 |
| 毫秒闭区间缺口规划器接入 | 复用 `meshMissingIntervals()`，只为缺失区间发 raw 请求 | 缓存单测、Workbench raw coalescing 单测 | 完成 |
| 跨区间计数器连续性 | 以完整排序 raw 集合重建 12 个累计计数器的 previous/delta/rate | `meshRawSampleCache.test.ts` 分段对照 | 完成（fixture） |
| 跨区间链路连续性 | lane identity、前置 context、role/gap/reset 边界 | raw context 服务单测、真实宁波分段 record_id 对照 | 完成 |
| 真实 HTTP / SQL trace | DTO 返回 `query_kind`、`sql_query_count`、raw 完整性和 context 数量 | 最小 FastAPI 路由 + 宁波开发数据 | 完成（只读路由） |
| 全工作台共享 raw cache | 图表、历史、时间定位共用 `MeshRawSampleCache`；命中时不再 nearest SQL | raw-aware Workbench 单测 | 完成（mock/fixture） |
| 历史 / 建链分页复用 | 保留 `MeshWindowPageCache`，raw 历史页切片后进入既有分页缓存 | Workbench 回归 | 完成（mock/fixture） |
| 宁波地铁12号线真实数据 | 读取开发 Authority，未复制数据；raw、分段、角色和性能均核验 | `REAL_DATA_VALIDATION.md` | 完成（只读） |
| 完整查询与分段查询一致 | 20 秒整段 61 条可见记录；两段 31+30 条，可见 record_id 完全一致 | `FULL_VS_SEGMENTED_COMPARISON.md` | 完成（raw identity） |
| 真实 Electron / Renderer 使用真实 Authority | 本轮没有启动会触碰真实运行目录的完整 Electron acceptance | 未执行，避免触碰真实运行时 WAL/SHM | 未完成 |
| 冷热缓存、100 次交互、真实图表绘制时间 | 未建立长时交互或浏览器绘制基准 | `REMAINING_ISSUES.md` | 未完成 |

本矩阵保留前三轮报告，不覆盖既有结论。未完成项不影响已实现的 raw API 契约，但阻止本轮宣称 PASS。
