# 真实 HTTP / SQL 追踪报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`

## 追踪边界

后端 `MeshLinkPageDTO` 新增 `query_kind`、`sql_query_count`、raw 完整性、版本、context 数量和 coverage 时间元数据。raw route 的 SQL 计数在 `MeshAnalysisQueryService.list_link_details()` 内按目标查询、总数/截断判断、context 批量查询和必要投影计数；它是该 Service 路径的可审计计数，不是整个 Electron 进程所有 SQLite 调用的全局 profiler。

前端每个缺口对应一个 `raw_samples=true` HTTP；结果中的 SQL 计数累加到工作台调试计数器。缓存命中不会发 raw HTTP。由于本轮没有启动真实 Electron，工作台级“冷/热/补两个 gap/右侧详情”的 HTTP 数量没有伪造为已测量值。

## 真实最小 HTTP app 结果

数据为宁波地铁12号线真实 `列车03-MR-CW` parsed DB，使用最小 FastAPI app + 真实 Router/Service/SQLite，所有请求均为只读：

| API/范围 | HTTP | query_kind | 目标 total | items | context | complete | SQL | query duration |
|---|---:|---|---:|---:|---:|---|---:|---:|
| raw `00:05:00.000–00:05:10.000` | 200 | raw_samples | 31 | 34 | 3 | true | 3 | 29.69 ms |
| raw `00:05:10.001–00:05:20.000` | 200 | raw_samples | 30 | 33 | 3 | true | 3 | 9.98 ms |
| raw `00:05:00.000–00:05:20.000` | 200 | raw_samples | 61 | 64 | 3 | true | 3 | 30.40 ms |
| `nearest_time` 20 秒窗口 | 200 | nearest | 1 | 1 | — | — | 5 | 600.99 ms |

nearest 用时包含其既有 raw gz/zero-link 上下文工作，不能当作图表绘制耗时，也不能与 raw SQL 的单次执行时间直接比较。

## Service 级对照

- raw 5 分钟：905 个目标 row，SQL 3。
- raw 20 秒：61 个目标 row、3 个 context，SQL 3。
- raw 1 小时：10820 个目标 row，SQL 3。
- metric counter 20 秒：61 个 row，SQL 2，Service 约 31.52 ms；一次记录的墙钟约 69.76 ms。
- nearest：目标 1 条，手工追踪为 SQL 5；它是兼容/独立 nearest 路径，不应在 raw cache 命中时被工作台正常调用。

## 解释

真实 route 已证明 HTTP 响应携带了真实 SQL 统计，并且分段请求的时间范围确实改变了 SQL 目标窗口；这满足“不能只有 Mock API”的最低闭环。

但本轮尚未完成：

- 真实 Electron 中从冷缓存触发全部可见指标的请求 ID/operation ID 采集。
- 已有前后区间补中间缺口时的实际 HTTP=gap 数量与 SQL 总数。
- 热缓存缩小窗口的 HTTP=0 与 SQL=0 运行态证明。
- AP、Active Build Order、历史分页、建链分页和 nearest 全部接口的统一全局 trace。

因此不能把 `sql_query_count=3` 扩展解释为整页只执行 3 次 SQL，也不能把前端缓存命中推断成数据库绝对没有其他查询。
