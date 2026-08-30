# 局点与数据存储

NetConsole 的正式桌面产品是 Electron Main + Vue + FastAPI/Python Core。局点、数据根、迁移以及 `.ncsite` / `.ncresult` 数据包由 Python Application Service 管理，Electron Main 只提供原生选择器、受控目录打开和 Backend 重启。

NSIS 安装器把程序安装位置和数据存放位置分开选择。业务数据根写入 `HKLM\Software\NetConsole\DataRoot`，当前机器为 `D:\NetConsoleData`，其顶层固定为 `config/`、`sites/`、`runtime/`、`agents/`、`migrations/` 和 `staging/`；普通局点安全删除时按需创建 `.trash/`。程序升级、修复和普通卸载均保留业务数据。开发和正式安装包都读取该唯一配置，自动测试仅可使用显式的 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`；不得使用 LocalAppData、用户目录、仓库、安装目录或系统 Temp 作为运行根。根锁、schema manifest、备份、冲突保留和迁移报告的约束见[数据根](./DATA_ROOT.md)。

## 文档

- [存储架构](./STORAGE_ARCHITECTURE.md)：全局 authority、producer/consumer/lifecycle owner、数据分类、Site Package 边界与 `UNKNOWN = PROTECT`。
- [数据库设计指南](./DATABASE_DESIGN_GUIDE.md)：current/history/raw/derived 分层、source identity、测量精度、状态去重与查询 parity。
- [数据库与持久化生命周期](./DATABASE_LIFECYCLE.md)：创建、验证、发布、归档、备份、staging、恢复与受控退役。
- [存储测试指南](./STORAGE_TESTING_GUIDE.md)：全局 inventory、Before/After parity、No-Reinflation、Site Package 与只读真实 snapshot 验收。
- [数据根](./DATA_ROOT.md)：默认路径、bootstrap、校验和迁移。
- [局点管理](./SITE_MANAGEMENT.md)：Registry、新建、切换、Legacy/Demo 审计、二阶段回收和活动任务门禁。
- [局点迁移](./SITE_MIGRATION.md)：单局点/全局迁移、staging、回滚边界。
- [局点包格式](./SITE_PACKAGE_FORMAT.md)：未加密完整迁移、脱敏分享、现场采集、采集回传、manifest、checksum、凭据边界和安全合并。
- [备份恢复](./BACKUP_AND_RESTORE.md)：替换导入、旧数据保留和恢复策略。
- [局点数据保留与清理](./SITE_RETENTION.md)：扫描令牌、数据库分类、Online MR 原始数据、任务事件和保护边界。
- [真实数据根验证](./DATA_ROOT_VALIDATION.md)：Production/Dev Copy 隔离、复制流程和生命周期审计结果。
- [History Storage V2](./HISTORY_STORAGE_V2.md)：月分片 V2 格式、V1/mixed 兼容、物理基线和真实 snapshot/query 结果。
- [Legacy History COPY-only 迁移](./LEGACY_HISTORY_MIGRATION.md)：inventory、identity、checkpoint、verify、resume 和源数据保护边界。
- [安全边界](./SECURITY.md)：路径、ZIP、API 和 Electron IPC 约束。

机器可读的 owner、authority、分类、package/backup/migration policy 位于
[`config/storage_registry.yaml`](../../config/storage_registry.yaml)。注册表用于架构门和生命周期
约束，不等于生产迁移、删除、Server HDD 观察或 No-Reinflation 全部验收已经完成；未知 owner/authority
统一按 `UNKNOWN_PROTECT` 处理。对应架构决策见
[Storage Authority And Lifecycle ADR](../architecture/ADR-storage-authority-and-lifecycle.md)。

当前功能已接入 `/api/v1/sites` 和 `/api/v1/storage/data-root`。`PATCH /api/v1/sites/{site_id}` 只更新显示名称、线路名称和项目类型，不修改稳定 ID 或物理目录；普通非当前局点通过 `POST /api/v1/sites/{site_id}/trash` 原子移动到 `.trash/` 后再注销 Registry。空壳局点的二阶段 cleanup、Demo 重建和局点数据保留清理都复用现有 Task Center，不建立第二套任务模型。保留清理先通过 `/retention/scan` 生成服务端令牌和相对路径候选，再由 `/retention/apply` 复验后执行；当前数据库、未知数据库、活动任务和证据不足的原始数据固定受保护。审计结果不等于清理授权，`.trash/` 和 cleanup 回收区也不会由自动缓存清理处理。
