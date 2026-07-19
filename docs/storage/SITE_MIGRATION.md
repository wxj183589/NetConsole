# 局点迁移

全局数据根迁移和单局点迁移都是 Task Center 任务，任务类型分别为 `site_data_root_migration` 和 `site_migration`。复制过程中排除运行锁、缓存、临时文件和正在写入的 `.tmp` 文件，源目录始终保留。

流程：获取迁移锁、校验目标、复制 staging、校验文件/SQLite、写迁移 manifest、发布目标、返回 `restart_required`。任何失败都保留源数据并清理本次 staging；不会把两套数据根同时设为可写，也不会静默删除旧目录。
