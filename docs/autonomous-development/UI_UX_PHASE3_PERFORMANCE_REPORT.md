# Phase 3 性能记录

同机同 HZL9 回放副本，源码 Electron，采样窗口约 650 ms。每页重复 5 次。导航计时到两帧完成，不表示网络读完。P95 使用最近秩，5 个样本时等于最大值。首次页进入和后四次可从原始样本区分。操作期间没有源码热更新的轮次用于比较，整轮仍受其他独立验收进程负载影响。

| 指标 | 前 | 后 |
| --- | --- | --- |
| 首页导航 P50 / P95 / 最大 | 17 / 21 / 21 ms | 18 / 20 / 20 ms |
| 首页业务请求 | 每次 5 个 | 每次 4 个。折叠的兼容性信息首次按需加载 |
| 设备管理 P50 / P95 / 最大 | 57 / 335 / 335 ms | 51 / 54 / 54 ms。后测已预热，不能归因于源码优化 |
| 日志纯筛选 CPU，80,000 行固定夹具，5 次最小值 | 364.5 ms | 64.5 ms |
| HZL10 首次交互 | Ground 初始化阶段 30 秒超时 | 一次就绪观测 5.78 秒，采集关闭且只读 |

SQL 按 task_id 查询在两线路均命中主键索引 `sqlite_autoindex_task_snapshots_1`。采样只涵盖 SQL 盘点，表级 COUNT 与时间范围统计不纳入应用首屏。HZL10 的 Ground 常规 Ping 行数与时间范围查询本次约 142 ms，MESH 约 829 ms。阶段保留现有数据库索引。重复冷启动、内存/CPU 长测和更大负载尚未达到完整验收口径。

[首页前测](../../../reports/tests/legacy-ui-ux-phase3/hz9-home-before.json) · [台账前测](../../../reports/tests/legacy-ui-ux-phase3/hz9-before.json) · [十二页后测](../../../reports/tests/legacy-ui-ux-phase3/hz9-after.json) · [采样脚本](../../../reports/tests/legacy-ui-ux-phase3/profile.cjs) · [SQL](../../../reports/tests/legacy-ui-ux-phase3/sql-inventory.txt)
