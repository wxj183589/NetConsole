# Ground Unattended R2 实施报告

日期：2026-11-09
分支：`codex-A/global-dataroot-disk-policy`
阶段：R2.1 安全与任务可靠性（部分完成）

## 已实施

- Syslog 配置审计增加 `managed_by_netconsole`、`created_by_netconsole`、目标地址/端口、所有权审计 ID、所有权状态和撤销时间字段。
- 旧数据库通过 additive migration 补齐字段；旧审计记录保持 `UNKNOWN`，不会因 `CONFIG_PRESENT` 自动获得所有权。
- 只有本次实际下发 loghost 命令且复查成功的记录进入 `ACTIVE`；`CONFIG_PRESENT` 为 `NOT_OWNED`。
- Syslog 退出只接受匹配目标的 `ACTIVE`、NetConsole 创建记录；退出失败保留 `ACTIVE`，允许安全重试；成功退出保留 `REVOKED` 审计。
- 修复退出验证失败路径重复使用同一审计 ID 的异常写入问题。
- 批次入口为每次提交创建独立 Task ID、设备集合和 `DEVICE_QUEUED` 事件；同一 MR 可在多个批次中重复提交，不再以 `SYSLOG_DEVICE_BUSY` 拒绝。
- Supervisor 按设备 FIFO 串行实际配置操作；重复批次仍保留各自设备结果，服务返回 `CONFIGURED`、`ALREADY_CONFIGURED`、`CONFIG_CONFLICT`、`FAILED`、`CANCELLED` 映射，并记录审计 ID。
- 重复加入每次重新读取设备配置：目标已正确存在时只读检查并映射 `ALREADY_CONFIGURED`，不重复下发、不新增所有权；冲突不覆盖。取消只移除本批次待处理项。
- Backend 启动时从 Job Center 的运行中批次及 `BATCH_DEVICES`、`DEVICE_QUEUED`/设备结果事件恢复未完成设备队列；设备清单在提交队列前持久化，事件按最多 2000 条读取，保留不同批次的独立进度。

## 尚未实施

失败设备按错误类型自动重试、独立逐设备 API、Heartbeat/Receiver 完全脱离 Run 生命周期及稳定性压测仍待后续 R2.1-R2.4 阶段。当前恢复依赖已持久化的 Task Center 事件，真实 Backend 崩溃窗口和设备现场仍需验收。

## 数据边界

只修改源码、测试和报告；未访问或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`、现场设备或既有数据库。
