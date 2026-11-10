# Heap 与性能验收

日期：2026-11-10  
结论：`PARTIAL`

## 已有边界与实测观察

| 项 | 边界/观测 |
|---|---|
| raw facts cache | 最多 8 scopes、总计最多 100000 samples，按 last-used 淘汰 |
| AP page cache | 最多 32 个 scope/page，按 Map LRU 淘汰 |
| history/build page cache | `MeshWindowPageCache` 最多 32 pages，支持完整第一页派生子窗口 |
| complete metric cache | 最多 16 entries |
| trace ledger | 最多 2048 events |
| selection cache | 最多 128 entries |
| 宁波12号线真实 raw 20 秒 | 首次约 33.55 ms / 10.79 ms / 29.74 ms（两个分段与完整） |
| 既有真实 5 分钟观察 | 约 65.99 ms，905 条目标 raw，SQL=3 |
| 既有真实 1 小时观察 | 约 660.3 ms，10820 条目标 raw，SQL=3 |

上述时间是 Service/SQLite 只读观察，不是 Electron paint、Canvas、ECharts 或用户端端到端 SLA。

## 未完成门禁

本轮未取得 Chrome DevTools/真实 Electron JS Heap 前后快照，没有完成 1/4/8 小时 soak、GC 后 retained objects、Canvas/ECharts 重绘、CPU profile 或 300 秒→240 秒滚轮实机请求曲线。因此不得宣称内存长期稳定、无泄漏或性能门禁全部通过。
