# Legacy HistoryStore Maintenance Boundary

## Status

运行时已经彻底退出 `HistoryStore`。Backend startup、普通采集、查询、导出和
Update All 不创建或读取 `<site>/db/history`，也不再写入 `history_outbox`。
四类业务历史改由 `devices.db` 的 Current + change-only Recent10 projection
承载，完整前后消费者见 [HISTORYSTORE_RUNTIME_CONSUMER_MATRIX.md](./HISTORYSTORE_RUNTIME_CONSUMER_MATRIX.md)。

本文件描述仍保留的 maintenance-only 能力：旧 `*_history` 表、旧
`HistoryStore` catalog/month shard 只可作为明确迁移或回滚证据读取，不能被
运行时服务注入。`scripts/maintenance/retire_legacy_history_store.py` 是本次
退役的唯一物理删除入口，使用逐库候选、源 manifest、SQLite Backup API、
quick/integrity check 和按环境控制的备份生命周期。

Production `apply` 同时要求：精确数据根 `D:\NetConsoleData`、候选验证为
`PASS`、源数据库和 history manifest 未变化，以及显式
`LEGACY_HISTORY_RETIREMENT_AUTHORIZED` token。开发 Authority 必须额外使用
`--development`，只接受精确 `D:\NetConsoleData-dev`；仅保留逐库短生命周期
备份，成功验证后立即退役该备份，并拒绝非空外部 HistoryStore。失败即停止并
恢复已切换的数据库；不允许猜测实体、静默删除未注册站点或触碰 tasks.db、
Task Result Blob、MESH、Online MR、Ground、Artifact 和其他存储。

## Inventory

`HistoryLegacyMigrationService.inventory()` 仍可发现名称以 `_history` 结尾的表并
写入 `LEGACY_HISTORY_INVENTORY.json`。它是审计/迁移输入，不是运行时注册；每张
表记录 schema、主键、索引、实体映射、时间字段、身份字段、源版本、行数和时间范围。

旧通用 COPY 迁移仍然只接受具备明确 id、时间和业务身份字段的输入；未知 schema
或无法确定身份的行必须 fail closed，不得猜测写入。此前被标为 unsupported 的
`ac_fit_ap_unauthenticated_history` 和 `ac_station_online_summary_history` 已由
本次专用脚本迁移到本地 Current/Recent10，不再需要目标月分片。

## Identity And Duplicate Projections

本次退役的源身份由注册站点、`devices.db` SHA-256 和 history 文件 manifest
共同确定；它不只依赖路径。候选 apply 前再次比较 manifest，任何生产写入或源文件
变化都会停止，不会在旧源上继续替换。

旧 AP projection 的身份匹配规则仍适用于旧 COPY maintenance：必须使用明确的
规范化业务字段，不能用模糊名称匹配或猜测 AP。新的四类 Recent10 projection
分别使用 device、AC+AP、AC+稳定推断身份和 site 作为资源键。

## Journal And Recovery

旧 HistoryStore `catalog.db` 中已有的迁移表仍只用于旧维护审计。它们不再是新
运行时的 authority；本次退役脚本在候选库中完成一次性回放，并记录 source rows、
discarded rows、Current/Recent counts、quick/integrity check 和 source manifest，
不会生成新的外部 HistoryStore shard。

运行时 authority 不再依赖旧表状态。候选验证成功后，Production 退役脚本先备份
`devices.db` 和 history 目录，再原子替换候选数据库，最后仅删除注册站点的
`db/history`；backup 保留回滚所需的旧源，且不自动 VACUUM 其他数据库。

Invalid timestamps、unsupported row shapes 和缺少业务身份的行不得静默变成
Current/Recent 事实；脚本会跳过无法安全归属的行并在候选报告中反映 source rows
与 migrated/discarded counts，Production apply 只接受候选验证为 `PASS` 的结果。

## Priority And Commands

维护分类为 `site-database-maintenance`。本次脚本不在 Backend startup 中注册，
必须由人工维护窗口显式调用；SiteRetention 的任务归档锁族仍保持原边界。

唯一的退役命令为 `prepare`、`apply` 和 `verify`。`prepare` 只读源并创建逐库
隔离候选库；`apply` 需要显式 authorization，Production 使用默认模式，开发
Authority 使用 `--development`；`verify` 只检查注册站点 Current/Recent 和
history 目录状态。无人值守运行不调用这些命令。

```powershell
$env:PYTHONPATH = "D:\study\worktrees\NetConsole\history-store-full-retirement\src;D:\study\worktrees\NetConsole\history-store-full-retirement"
& "D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.retire_legacy_history_store prepare `
  --data-root "D:\NetConsoleData" `
  --candidate-root "D:\study\diagnostic\NetConsole\history-store-retirement\<run-id>"

& "D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.retire_legacy_history_store apply `
  --data-root "D:\NetConsoleData" `
  --candidate-root "D:\study\diagnostic\NetConsole\history-store-retirement\<run-id>" `
  --backup-root "D:\study\backup\NetConsole\history-store-retirement\<run-id>" `
  --authorization LEGACY_HISTORY_RETIREMENT_AUTHORIZED

# 开发 Authority：candidate/temporary backup 必须位于 D:\study\NetConsole-Workspace\NetConsole\.local\tmp
# 等任务临时目录；不得复制整个 Site 或非空 HistoryStore。
& "D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe" -m scripts.maintenance.retire_legacy_history_store apply `
  --development `
  --data-root "D:\NetConsoleData-dev" `
  --candidate-root "D:\study\NetConsole-Workspace\NetConsole\.local\tmp\history-store-retirement-dev\<run-id>" `
  --backup-root "D:\study\NetConsole-Workspace\NetConsole\.local\tmp\history-store-retirement-dev-backup\<run-id>" `
  --authorization LEGACY_HISTORY_RETIREMENT_AUTHORIZED
```

## Remaining Gates

- Production apply 必须在应用正常停止后完成；重新启动、Update All 和运行时
  smoke 之后再次 verify，确认没有重建 `db/history`。
- GUI 可交互性、真实设备可达性和现场业务验收仍是独立门禁；自动化测试通过不
  代表设备或 Electron GUI 已完成现场验收。
