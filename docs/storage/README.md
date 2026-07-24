# 局点与数据存储

NetConsole 的正式桌面产品是 Electron Main + Vue + FastAPI/Python Core。局点、数据根、迁移以及 `.ncsite` / `.ncresult` 数据包由 Python Application Service 管理，Electron Main 只提供原生选择器、受控目录打开和 Backend 重启。

NSIS 安装器把程序安装位置和数据存放位置分开选择。业务数据根写入 `HKLM\Software\NetConsole\DataRoot`，当前机器为 `D:\NetConsoleData`，其顶层固定为 `config/`、`sites/`、`runtime/`、`agents/`、`migrations/` 和 `staging/`；程序升级、修复和普通卸载均保留它。开发和正式安装包都读取该唯一配置，自动测试仅可使用显式的 `D:\NetConsoleTestData\<run-id>`；不得使用 LocalAppData、用户目录、仓库、安装目录或系统 Temp 作为运行根。根锁、schema manifest、备份、冲突保留和迁移报告的约束见[数据根](DATA_ROOT.md)。

## 文档

- [数据根](DATA_ROOT.md)：默认路径、bootstrap、校验和迁移。
- [局点管理](SITE_MANAGEMENT.md)：Registry、新建、切换、Legacy/Demo 审计、二阶段回收和活动任务门禁。
- [局点迁移](SITE_MIGRATION.md)：单局点/全局迁移、staging、回滚边界。
- [局点包格式](SITE_PACKAGE_FORMAT.md)：完整迁移、现场采集、采集回传、manifest、checksum、凭据排除和安全合并。
- [备份恢复](BACKUP_AND_RESTORE.md)：替换导入、旧数据保留和恢复策略。
- [安全边界](SECURITY.md)：路径、ZIP、API 和 Electron IPC 约束。

当前功能已接入 `/api/v1/sites` 和 `/api/v1/storage/data-root`；局点审计、清理准备/执行与 Demo 重建复用现有 Task Center，不建立第二套任务模型。审计结果不等于清理授权，成功回收也只进入数据根内的受控归档。真实数据回收、真实大数据迁移和人工 Electron 点击验收仍需单独执行。
