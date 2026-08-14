---
name: netconsole-data-safety-skill
description: "SQLite schema、Repository、数据库 locked/WAL、PathResolver、数据目录、会话目录、备份、迁移、临时文件、自动清理或删除安全任务时使用。纯 UI、无持久化 parser 或普通文档更新不使用本 Skill。"
---

# 目标

保护 NetConsole 主应用数据库、会话原始日志、用户配置和正式报告，在可回滚前提下处理 schema、连接、目录、迁移和清理。

# 触发与反例

触发示例：

- “增加 SQLite 字段并兼容旧数据库。”
- “修复 database locked 或跨线程连接错误。”
- “调整数据目录、自动清理或会话打包，防止误删 raw log。”

不应触发：

- “只修改 Qt 页面布局。”
- “修复不读写数据库的 parser 或普通 Markdown。”

# 输入与输出

- 输入：目标数据库/目录、当前 schema、数据分类、迁移/清理规则和回滚要求。
- 输出：安全的 Repository/迁移/路径修改、备份与回滚说明、测试和数据影响。
- 允许修改生产代码：允许，限数据/Repository/路径/清理领域和测试；破坏性 schema、递归删除或主库重建必须先得到明确授权。

# 开始前读取

- `docs/storage/DATA_LAYOUT.md`、`docs/ARCHITECTURE.md`、`docs/storage/DATABASE.md`。
- `src/netconsole/core/database.py`、`src/netconsole/core/sqlite_utils.py`、`src/netconsole/core/paths.py`、`src/netconsole/core/sites.py`。
- `src/netconsole/services/data_disk_manager.py`、`src/netconsole/services/app_auto_cleanup.py`、`src/netconsole/services/path_preference_service.py`。
- 目标 `src/netconsole/repositories/`、`src/netconsole/storage/`。
- 在线 MR 时读取 `src/netconsole/services/online_mr/collection_paths.py`、`src/netconsole/services/online_mr/collection_packager.py`。

# 工作流程与规则

1. 先分类：设备管理、FIT-AP 等主应用数据库默认保持稳定；解析会话/分析 SQLite 仅在对应领域文档与兼容要求允许时重构。
2. 识别旧 schema 和真实数据量；高风险升级先备份，迁移尽量幂等、事务化并可重复执行。
3. 数据访问进入 Repository；UI 不写复杂 SQL。每线程/进程独立创建和关闭 connection，不跨线程共享。
4. 根据现有 helper 配置 WAL、busy timeout 和事务；不要用吞异常掩盖 locked。
5. 所有路径由 `PathResolver`/领域路径服务解析，不硬编码局点或用户路径。
6. 本地质量门和数据库测试统一覆盖 `RuntimeMode.TEST` 与唯一 `D:/study/test-data/NetConsole/<run-id>`；不得继承正式 `D:/NetConsoleData`，也不得让报告、缓存或临时数据库回写仓库。
6. 临时文件与正式文件分离；原子替换成功后再清理，失败保留原数据库/raw/正式报告。
7. 自动清理使用白名单和已验证项目数据根；递归删除前解析绝对目标并确认位于允许目录，禁止处理不可信路径。

# 必须保护

- 用户数据库、站点配置、原始设备/MR/MESH 日志、采集会话和正式导出报告。
- 旧数据可读性、Repository API、AP/FIT-AP 主数据和已发布导入格式。
- 不静默删除、重建或搬移用户数据，不用测试夹具覆盖生产数据。

# 验证与失败报告

- 在临时目录/临时数据库验证空库、旧库升级、重复迁移、事务回滚、WAL/locked、并发连接和路径越界拒绝。
- 删除/清理测试只用临时白名单目录；不得对真实 data 根做破坏性验证。
- 输出数据库分类、schema/路径变化、备份/回滚、旧数据兼容、删除边界和测试。

# 相关 Skills

- 修改 DataRoot/schema/migration 等 L4 契约前：`netconsole-change-review-skill`。
- Job 连接边界：`netconsole-job-center-skill`。
- Export 临时文件：`netconsole-export-report-skill`。
- AP 主数据风险：`netconsole-ap-identity-skill`。
