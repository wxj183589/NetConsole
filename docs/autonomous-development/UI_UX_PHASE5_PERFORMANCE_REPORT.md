# Phase 5 性能记录

复用 [Phase 4 SQL 对照](UI_UX_PHASE4_PERFORMANCE_REPORT.md)，旧耗时仅作为背景。本轮未新增索引。选定 HZL10 Run 的 GUI 查询分页为 25 条，并校验不同 Run ID 与游标。

初次启动压测时，工具仍检查旧的 Ground 内置探测计数。改用产品的常驻 Heartbeat 配置与状态 API 后，生产代码的隔离实例使用 200 个回环目标和 7 个常驻探测进程，并发运行 Ground Syslog、合成 WMESH、独立 Quick Ping。

混合页面轮换发现 LIVE_COLLECTION 请求误带活动 Run ID，导致 Heartbeat API 返回 409。修复后总览仍按活动 Run 查询事件，心跳从常驻上下文读取。页面采样约 19 分 49 秒，发起 1,188 次请求，累计 SQL 响应计时 28.19 秒，JS Heap 峰值约 130 MB。采样记录 63 次非成功响应，最后一次增加在第 814 秒，随后至采样结束计数未增加。零 Renderer 异常。退出时页面轮换脚本遇到卸载竞态并以非零状态退出。

回环采集持续 1,800 秒，发送 175,840 条 UDP 消息。175 个资源样本记录的队列长度、丢弃计数及原始写入失败计数峰值均为零。Python 合计 RSS 峰值约 282 MB，Electron 进程组合计约 734 MB。以单核计的组内 CPU 采样峰值分别约 54% 和 32%。Ground 停止后仍有 200 个常驻目标、7 个探测进程。Electron 退出码 0，所属进程残留 0。混合采样未覆盖持续设备任务执行、队列积压以及完整 30 分钟的页面轮换。

[采集结果](../../../test-data/NetConsole/phase5-live-resident-20261128/summary.json) · [进程样本](../../../test-data/NetConsole/phase5-live-resident-20261128/metrics.ndjson) · [Renderer 样本](../../../reports/tests/legacy-ui-ux-phase5/mixed-ui.ndjson)
