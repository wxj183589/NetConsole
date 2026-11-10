# Phase 11.9 第七轮：第六轮请求归因

## 结论

第六轮的 94 条 MESH HTTP 不是 94 次缓存内重复查询。原始 request ledger 中包含首次加载、页面重入、后台 overview 刷新、显式页面/详情请求和被 transition 取消的请求。

| 分类 | 请求数 | HTTP 200 | FAILED | SQL | 证据 |
|---|---:|---:|---:|---:|---|
| 首次必要加载 | 6 | 6 | 0 | 5 | ledger id 261,263,264,265,266,267；overview、session、无范围 build-order、business-summary、范围 build-order、raw links |
| 区间变化/transition 取消 | 10 | 0 | 10 | 0 | ledger id 281–290；links/build-order 交替，记录为 FAILED/`net::ERR_ABORTED`，没有成功 SQL |
| 显式详情、分页、AP/路径/事件页面 | 7 | 4 | 3 | 0 | ledger id 293–299；nearest、AP statistics、links page、active path、switches、artifacts、parse issues |
| 第二次冷/重入加载 | 5 | 5 | 0 | 4 | ledger id 562–566；session、无范围 build-order、business-summary、范围 build-order、raw links |
| 后台 overview 刷新 | 65 | 65 | 0 | 0 | 66 条 overview 200 中去除首次加载 ledger id 261 后的其余记录 |
| 重入后的 parse-issues 刷新 | 1 | 1 | 0 | 0 | ledger id 579 |
| **合计** | **94** | **81** | **13** | **9** | 与第六轮原始证据一致 |

## SQL 的请求级来源

第六轮 ledger 对每个请求保存了 SQL 次数和 HTTP 查询参数，但没有保存后端逐条 SQL 的 `sql_query_ranges`；因此下表不把 HTTP 时间范围冒充成 SQL 绑定范围。第七轮已在 raw links DTO 和 renderer trace 中补齐精确 SQL 范围字段。

| ledger id | operation id | route | query kind | HTTP 范围/参数 | SQL | 归因 |
|---:|---|---|---|---|---:|---|
| 265 | `mesh-op-mwa03ncw-1` | `business-summary` | `business_statistics` | `exclude_depot=true`, `exclude_parking=true` | 1 | 首次业务汇总 |
| 266 | `mesh-op-mwa03shm-2` | `active-build-order` | `active_build_order` | `18:37:06.381–18:42:06.381`, radio 1, ACTIVE, exact AP | 1 | 首次主链路范围查询 |
| 267 | `mesh-op-mwa03shn-5` | `links` | `raw_samples` | `18:37:06.381–18:42:06.381`, `raw_samples=true`, `include_context=true` | 3 | 首次原始采样：计数、可见目标行、boundary context |
| 565 | `mesh-op-mwa0646e-2` | `active-build-order` | `active_build_order` | `18:37:06.381–18:42:06.381`, radio 1, ACTIVE, exact AP | 1 | 第二次冷/重入主链路范围查询 |
| 566 | `mesh-op-mwa0646f-5` | `links` | `raw_samples` | `18:37:06.381–18:42:06.381`, `raw_samples=true`, `include_context=true` | 3 | 第二次冷/重入原始采样 |

9 条 SQL 的精确总和为 `1 + 1 + 3 + 1 + 3 = 9`。没有 FAILED 请求被改写成成功，也没有 FAILED 请求贡献 SQL。

## 操作归因

- 首次进入主链路：首次 page/raw cache miss 和一个 raw gap，必要加载对应 ledger 261–267。
- 第一次区间扩大、滚轮扩大/缩小和部分指标滚轮：触发未覆盖区间规划，同时 transition 请求被新窗口取消；ledger 281–290 的失败是取消，不是缓存命中成功后重复查询。
- 已经完整覆盖的 13 个图表滚轮、tooltip、Shift 固定、Ctrl 浏览、Esc、已命中的历史/建链页和页面重入：第六轮 action ledger 记录新增数据请求 `0/0`；第七轮改为低层实际 fetch trace 后再次验证热缓存数据请求仍为 `0/0`。
- 最近采样/右侧详情：只有 raw 缺失或 fallback 时才走 nearest/context_focus；第六轮的显式 detail/AP 页面请求属于未缓存页面或取消请求，不计入热缓存零查询集合。
- AP/Radio、报告、事件、路径等页面：是独立页面数据身份或独立 page cache，不等于已完整 raw cache 内的 chart 查询。
- overview 的 65 条额外 200：是工作台会话概览刷新，SQL=0；保留在全运行统计，不伪装成 chart cache hit。

## 第七轮热缓存差值

真实 Electron 中先等待初始化结束并记录 trace，再执行 5 次 `链路明细 → 主链路监控` 重入/滚动循环。循环前后 renderer raw counter 均为 raw HTTP=1、SQL=3、cache hits=8、gap queries=1；底层 MESH trace 由 9 条增加到 10 条，但唯一新增是未预加载的 `/sessions/.../links?page=1&page_size=100&sort_order=asc` 页面请求，SQL=0。

因此满足热缓存前提的 chart/tooltip/详情复用动作的真实增量为：

```text
MESH raw/data HTTP = 0
MESH raw/data SQL  = 0
```

上述 links page 请求单独归为“未缓存分页加载”，不强行计入热缓存零查询集合。
