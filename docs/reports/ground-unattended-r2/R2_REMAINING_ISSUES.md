# Ground Unattended R2 剩余问题

- Syslog 批次关系和设备结果已通过 Task Center 事件持久化，并在启动时恢复未完成设备；真实进程崩溃窗口、跨进程互斥和现场并发仍需验证。
- 失败设备自动重试及取消语义仍需完整任务模型验证。
- Heartbeat 和 UDP Receiver 的 Backend 常驻生命周期、健康隔离和恢复测试未完成。
- AC 60 秒默认轮询、AC-Mesh-Link 默认关闭需在 R2 综合回归中复验。
- 真实设备、GUI、400 目标、UDP 压力和长稳验收尚未执行。
