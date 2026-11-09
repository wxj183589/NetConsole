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
- 批次入口增加进程内设备占用检查，当前对重叠 MR 返回 `SYSLOG_DEVICE_BUSY`，Supervisor 记录任务设备集合并在完成/取消时释放。

## 尚未实施

批次占用尚未实现原子预留与排队，进程内状态不支持 Backend 恢复；失败设备自动重试、逐设备结果模型、Heartbeat/Receiver 完全脱离 Run 生命周期及稳定性压测仍待后续 R2.1-R2.4 阶段。

## 数据边界

只修改源码、测试和报告；未访问或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`、现场设备或既有数据库。
