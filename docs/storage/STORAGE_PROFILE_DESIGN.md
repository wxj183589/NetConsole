# Storage I/O Profile Design

`StorageProfileDetector` 以实际 `data_root` 的 volume 为检测对象，调用 Windows PowerShell/CIM `Get-Partition -DriveLetter ... | Get-Disk`，并将 RAID/virtual disk、未知及异常统一映射为 `CONSERVATIVE_STORAGE`。

## Profile

| 参数 | FAST_STORAGE | CONSERVATIVE_STORAGE |
|---|---:|---:|
| raw_batch_bytes | 64 KiB | 512 KiB |
| raw_flush_interval_ms | 250 | 400 |
| durable_sync_interval_ms | 1000 | 1000 |
| db_batch_size | 200 | 1000 |
| db_batch_interval_ms | 500 | 750 |

`AUTO` 使用检测结果；`FAST`/`CONSERVATIVE` 为持久化的手动覆盖。UNKNOWN 绝不提升为 FAST。

本轮只保留已实际接线的参数：Raw Writer 的字节/时间 flush、周期 durable sync、数据库批量目标、健康计数和 Ground 配置。Parser spool 仍是兼容副本；Raw segment、active writer 上限、SQLite checkpoint 调度与活动期归档策略没有接线，不作为当前 profile 能力声明。
