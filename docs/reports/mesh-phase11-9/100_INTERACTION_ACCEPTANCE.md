# 100 次 Workbench 交互缓存验收

日期：2026-11-10  
测试：`apps/desktop_renderer/src/components/mesh-analysis/MeshPhase11Workbench.test.ts`，`keeps one fully cached range at zero HTTP and SQL for 100 workbench interactions`

## 方法

1. 用 complete `mesh-raw-v1` response 预热同一 AP/Radio/ACTIVE/毫秒窗口；
2. 清空 trace ledger；
3. 连续调用 100 次同一 `openContext()`；
4. 统计 API mock 调用、trace HTTP 事件、SQL 计数和 cache hit。

## 结果

| 断言 | 结果 |
|---|---|
| warm 后 links 调用数 | 未增加 |
| warm 后 Build Order 调用数 | 未增加 |
| 100 次新增 HTTP trace | 0 |
| 100 次新增 SQL trace | 0 |
| cache hit | ≥100 |

结论：`PASS（mock workbench）`。该结果证明缓存命中和交互去重逻辑，但不证明真实 Electron/真实数据长稳或 JS Heap 不增长。
