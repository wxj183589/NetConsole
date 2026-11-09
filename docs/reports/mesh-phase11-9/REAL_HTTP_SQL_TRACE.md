# 真实 HTTP / SQL trace 证据

日期：2026-11-10

## Backend trace contract

开发/测试请求可附加 `mesh_trace=true` 和 `mesh_operation_id`。Router 将 operation 传到 Service，Service/Repository 在只读 SQLite 连接上计数 `SELECT`/`WITH`，DTO 回传 `query_kind`、`query_id`、`operation_id`、`query_duration_ms`、`sql_query_count`。生产 Renderer 不发送这些参数，避免把诊断开销带入正式运行。

真实宁波12号线最小 Router/Service/SQLite 链路结果：

| 查询 | query kind | SQL | 结果 |
|---|---|---:|---|
| raw 20 秒第一段 | `raw_samples` | 3 | 31 可见 + 3 context，complete=true |
| raw 20 秒第二段 | `raw_samples` | 3 | 30 可见 + 3 context，complete=true |
| raw 20 秒完整 | `raw_samples` | 3 | 61 可见 + 3 context，complete=true |
| raw+zero 完整 | `raw_samples` | 3 | total=62，zero=1 |
| business summary after AP statistics | `business_statistics` | 0 | Service cache hit |

每条真实 raw 响应的 SQL 计数来自实际 read-only SQLite trace callback，不是 mock 计数。真实数据路径是 `D:\NetConsoleData-dev`；没有复制整个 Site 或 Production。

## Renderer trace ledger

`meshQueryTrace` 记录 bounded 的 `interaction → cache → http → sql/result/error` 事件，并把真实 DTO 的 SQL 元数据回写到 ledger。默认上限 2048 事件，开发/测试启用，打包生产 no-op。Workbench 覆盖 raw interval、history、metric、summary、AP、build order、detail、parse issues。

## 尚未完成

本轮没有在真实 Electron 中加载真实宁波12号线并完成从导航、滚轮、AP、历史、Build Order 到详情的完整端到端 ledger 导出，因此“全工作台真实 HTTP=0/SQL=0”仍为 `PENDING`；已完成的是真实后端 trace、代码消费者覆盖和 mock workbench 100 次门禁。
