# R2.3 最终验收

日期：2026-11-10。Agent：codex-A。总体 **PARTIAL**。

| 验收项 | 状态 | 结论 |
| --- | --- | --- |
| 持续接收、Raw 优先、批量解析/提交 | PASS（代码/定向回归） | 使用既有有界队列、spool 和 Repository 批量事务 |
| Event/Receive/Raw/Parse/Commit/UI 时间链 | PASS（隔离测试） | 阶段字段贯通并可在 health/DTO 读取 |
| 同 MR 顺序、重复、乱序、历史完整 | PASS（纯逻辑/临时库） | PositionEngine 和位置表已接入 |
| AP 身份与未知事件保护 | PASS（隔离测试） | 只接受精确身份，未知/不完整不清空 |
| AC 延迟快照不覆盖 Syslog | PARTIAL | 读取投影已有优先级，缺少延迟 AC 端到端注入 |
| 队列积压、EPS、P95/P99 观测 | PASS（接口字段） | 已有指标；阈值和长期趋势尚未现场验证 |
| 正常负载 P95 ≤10 秒、P99 ≤30 秒 | NOT_VERIFIED | 未执行规定负载的统计验收 |
| 真实设备、故障注入、Backend 重启 | NOT_RUN | 没有现场或破坏性运行数据测试 |
| GUI/长稳 | NOT_RUN | 见专项报告 |

## 数据与分支边界

只使用仓库代码和临时 SQLite/合成事件进行验证；没有读取、复制或修改生产/真实开发数据，也没有操作独立 fping 仓库。当前分支为 `codex-A/global-dataroot-disk-policy`；产品与 DevStatus 的既有 dirty 修改不属于本轮报告范围。

R2.3 的最低交付是可测、可观测、准确性优先的本地位置链路；“正常情况下 30 秒内”仍需下一阶段正常/突发负载和现场证据后再决定是否通过。
