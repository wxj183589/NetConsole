# 局点与数据存储

NetConsole 的正式桌面产品是 Electron Main + Vue + FastAPI/Python Core。局点、数据根、迁移和 `.ncsite` 包由 Python Application Service 管理，Electron Main 只提供原生选择器、受控目录打开和 Backend 重启。

## 文档

- [数据根](DATA_ROOT.md)：默认路径、bootstrap、校验和迁移。
- [局点管理](SITE_MANAGEMENT.md)：Registry、新建、切换和活动任务门禁。
- [局点迁移](SITE_MIGRATION.md)：单局点/全局迁移、staging、回滚边界。
- [局点包格式](SITE_PACKAGE_FORMAT.md)：manifest、checksum、凭据排除和安全导入。
- [备份恢复](BACKUP_AND_RESTORE.md)：替换导入、旧数据保留和恢复策略。
- [安全边界](SECURITY.md)：路径、ZIP、API 和 Electron IPC 约束。

当前新增功能已接入 `/api/v1/sites` 和 `/api/v1/storage/data-root`；真实设备、真实大数据迁移和人工 Electron 点击验收仍需单独执行。
