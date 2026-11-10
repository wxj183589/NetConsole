# 计数器跨区间连续性报告

## 实现

关键函数：

- `deriveMeshRawSamples()`：对完整 raw 集按 lane 和时间排序后一次性重建。
- `counterStatus()`：区分 first、valid、reset、missing、invalid_interval。
- `setDelta()`：同步写入十二个累计字段的 delta 字段和 `counter_samples`。

覆盖字段：`local/peer_tx`、`local/peer_rx`、`local/peer_retry`、`local/peer_err`、`local_tx_garp/peer_rx_garp`、`local_tx_mul_join/peer_rx_mul_join`。

## 边界规则

- 分段第二段使用窗口前 predecessor context，不能把第二段第一条当作 first。
- 计数器回退标记 `reset`，delta/rate 为 null。
- LinkCnt=0、role 变化和长时间 gap 不跨边界计算增量。
- rate 使用真实前后采样间隔，不使用固定 1 秒假设。

## 对照证据

`meshRawSampleCache.test.ts` 对同一 4 条序列执行整段和两段+context 计算，record_id、previous、delta、per_second 完全一致。边界 fixture 还验证：正常 delta 为 20、回退为 `reset`/null、role change 为 `link_changed`、长间隔 `monitor_gap_before=true`，且 raw 输入未被修改。

宁波真实数据本轮验证了 raw identity 和前置 context 的可见记录一致性；真实 Renderer 派生计数器尚未在 Electron 中直接绑定该 Authority，因此这里不把 fixture 结果写成真实计数器验收。
