# NetConsole R3 架构审计

审计基线：`codex-A/ground-unattended-v2-20261107`，HEAD `7063d85d`。

当前运行形态是 Electron Renderer -> HTTP -> Python Core Service。Ground Supervisor 在 Core 内管理调度、Fleet Ping、Heartbeat State、AC resident、Syslog Receiver 和 Deep Scheduler；Quick Ping 是独立线程域，拥有独立任务、停止事件、IP reservation、raw segment 和恢复逻辑。SQLite Repository 是统一存储边界，Syslog 已有 Raw 优先和异步解析链。

本轮保留单 Core 进程和按需线程，没有引入微服务或常驻 Storage 进程。新增共享丢包事件投影、任务调度观测和有限批量归档删除。Electron 关闭不影响 Core 生命周期的现有启动契约，页面刷新不重启后台任务。

残余风险：真实 Windows Service 安装、进程句柄、Job Object 和跨机器互操作未在本轮执行。
