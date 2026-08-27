# MESH Query Phase2 报告

日期：2026-08-26

## 实施内容

`MeshAnalysisQueryService` 根据请求的 chart resolution 限制 Trackside chart 的 repository source series budget：默认不超过 1,000 points 时使用 128 个 series；更高分辨率请求保留原有 512 上限。响应层原有的降采样和 payload fitting 规则保持不变。

这样避免默认图表先物化数百个最终会被响应 fitter 丢弃的 series，同时保留详细调用者的公共上限语义。

## A/B 证据

在同一宁波 12 号线 DEV MESH 数据和只读查询下：

| repository max_series | 总耗时 | query | 峰值内存 |
| ---: | ---: | ---: | ---: |
| 512（旧路径） | 16,890ms | 16,381ms | 434.04MiB |
| 128（默认实际需求） | 7,500ms | 7,362ms | 165.6MiB |

series 优先级 ID 集合保持一致；返回层仍按既有规则输出 128 series。当前无 tracemalloc 的真实调用为 2,022ms，repository source budget 为 128，最终返回 128 series、3,319 points。

## 兼容性验证

- `max_points=10/1000` -> 128 series budget。
- `max_points=2000/20000` -> 512 series budget。
- MESH 查询服务测试：100 passed。
- 未修改 HistoryStore、MESH identity、原始日志和数据库 schema。
