# Ground Unattended R2 剩余问题

- Syslog 批次仍主要由进程内状态协调，尚未完成同 MR 串行、跨批次持久化、逐设备结果和 Backend 重启恢复。
- 失败设备自动重试及取消语义仍需完整任务模型验证。
- Heartbeat 和 UDP Receiver 的 Backend 常驻生命周期、健康隔离和恢复测试未完成。
- AC 60 秒默认轮询、AC-Mesh-Link 默认关闭需在 R2 综合回归中复验。
- 真实设备、GUI、400 目标、UDP 压力和长稳验收尚未执行。
