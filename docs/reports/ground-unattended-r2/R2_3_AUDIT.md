# R2.3 Syslog 位置链路实施前后审计

日期：2026-11-10。Agent：codex-A。整体 **PARTIAL**。本报告只覆盖本轮 Syslog 位置延迟与准确性补充，不把现场设备、长稳或 GUI 视觉验收写成已完成。

## 审计结论

现有链路已经具备 UDP Receiver、Raw Writer、受管 spool、Parser、WMESH 结构化事件和 `/health`；缺口集中在“事件时间到位置可读”的显式阶段观测、按 MR 的乱序/重复归并、位置当前态持久化以及 UI 新鲜度表达。本轮已补齐这些代码边界：

| 要求 | 当前结果 | 证据/边界 |
| --- | --- | --- |
| 持续接收、Raw 优先、批量投影 | PASS（代码/定向测试） | `syslog_runtime.py` 的有界队列、raw-first spool、批量 flush；未做生产吞吐容量结论 |
| 五个处理时间点和 UI 可用时间 | PASS（隔离测试） | event/receive/raw persist/parse/commit 字段贯穿事件、位置状态、DTO；UI 时间为响应投影可用时间 |
| 同 MR 按有效事件时间处理 | PASS（纯逻辑测试） | `position_engine.py` 使用事件时间和 receive sequence，旧事件拒绝覆盖 |
| 重复不重复切换、历史不丢失 | PASS（纯逻辑测试） | dedup key、duplicate/out-of-order 计数和事件/时间轴保留 |
| 未识别/不完整事件不清空位置 | PASS（纯逻辑测试） | 位置状态保留已有 AP，状态转为 `STALE/UNRESOLVED` |
| AC 延迟快照不覆盖较新 Syslog | PARTIAL | endpoint enrichment 优先精确 Syslog 投影；缺少完整 AC 延迟注入集成测试 |
| 正常负载 P95/P99 与 30 秒目标 | NOT_RUN | 本轮没有持续正常负载或突发负载测量，不能宣称 SLA 通过 |
| 现场设备、Backend 重启、长稳、GUI | NOT_RUN | 见对应专项报告 |

## 主要修改面

- `src/netconsole/services/ground_unattended/position_engine.py`：位置归并、去重、乱序和身份门槛。
- `src/netconsole/services/ground_unattended/syslog_runtime.py`：阶段时间、位置批处理、积压和分位数健康指标。
- `src/netconsole/repositories/ground_unattended_repository.py`：兼容新增 `ground_unattended_syslog_position_states` 表及同事务 upsert/query。
- `src/netconsole/services/ground_unattended/application_service.py`、API/Renderer DTO：当前/上一个 AP、来源、状态、新鲜度、延迟和 UI 可用时间。

## 风险边界

设备没有可信 Event Time 时，系统使用 Receive Time 并标记 `RECEIVE_TIME_ONLY`，不伪造设备事件发生时间。Raw Persist Time 记录在 Raw Writer 写入边界前，尚未定义为 `fsync` 完成时间；该语义需在性能验收中继续明确。自动化使用临时数据库和脱敏/合成事件，不读取真实业务数据。
