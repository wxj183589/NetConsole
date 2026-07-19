# 备份与恢复

替换导入前，当前局点移动到数据根 `archive/site-import-<site_id>-<operation>`，成功后仍保留。导入 staging 校验失败时恢复原目录；Registry 更新失败也不能删除备份。

全局数据根迁移产生 `migrations/migration-<id>.json`，旧数据根不自动清理。清理和归档必须经过用户明确操作、路径白名单和完整性检查。数据库恢复只接受经过 `quick_check` 的副本，不在 Electron Main 或 FastAPI Router 中直接操作 SQLite。
