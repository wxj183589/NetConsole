# R2.3 剩余问题

日期：2026-11-10。状态：**PARTIAL**。

1. 建立固定正常负载和突发负载 harness，统计 Event Time→Position Commit/UI Available 的 P50/P95/P99，并验证 P95 ≤10 秒、P99 ≤30 秒；短时单事件测试不能替代。
2. 对 Parser 变慢、Raw Writer 慢写、SQLite 锁、磁盘压力、UDP socket 错误和 Backend 强杀重启做故障注入，确认 raw 留存、spool 有界、恢复不重复切换。
3. 使用真实格式脱敏 Syslog fixture 验证设备 Event Time 可信度、时钟偏差、延迟到达、同时间连续切换和跨 MR 并发；不得在时间缺失时伪造 Event Time。
4. 增加 AC 延迟快照与 Syslog 新位置冲突的端到端对账测试，包括同时间、旧事件、身份 revision 和 AC 未知 AP。
5. 明确 Raw Persist Time 是写入边界还是 `fsync` 完成时间；若需要磁盘确认，应增加独立时间点，不改变原始证据优先策略。
6. 执行 Electron GUI 截图/交互验收和 8/24 小时长稳，观察 stale 标识、增量刷新、内存、磁盘增长和队列趋势。
7. 完成后再更新最终验收和 DevStatus；在此之前不把本地自动化 PASS 表述为真实设备或发布 Gate 通过。
