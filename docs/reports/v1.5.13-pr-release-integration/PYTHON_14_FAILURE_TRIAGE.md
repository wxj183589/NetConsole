# Python historical 14-failure triage

任务输入中的历史 Python 失败清单逐项复核，最终处理链如下：

1. 恢复 Windows fixed-drive compatibility seam，修正 isolated test storage snapshot 契约。
2. 修正 FleetPing sample counter 发布时序，避免 callback 尚未消费时读到提前计数。
3. 修正设备时间领先 host 时的位置延迟统计边界。
4. 将 Syslog spool flush 改为批量 flush，并节流磁盘 guard 扫描。
5. 将 pending receive order 从每次 O(N) 扫描改为 deque 加惰性清理，解决 CI stress timeout。
6. 补齐 portable data-root fallback、MESH raw 全角色/零行契约及 LinkCnt=0 baseline 清理。

本轮本地证据：

- 目标间歇性心跳测试单独 30 次通过。
- 等价 heartbeat fixture 50 次通过。
- `tests/test_ground_unattended_ac_resident.py`：36 passed。
- Syslog 相关回归：33 passed；stress 组合：2 passed。
- 最终 GitHub attempt 3：`5665 passed, 4 skipped`，Python gate PASS。

CI attempt 2 的单次失败已作为真实偶发时序证据保留，不作为最终成功依据；attempt 3 完整重跑通过。
