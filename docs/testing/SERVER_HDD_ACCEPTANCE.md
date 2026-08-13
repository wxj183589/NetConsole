# Windows Server/HDD Phase 2.1 验收 Runbook

本流程用于 Windows Server 2016 + 机械硬盘/硬件 RAID 现场。它验证 Phase 2.1 的
兼容性和启动行为，不执行 Phase 2.2，也不自动迁移、删除或压缩 legacy history。

## 安全边界

- 现场数据根 `D:\NetConsoleData` 只读；不要执行 `VACUUM`、checkpoint、迁移、DROP、DELETE、rename 或替换。
- Backend 正在运行时不要复制或锁定现场 `devices.db`，不要 `taskkill`。若无离线副本，记录 `OFFLINE_SNAPSHOT_NOT_AVAILABLE` 并跳过物理副本验证。
- 验证副本必须位于独立 TEST root，不能位于 `D:\NetConsoleData`，也不能提交 Git。

## 诊断采集

在仓库根目录执行（PowerShell）：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m scripts.maintenance.diagnose_server_hdd `
  --database "D:\NetConsoleData\sites\宁波地铁12号线\db\devices.db" `
  --disk-path "D:\NetConsoleData" `
  --startup-log "D:\NetConsoleData\runtime\logs\app.log" `
  --output ".local\validation\server-hdd-before.json"
```

脚本只读输出 OS/CPU、卷容量、Backend PID、devices.db/WAL/SHM、schema/table/index/history
计数和可用启动阶段。Windows Server 2012/2012 R2 不支持的磁盘 active time、队列和延迟返回
`unknown`；这些字段由资源监视器/PerfMon 人工记录，脚本不会每秒启动 PowerShell。

## 离线副本验证

拿到用户提供的离线副本后，在隔离目录运行：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m scripts.maintenance.validate_phase21_snapshot `
  --source "E:\offline\devices.db" `
  --work-root "E:\NetConsoleValidation\phase21"
```

验收要求：第一次初始化允许按 schema 进入 maintenance；第二次初始化必须走 current-schema
fast path，文件大小稳定，不扫描 history shard，不调用 legacy migration。副本仍应能查询旧
history；新事件经 `history_outbox` 排空后进入 `history/devices-YYYY-MM.db`。

## A/B 现场步骤

1. 安装新包，保留原有 `D:\NetConsoleData`，记录诊断 BEFORE 和资源监视器：Backend、`devices.db`、`devices.db-wal`、当月 shard、Disk Active、Queue Length、读写 B/s。
2. 启动 NetConsole，记录 `spawn -> first stdout -> storage_manifest -> active_site_database -> listener -> health_ready` 各阶段和 READY 时间。
3. 正常托盘退出，确认安全退出完成后 `NetConsoleBackend.exe` 消失；不得以 Electron 窗口消失代替 Backend 已退出。
4. 立即第二次启动并记录 READY 时间。current-schema 第二次启动不得再次执行迁移、normalization 或 `wal_checkpoint(TRUNCATE)`。
5. 重复 `START -> READY -> QUIT -> BACKEND EXIT -> START` 至少 20 轮，记录残留 PID、data-root lock、startup timeout 和每轮耗时。
6. 在 `SERVER_UNATTENDED ACTIVE` 下运行 Syslog、MR、长 Ping/Traffic，确认任务 persistence 优先；观察 `history_pending`、最老 pending age、`history_last_drain_elapsed_ms`、`history_last_drain_written` 和 `history_budget_overrun`，不启动 migration/retention/VACUUM。
7. 退出后再次运行诊断 AFTER。验收看第二次启动是否进入 health，而不是要求固定 MB/s；不同 RAID/HDD 只比较同机 BEFORE/AFTER 的重写行为和 ready 时间。

## 结论记录

报告必须区分 `PASS`、`FAIL`、`NOT EXECUTED`。本仓库自动化不能替代真实 GUI、Windows 资源监视器、现场设备连接或长时间 20 轮循环；未执行项目必须保留为 `NOT RUN/PENDING`。
