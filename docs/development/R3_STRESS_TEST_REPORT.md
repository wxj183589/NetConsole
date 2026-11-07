# R3 压力测试报告

已添加可重复的纯逻辑测试覆盖：丢包事件开始/持续/恢复上下文、任务域容量、优先级队列、失败统计、取消释放容量和重复提交去重。

短压命令：

```text
python -m scripts.dev.ground_r3_short_stress
```

默认 Mock 证据（运行目录：`D:/study/NetConsole-Workspace/test-data/NetConsole/ground-r3-short-stress-9293b378dffb`）：

- 1000 个心跳目标、1000 个样本，1000/1000 ONLINE，耗时 27.326 ms。
- 101 个调度任务（1 个 HEARTBEAT、100 个 QUICK_PING），97 完成、4 个预期合成失败，队列归零。
- 2000 条 Raw Syslog，2000 条解析成功、0 解析错误，峰值解析积压 1967 条。
- 双线程 SQLite 竞争写入 200 行，7 次锁重试、0 写失败，`PRAGMA integrity_check=ok`。
- 全部短压耗时 0.648 秒，tracemalloc 峰值 1,562,294 字节，结束后线程数 1。

重复性校验：`--targets 500 --iterations 2` 也通过（运行目录：`D:/study/NetConsole-Workspace/test-data/NetConsole/ground-r3-short-stress-bab99560469d`），两轮均 500/500 ONLINE、2000/2000 Raw 解析、200/200 SQLite 行，锁重试 14/7、写失败 0。

Ground 后端定向回归（排除一个固定旧时间样本）为 `366 passed, 1 skipped`。完整 `tests/test_ground_unattended*.py` 仍有 1 个既有测试失败：`test_heartbeat_page_aggregates_real_ping_statistics` 使用 2026-11-07 之前的固定采样时间，当前实现按真实时间返回 `STALE`，测试仍断言 `RUNNING`。

短压是等效压力检查，不代表 1/4/8 小时长稳；长时间、真实设备、Electron 和 Backend 重启仍未执行。
