# Storage I/O Fix Report

## 已完成

- 新增实际数据盘检测与 UNKNOWN 保守降级：`src/netconsole/core/storage_io.py`。
- 新增 `AUTO`、`FAST`、`CONSERVATIVE` 手动覆盖并持久化到 Ground profile。
- Raw Writer 统一读取 `StorageIOProfile`，按 size/time flush，周期 `os.fsync`，停止时 flush + sync + close；健康快照增加 profile、flush/sync 计数和平均批量字节。
- Ground 健康页面展示数据目录所在卷、介质、策略和来源。
- 保留 UDP overflow spool、Parser spool、archive isolation 与历史 Raw reader 兼容性。

## 直接回答

1. 当前 Raw 仍是一条消息一次 write，但保守策略把 OS flush 合并为大块批次。
2. 不再 per-message flush/fsync；durable sync 周期为 1 秒，停止时强制同步。
3. active Raw writer 由 train/role/hour key 决定，可能几十个；统一 ingest segment 尚未迁移。
4. Parser spool 重复 Raw payload，当前保留以确保恢复。
5. SQLite Syslog 事件默认 100 条或 1 秒一事务；保守 profile 目标 1,000 条或 750 ms。
6. checkpoint 当前由 SQLite 默认行为控制；DEFERRED 策略已进入 profile，独立 checkpoint scheduler 尚未接入。
7. 主要放大来自多文件 Raw、小 flush、Parser duplicate spool 和 SQLite 事务。
8. SSD/NVMe -> FAST_STORAGE；HDD -> CONSERVATIVE_STORAGE。
9. RAID/UNKNOWN 底层介质不可见，不能证明 SSD，因此选择 CONSERVATIVE_STORAGE，避免 HDD 风险。
10. write-op/flush/fsync/transaction/checkpoint 的真实百分比需在指定开发数据根上长时压测后填写，本轮未伪造数字。

## 验证

`.venv/Scripts/python.exe -m pytest tests/test_storage_io_profile.py tests/test_udp_syslog_reliable_spool.py -q`：13 passed。
`.venv/Scripts/python.exe -m pytest tests/test_udp_syslog_reliable_spool.py tests/test_ground_unattended_api.py tests/test_runtime_profile.py -q`：44 passed。
`.venv/Scripts/python.exe -m py_compile`：相关 Python 文件通过。

## 后续主机验证

在 `D:\NetConsoleData-dev` 完成 Ground、Online MR、Renderer 回归与 FAST/CONSERVATIVE 长时 benchmark；不得使用真实数据根。
