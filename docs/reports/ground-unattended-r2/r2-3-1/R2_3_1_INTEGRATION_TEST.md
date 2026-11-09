# R2.3.1 三链路集成测试

## 运行关系

同一隔离 SQLite 运行三条互不互锁的链路：

1. Syslog Receiver 持续接收 UDP，Raw/Parser/Position 批量处理。
2. FleetPingSupervisor 同时维护 200 个 Heartbeat 目标和 17 个分片。
3. AC 模拟线程写入全快照和 delta 证据，并在结束后写入对账状态。

AC 查询慢、Heartbeat 采样慢、Parser 暂时积压不会通过同一把业务锁阻塞 Syslog；现有组件隔离测试确认这一边界。整合运行中 Syslog 402 条全部接收、解析并完成位置提交，Heartbeat stop 成功，AC 301 条 delta 写入完成。

## 恢复

Receiver 停止并在同一数据库/Raw 根重启，位置状态恢复后再接收 AP-C；相关位置和 Raw 证据连续。Backend lifespan、resident Heartbeat 重启以及 Repository recovery 测试通过。完整安装包 smoke 未运行，因为安装器明确要求 clean worktree，而当前存在用户并行 dirty 修改。
