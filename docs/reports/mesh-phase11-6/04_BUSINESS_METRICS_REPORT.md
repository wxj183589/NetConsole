# Phase 11.6 业务指标报告

## 指标闭环

| 指标 | Parser/SQLite | Query Service/API | Renderer/ECharts | 当前结论 |
|---|---|---|---|---|
| RSSI | local_rssi_db/peer_rssi_db，保留 null/0 事实 | metric_group=rssi，主/备语义由 link_role 返回 | RSSI 图、本端/对端颜色、缺口不连线 | PASS_WITH_LIMITATIONS |
| Noise | local_noise_dbm/peer_noise_dbm | metric_group=noise | 双端 Noise 图和详情 | PASS_WITH_LIMITATIONS |
| Rate | local_rate_raw/peer_rate_raw，不猜单位 | metric_group=rate | 双端 Rate 图和详情 | PASS_WITH_LIMITATIONS |
| CPU | local_cpu_percent/peer_cpu_percent | metric_group=cpu | 双端 CPU 图和详情 | PASS_WITH_LIMITATIONS |
| Memory | local_mem_percent/peer_mem_percent | metric_group=memory | 双端 Memory 图和详情 | PASS_WITH_LIMITATIONS |
| TxBusy/RxBusy | local/peer_tx_busy、local/peer_rx_busy | metric_group=busy，两个子图复用 | TxBusy、RxBusy 独立双端图 | PASS_WITH_LIMITATIONS |
| TxDesFreeCnt | local/peer_tx_des_free_cnt | metric_group=tx_des_free_cnt | 双端计数图和详情 | PASS_WITH_LIMITATIONS |
| Tx/Rx | 原始累计计数 | counters 增量/秒速率 | Tx/Rx 独立双端图、详情显示 current/previous/delta/interval/rate | PASS_WITH_LIMITATIONS |
| Retry/Err | 原始累计计数 | counters 增量，回退/缺失返回 null/status | Retry、Err 独立图 | PASS_WITH_LIMITATIONS |
| GARP/MulJoin | 原始累计计数 | counters 增量/秒速率 | 两张独立图，颜色稳定 | PASS_WITH_LIMITATIONS |

PASS_WITH_LIMITATIONS 表示当前代码与自动化/真实只读 Service 证据一致，但未完成真实 Electron 与完整现场日志验收，不代表指标缺失。

## 数据语义

- 对端缺失保持 null/暂无数据，不从本端补值。
- 计数器首点、间断、回退和 reset 按 Query Service 状态处理；前端只展示，不重算。
- LinkCnt=0 的业务折线值为 null，原始记录仍可由 zero query/诊断路径追溯。
- Rate 保留原始值，不从数值猜单位；RSSI 0 保留在 raw/parsed，业务质量统计排除。
- local/peer 颜色来自固定 side palette，不随排序改变。

## 仍需实测

1. 真实运行态 API 连接和完整 Electron 多图加载。
2. 大型真实日志首次绘制和单图慢查询隔离。
3. 真实 AP/Radio 多站点数据的视觉/业务复核。
4. 历史报告与诊断 Excel 在真实 Excel/WPS 中打开和保存。
