# Repository 持久化层

本目录封装 SQLite 表、查询、写入和数据边界，按设备、任务、Agent、Traffic、Mesh 等域拆分。Repository 不应被 Vue、Router 或 Electron 直接调用，也不持有跨线程连接。

主要入口为各域 `*_repository.py`；数据库路径由 PathResolver/站点上下文提供。修改 schema、索引、事务或锁处理时运行数据库、迁移和对应 Service 测试。


## 用途与边界

本目录是 SQLite 持久化边界，按设备、任务、Agent、Traffic、Mesh、Online MR 和基础资料拆分；Repository 不被 Vue、Router 或 Electron 直接调用。

## 主要入口

各域 `*_repository.py` 提供查询/写入接口，`device_repository.py`、`task_repository.py`、`traffic_run_repository.py` 和 Mesh/Agent 仓储是主要入口。

## 依赖关系

Repository 依赖 Database/PathResolver/站点上下文，被 Service、Application、Job 和 Query Service 调用；SQLite connection 不跨线程或进程共享。

## 数据与状态

数据库、WAL、备份和可重建分析表位于系统应用数据局点目录；Repository 负责事务/锁边界，不把凭据、原始日志或报告静默删除。

## 测试与修改

修改 schema、索引、SQL、分页或事务时运行 database、paths、migration、repository 和对应 Service/API 测试，检查旧库兼容与 locked/WAL 行为。

## 生成与清理

测试数据库使用 `tmp_path`；运行数据库/备份/临时导出由 PathResolver 和维护清理白名单管理，禁止直接递归删除未知数据。

## 相关文档

参见 [数据与路径](../../../docs/DATA_LAYOUT.md)、[Job Center](../../../docs/JOB_CENTER.md) 和 [数据安全 Skill](../../../.agents/skills/netconsole-data-safety-skill/SKILL.md)。
