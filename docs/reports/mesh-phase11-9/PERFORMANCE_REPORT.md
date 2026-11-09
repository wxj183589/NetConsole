# 性能报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
状态：后端 raw 查询性能已实测；完整冷/热缓存、Renderer Heap 和长稳仍为 PARTIAL。

## 真实 Service/HTTP 结果

数据为宁波地铁12号线 `列车03-MR-CW`、Radio 1，真实 SQLite 只读查询：

| 场景 | 目标记录 | 返回 items | SQL | Service/query 用时 | 备注 |
|---|---:|---:|---:|---:|---|
| raw 5 分钟 | 905 | 905 | 3 | 65.99 ms | complete=true，context=0 |
| raw 20 秒 | 61 | 64 | 3 | 33.54 ms | context=3，complete=true |
| raw 1 小时 | 10820 | — | 3 | 660.30 ms | complete=true，观察值 |
| metric counter 20 秒 | 61 | 61 | 2 | 31.52 ms | 墙钟记录 69.76 ms |
| nearest 20 秒窗口 | 1 | 1 | 5 | 600.99 ms | 含既有 raw gz/zero-link 工作，不是绘图耗时 |

5 分钟查询的另一条记录墙钟约 66.47 ms；墙钟和 Service 内部耗时的差异保留，不混为同一指标。

## 缓存实现的容量边界

`MeshRawSampleCache` 默认最多 8 个 scope、最多 100000 个 sample，按 `lastUsed` 做 scope 级 LRU；单个 response 的最大请求由 Workbench 设置为 50000 条，后端超过上限标记不完整并拒绝推进 coverage。原始缓存与派生图表缓存分别存在，派生版本变化不会删除原始事实。

这些是实现上限，不是本轮真实 JS Heap 的实测结果。当前实现没有对“正在显示 scope”做 pin/refcount 保护，可能在极端多 scope 场景被 LRU 淘汰；这是剩余风险。

## 未完成的性能维度

没有在真实 Electron 中执行并记录以下项目：

- 冷缓存、第一次热缓存、再次热缓存三轮完整加载。
- 原始合并、派生重建、链路连续性计算的独立耗时分解。
- 真实工作台 JS Heap、Renderer RSS、100 次交互和 30 分钟稳定性。
- 多个不连续 gap 的总耗时与一次性完整查询的端到端比较。
- 真实页面绘图完成时间。HTTP/query duration 不能代替 ECharts render-complete。

因此当前性能结论是：后端 20 秒、5 分钟和 1 小时 raw SQL 路径可运行，SQL 计数稳定为 3；性能门禁和完整工作台端到端 SLA 尚未通过，整体仍为 `PHASE_11_9_FOURTH_ROUND=PARTIAL`。
