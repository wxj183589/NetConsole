# 采集运行启动恢复契约

## 目的

Backend 启动或局点切换完成后，收口上一个已退出进程遗留的 `collect_runs` 运行记录。该机制只结束已确认不再由当前 Backend/Worker 持有的 stale 运行，不自动重放采集任务，也不修改设备事实、映射或原始日志。

## 生命周期顺序

- standalone/server 和 Electron Backend 都先取得 `BackendInstanceLock`，再创建应用并初始化活动局点数据库；正常启动的恢复因此不会与另一个同一 DataRoot 的 Backend 并发执行。
- warm handoff 使用 transition lock 和旧 owner 的 `instance_id`、`active_site_id`、`data_root` 校验；目标局点必须不同于旧局点。候选 Backend 可以在旧实例释放前读取目标局点，但不会把旧局点的 Worker 视为目标局点 owner。
- 启动初始化先执行一次恢复；Backend 启动后再经过约 5 分钟宽限期复查。复查在 `active_task_snapshot()` 报告 `active_tasks` 或 `active_workers` 时继续等待，owner 不可读时 fail closed。

## 数据契约

恢复条件固定为：`status = 'running'` 且 `started_at < stale_before`。恢复只把该行更新为 `failed`，写入 `ended_at` 和受控中文 `error_message`；`collect_run_uuid`、`collect_type`、`started_at`、`raw_log_dir`、`created_at` 等字段保持不变。

更新使用 `WHERE collect_run_uuid = ? AND status = 'running'` 的 CAS。Worker 已经完成或取消时，恢复不覆盖其终态；重复恢复为空操作。现有终态 `success`、`partial_success`、`failed`、`cancelled` 不会被扫描或重写。

`collect_runs` 不新增 `updated_at` 或其他 schema 字段；该恢复是 Repository 层的现有表生命周期操作。

## 观测与边界

恢复日志仅记录局点、恢复数量和 `stale_before`，不记录凭据、设备回显或原始 payload。自动化测试使用隔离数据库；Production 和真实设备验收仍是独立门禁。
