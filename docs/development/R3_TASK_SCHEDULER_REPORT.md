# R3 任务调度报告

新增 `GroundTaskScheduler`，按 HEARTBEAT、QUICK_PING、AC_POLLING、SYSLOG_PARSE、CONFIG_BACKUP、CONFIG_RESTORE、REPORT_EXPORT、HISTORY_ARCHIVE、DEEP_ANALYSIS 分域保存有界优先队列。每项任务具备 task id、类型、优先级、创建时间、状态、重试计数、错误码、错误信息和 owner。

已实现：容量拒绝、同域去重、取消、单次执行、失败计数和快照。取消项立即释放队列容量；运行中取消不会在回调结束后被误标为完成。去重键独立保存，不占用错误字段。现有业务线程仍按原生命周期运行，调度器作为统一边界和观测层逐步接入，避免一次性重写后台。

定向回归覆盖优先级顺序、容量释放、取消和失败统计；默认短压提交 101 项任务后得到 97 完成、4 失败、0 积压。当前 `worker_count=0`，调度器仍是观测/执行边界，不自动创建常驻 Worker。
