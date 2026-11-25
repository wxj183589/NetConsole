# Phase 8 数据迁移验收

状态：PARTIAL

迁移入口复用现有系统设置 DataRoot 流程和 Job Center。迁移前检查目标可写性、嵌套路径和活动任务，复制期间拒绝符号链接/Reparse Point，跳过运行时缓存与临时锁，SQLite 使用备份复制并在发布前执行完整性检查。目标发布后生成 `migrations/migration-<id>.json`，记录源/目标、时间、应用版本、Site 数量、文件数量、总容量、逐文件 SHA-256、数据库表计数和 Schema 版本。迁移失败保留源数据并清理未发布 staging。

自动化：

- `tests/test_site_storage.py`：80 passed，1 skipped。
- 覆盖空目标、源数据保留、Manifest 重绑定、文件哈希、SQLite inventory 和 Reparse Point 拒绝。
- `tests/test_unified_data_root_migration.py`：本轮未重复执行，历史套件已存在且未被本次代码修改。

跨计算机、网络映射盘、迁移中断后恢复和真实大数据目录：NOT VERIFIED。
