# Ground Unattended R2 需求矩阵（当前阶段）

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| SYSLOG_OWNERSHIP | PASS（模拟设备） | Syslog 字段/迁移测试 |
| SYSLOG_EXIT_SAFETY | PASS（模拟设备） | 原有 `CONFIG_PRESENT` 拒绝撤销；ACTIVE 可撤销 |
| SYSLOG_BATCH_CONCURRENCY | PARTIAL | 重叠设备当前拒绝并返回 `SYSLOG_DEVICE_BUSY`；同 MR 排队、原子预留、并发竞态和取消隔离未完成 |
| SYSLOG_RETRY | PARTIAL | 退出失败可保留所有权并重试；批次自动重试未实现 |
| SYSLOG_TASK_PERSISTENCE | NOT_STARTED | 后续 R2.1 |
| HEARTBEAT_RESIDENT | PARTIAL | 上一轮实现存在，R2 常驻重构未完成 |
| HEARTBEAT_RUN_INDEPENDENCE | PARTIAL | 需 Backend 生命周期专项验证 |
| SYSLOG_RECEIVER_INDEPENDENCE | PARTIAL | 当前能力存在，独立生命周期未完成 |
| SYSLOG_RAW_WRITER | NOT_RUN | 未执行本阶段长稳/压力门禁 |
| SYSLOG_PARSER | NOT_RUN | 未执行本阶段故障注入 |
| AC_POLLING | NOT_RUN | 保持既有 60 秒默认值，未在本阶段重跑 |
| AC_MESH_LINK_INDEPENDENCE | NOT_RUN | 保持默认关闭，未在本阶段重跑 |
| COMPONENT_FAULT_ISOLATION | NOT_RUN | 未执行故障注入 |
| PERFORMANCE | NOT_RUN | 未执行 R2 压力测试 |
| REGRESSION | PASS（定向） | 30 Syslog + 55 Ground API/调度 |

真实设备、GUI、长稳和压力项目不得据此标记 PASS。
