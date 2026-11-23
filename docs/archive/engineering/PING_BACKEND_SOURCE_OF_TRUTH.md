# Ping Backend Source of Truth

## 事实源

统一实现位于：

`src/netconsole/services/ground_unattended/ping_business.py`

该模块不依赖 Renderer、Electron 或持久化层，提供：

- `normalize_status`：原始状态别名归一；
- `classify_status`：逐包业务状态；
- `classify_heartbeat_status`：Heartbeat 可达性状态；
- `point_values`：图表和 DTO 所需的派生字段；
- `natural_second_loss_buckets`：自然秒分桶、去重和丢包率；
- `selected_statistics`：Quick Ping 页级统计。

## API 契约

`GET /ground-unattended/ping-series` 和增量接口返回的每个 `points[]` 包含 `normalized_status`、`status`、`heartbeat_status`、`loss_percent` 和 `rtt_display_ms`，并在 `second_loss_buckets[]` 返回自然秒统计。

`GET /ground-unattended/quick-ping/{run_id}/samples` 返回同样的投影样本，以及 `statistics` 和 `second_loss_buckets`。原始字段（`ok`、`rtt_ms`、时间戳和身份字段）保留用于兼容和审计，但 Renderer 不再据此重建业务状态。

时间戳以 ISO-8601 为输入并按 UTC 解释；自然秒桶为半开区间。无有效时间的记录不进入统计。未知状态不计入成功或丢包，但计入总数和 `ping_unknown`。

## 接入位置

`GroundUnattendedApplicationService` 在 `ping_series`、`ping_series_incremental`、`ping_samples` 和 `quick_ping_samples` 的 DTO 出口调用该模块。这样长 Ping、Quick Ping、历史回放和图表共享同一套分类和统计规则。

Renderer 只消费派生字段，状态文案/颜色和 ECharts 坐标属于展示层，不改变业务事实。
