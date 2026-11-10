# MESH 全工作台缓存消费者覆盖

日期：2026-11-10
状态：代码路径与定向测试通过；真实 Electron 业务页面仍为待验收。

| 消费者 | 当前路径 | 命中行为/安全边界 |
|---|---|---|
| RSSI、Busy、Counter、Retry、Error、GARP、MulJoin 指标 | `loadMetric()` → `loadRawSamples()` → `deriveMeshRawSamples()` | 共享 raw facts；只在 response complete 且未降采样时推进 coverage |
| AP 历史表 | `loadHistory()` → shared raw cache | 与 AP、Radio、role、zero、时间 scope 隔离；context 只用于派生 |
| 时间定位/nearest | `locateTime()` 读取 `completeIndex` 或 raw cache 后本地 `nearest()` | complete index/raw 命中不发 nearest HTTP；fallback 仅在 raw 未覆盖/错误时使用 |
| 建链顺序/Build Order | `loadRecords()` 使用有界 `MeshWindowPageCache` | page cache 支持完整第一页派生更小窗口；请求去重 |
| 右侧 build/detail | `selectBuild()` 先查 exact raw cache | 命中后本地派生并选择；未命中才发一条 traced detail query |
| AP 统计 | `loadAps()` 使用 role/radio/page/scope key | 专用 aggregate cache；LRU 上限 32，不把 partial raw rows 冒充 AP aggregate |
| Business Summary | Service `business_statistics` cache | signature 绑定 DB、rules、scope；命中 SQL=0；大结果不长期保留 |
| Parse issues | 独立请求和生命周期 | 不混入 raw facts，取消和错误状态独立处理 |

缓存版本明确区分：原始事实为 `mesh-raw-v1`，派生结果为 `mesh-derived-v1`。raw cache 的 key 包含 source、radio、peer、establish time 等链路身份，不以 timestamp 或 AP 名称模糊合并；visible row 优先于同 key 的 context row。

明确不做的事情：AP aggregate 不从不完整/降采样 raw cache 推断；旧后端或 raw metadata 缺失时保留受控 legacy fallback；生产构建不发送开发 trace 参数。
