# R2.3 Position Engine 报告

日期：2026-11-10。结论：确定性位置归并 **PASS**；真实设备身份与长时一致性 **PARTIAL**。

## 规则

`PositionEngine` 只将精确 AP 身份（`PHYSICAL_AP`/`RADIO_BSSID`）写入当前位置。它按有效 Event Time、同时间的 receive sequence 和设备标识处理事件；可信设备时间下使用稳定 dedup key，只有 Receive Time 的重复在短窗口内去重。每个 MR 保存最多 256 个近期 dedup key，随当前投影恢复，避免“重复 A→正常 B→再次到达重复 A”造成回切。

- `MESH_LINKUP`/`MESH_ACTIVELINK_SWITCH`：更新当前 AP，并将原当前 AP保存为上一个 AP。
- `MESH_LINKDOWN`：保留最后已知 AP，状态变为 `DISCONNECTED`，不虚构未知 AP。
- 未识别、歧义、缺少身份或不完整事件：保留当前 AP，状态标记为 `STALE/UNRESOLVED`。
- 重复只增加 duplicate count；旧事件只增加 out-of-order count，不回写新状态。
- 每个有效切换仍保留结构化事件和时间轴；批处理只合并位置当前态提交。

## 自动化证据

`tests/test_ground_unattended_position_engine.py` 通过 6 项测试，覆盖 A→B→A 的 current/previous、重复事件、旧事件、未知/断开事件、跨中间事件重复和状态恢复。`tests/test_ground_unattended_syslog_position_latency.py` 在临时 SQLite Repository 中验证位置状态、阶段时间、批量提交、结构化去重和健康指标。

## 持久化边界

新增 `ground_unattended_syslog_position_states` 是兼容的 `CREATE TABLE IF NOT EXISTS` 增量表，保存当前投影及最近一次位置事件的时间/质量/来源/计数；原始事件和历史切换不由该表替代。位置状态、结构化 WMESH 事件、timeline 和 raw checkpoint 由 Repository 的同一批次提交。

## 未验收项

未使用真实脱敏设备流做跨时钟乱序样本，未验证真实 AP identity revision 变化、跨 Backend 进程恢复和长时位置准确率。上述自动化结果不能替代现场验收。
