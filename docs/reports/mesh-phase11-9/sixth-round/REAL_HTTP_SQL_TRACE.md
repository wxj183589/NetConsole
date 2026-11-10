# 真实 HTTP / SQL Trace

证据源：`sixth-round-runtime-evidence.json`。统计范围是主 Electron 运行；补充 Electron 运行只用于补拍 08、09 两张截图。

## 总量

- MESH HTTP request records：94。
- HTTP 200：81。
- FAILED：13；其中可见 `net::ERR_ABORTED`，对应 viewport/page transition 中的主动取消或被新窗口请求替换。
- MESH SQL：9。
- 主运行中没有将 FAILED request 改写成成功；这些失败保留在 request ledger。
- stability 每分钟样本均为 `inflight_mesh_requests=0`、`cancelled_trace_events=0`、页面错误 0、console error 0。

## 观测到的 route families

| Route | 用途 | 观测结果 |
|---|---|---|
| `/overview?page=1&page_size=50` | 会话概览/后台刷新 | 多次 200；不计入缓存 chart gate |
| `/sessions/{session}` | 会话详情 | 冷启动 200 |
| `/sessions/{session}/active-build-order` | 主链路/分页 | 冷启动真实返回 `total=8102`、`item_count=100`；区间查询返回 `total=91` |
| `/sessions/{session}/business-summary` | 业务汇总 | 真实调用并带 `mesh_operation_id` / query id |
| `/sessions/{session}/links?...raw_samples=true&include_context=true` | 原始链路及采样 | 首次完整查询 `total=465`、`item_count=466`、`raw_sample_complete=true`、SQL=3 |
| `/sessions/{session}/ap-signal-statistics` | AP/Radio/角色统计 | AP 页面实际显示 853 条记录 |
| `/sessions/{session}/charts/active-path` | 主用路径图表 | 在页面动作中出现 |
| `/sessions/{session}/switch-events` | 切换事件 | 在页面动作中出现 |
| `/sessions/{session}/artifacts` | 报告与来源 | 页面切换中出现 |
| `/sessions/{session}/parse-issues` | 数据告警 | 页面切换中出现 |

## 代表性 SQL 计数

- 冷 reload 的 active-build-order：SQL=1，返回 91 条。
- 冷 reload 的 raw links：SQL=3，返回 465/466 条 raw result。
- cold reload 该阶段合计 SQL=4；warm-1 SQL=0，warm-2 SQL=0。
- raw cache counters 在补充 gap 完成状态为 HTTP=2、SQL=6、cache hits=17、gap queries=2；这包含缺口补取和重新确认，不应误读为缓存命中时新查询为 0。

## 缓存 gate

主运行动作 ledger 中，主链路 nav、两次 wheel、13 个 chart wheel、tooltip、Shift、Ctrl、Esc、详情点击、页面重入等缓存范围动作均记录 `http_requests=0`、`sql_queries=0`。区间扩大操作记录了 raw cache `gap` / page cache `miss`，并出现被取消的 transition request；因此报告同时保留“缓存范围 0/0”和“全运行 94/9”两个不同口径。
