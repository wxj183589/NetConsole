# Recent/detail 查询闭环修复

日期：2026-11-10

## 修复内容

`MeshPhase11Workbench.vue` 的 `selectBuild()` 现在按以下顺序处理：

1. 用选中建链记录构造精确 AP、Radio、role、zero 和毫秒窗口；
2. 先检查同 scope raw cache 是否完整且没有 legacy fallback 标记；
3. 命中时从缓存 raw rows 调用实际 `deriveMeshRawSamples()`，按 `record_id`/AP/role 选择详情，不调用 nearest API；
4. 未命中时才发送一条 `page_size=1` 的 detail 查询，并记录为 `build_detail` fallback。

时间定位 `locateTime()` 同样先使用完整 raw index/cache，本地 `nearest()` 命中时不访问后端。仅在 raw 不可用、scope 被 fallback 标记或派生失败时保留 nearest 兼容路径。

## 证据

- Workbench 100 次同窗口交互测试：warm 后 links/builds 调用数不再增加，HTTP=0，SQL=0，cache hit≥100。
- 时间定位与 exact context 既有测试仍通过；include_zero 的 LinkCnt=0 路径不再绕回 metric_group。
- 真实宁波12号线 raw 查询 `SQL=3`，分段/完整结果稳定；真实 Electron 本轮只验证隔离启动和窗口几何，未宣称真实数据 GUI 点击验收。

## 边界

`listMeshActiveBuildOrder` 仍是 Build Order 的独立分页消费者；AP aggregate 仍是独立统计消费者。两者的缓存命中不会把不完整 raw facts 解释为聚合事实。
