# 备份与恢复

完整迁移包替换导入前，当前局点移动到数据根 `archive/site-import-<site_id>-<operation>`；成功后仍保留。导入 staging 校验失败时恢复原目录；Registry 更新失败也不能删除备份。

采集回传包不会替换局点目录。写入前在 `files/backups/sync-import-<id>/` 保存受影响数据库和局点元数据；失败会从该快照恢复数据库并移除 journal 精确登记的本次新增文件。相同 package hash/base revision/mode 重放复用已完成审计，不再生成一个完整快照。进程中断由 `temp/site-sync-import-journal/` 在启动时判定 rollback 或 committed；原始文件、报告和删除请求默认只追加/记录，不自动删除。

全局数据根迁移产生 `migrations/migration-<id>.json`，旧数据根不自动清理。清理和归档必须经过用户明确操作、路径白名单和完整性检查。数据库恢复只接受经过 `quick_check` 的副本，不在 Electron Main 或 FastAPI Router 中直接操作 SQLite。
