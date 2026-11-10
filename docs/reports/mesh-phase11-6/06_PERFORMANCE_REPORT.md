# Phase 11.6 性能报告

## 已确认

- Query Service 使用窗口、metric_group、分页/预算、LOD 和 downsampled 标志；Workbench 仅加载可见图表并复用 source query。
- 计数器六类指标共享一次 counters 请求，避免为 GARP/MulJoin 重复查询。
- Renderer 图表使用 ECharts finished 边界、shallow/ref 缓存、AbortController 和 generation；resize 不重建实例。
- 历史合成基准已覆盖 50k/200k/500k/1M 规模，百万 payload 和 ZIP64 修复记录在 mesh-analysis-performance-optimization/02_PERFORMANCE_BENCHMARK.md。这些是单轮合成基准，不是现场 SLA。
- Phase 11.2 真实只读服务证据：默认五分钟窗口 465 条原始记录，返回 240 条；数据库和 raw 指纹未变化。

## 未完成性能门

| 门 | 状态 | 原因 |
|---|---|---|
| 慢查询故障注入 | NOT RUN | 未在真实后端运行态注入可控延迟/失败 |
| 30 分钟稳定性 | NOT RUN | 没有 Electron/runtime 长稳窗口 |
| 100 次页面/AP/时间范围切换内存曲线 | NOT RUN | 没有真实 Renderer/Electron 画像 |
| 大型真实日志首次绘制 | NOT RUN | 真实 GUI/runtime 未启动 |
| 原生 Windows 125% DPI 性能 | BLOCKED | 当前环境没有对应 GUI 证据 |

不把历史合成单轮数据改写为本轮长稳 PASS；不复制真实数据根。
