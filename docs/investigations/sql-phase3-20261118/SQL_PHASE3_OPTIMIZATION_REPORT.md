# SQL Phase 3 优化报告

## 实施内容

1. `AcRepository.list_fit_ap_radio_details_for_keys()` 使用 AC/AP 复合身份批量读取，400 对身份分批以保持 SQLite 参数上限安全。
2. AC/FIT-AP 列表页、全量详情、当前页详情和导出路径复用批量 details/radio 结果，不再逐 AP 建立连接。
3. Mesh-Link identity batch 读取同时接受 canonical MAC 和 vehicle MAC key，避免每条 Link 回退到单条 identity 查询。
4. Mesh-Link 历史页一次加载页面所需 snapshots 和 link rows，并复用设备、AP、identity、ARP 解析上下文。
5. 增加 AC/FIT-AP 批量读取、连接上界和 Ground ARP 单连接投影回归测试。

## 性能结果摘要

数据来自 Workspace 外的合成 SQLite 夹具，完整结果见 `SQL_PHASE3_PERFORMANCE_COMPARISON.json`。

| 场景                        | baseline SQL P50 | optimized SQL P50 | baseline connections P50 | optimized connections P50 |
|-----------------------------|-----------------:|------------------:|-------------------------:|--------------------------:|
| AC/FIT-AP 100 AP            |              309 |                22 |                      103 |                         5 |
| AC/FIT-AP 500 AP            |             1509 |                23 |                      503 |                         5 |
| AC/FIT-AP 1000 AP           |             3009 |                24 |                     1003 |                         5 |
| Mesh-Link 50 MR / 100 Link  |              884 |                27 |                      197 |                         6 |
| Mesh-Link 100 MR / 200 Link |             1784 |                27 |                      397 |                         6 |
| Mesh-Link 200 MR / 400 Link |             3584 |                27 |                      797 |                         6 |
| ARP 50 MR / 100 IP          |             1200 |                 6 |                      150 |                         1 |
| ARP 100 MR / 200 IP         |             2400 |                 6 |                      300 |                         1 |
| ARP 200 MR / 400 IP         |             4800 |                 6 |                      600 |                         1 |

baseline 与 optimized 使用相同的请求入口和 DTO 响应；baseline 仅关闭 identity batch 以复现修复前的逐 Link identity 回退。optimized 是连续读取结果，不代表磁盘冷启动。

## Schema / 索引

新增索引：0。现有 AC/FIT-AP 与 Ground ARP 复合索引命中；Mesh 的 snapshot link 表扫描记录在 Query Plan
中，作为后续有真实数据证据时再评估的剩余事项。
