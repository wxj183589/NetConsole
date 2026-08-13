# Repository 持久化层

本目录封装 SQLite 表、查询、写入和数据边界，按设备、任务、Agent、Traffic、Mesh 等域拆分。Repository 不应被 Vue、Router 或 Electron 直接调用，也不持有跨线程连接。

主要入口为各域 `*_repository.py`；数据库路径由 PathResolver/站点上下文提供。修改 schema、索引、事务或锁处理时运行数据库、迁移和对应 Service 测试。


## 用途与边界

本目录是 SQLite 持久化边界，按设备、任务、Agent、Traffic、Mesh、Online MR 和基础资料拆分；Repository 不被 Vue、Router 或 Electron 直接调用。

## 主要入口

各域 `*_repository.py` 提供查询/写入接口，`device_repository.py`、`device_fact_repository.py`、`device_detail_repository.py`、`task_repository.py`、`traffic_run_repository.py` 和 Mesh/Agent 仓储是主要入口。

### 设备详情快照

设备详情页面通过 Query/Application Service 读取 Repository，不直接访问 SQLite：

- overview 使用 `devices.db.latest_snapshot`；
- 接口、光模块和 LLDP 使用各自最近快照，并保留可用的采集时间和 Task ID；
- `device_detail_repository.py` 提供有上限的分页、筛选、详情和历史读取；
- 任务摘要通过 Task Repository / `tasks.db` 获取；
- 配置与关联业务继续由现有领域 Repository/Query Service 提供，不复制表或数据源。

快照中未知的数值保持 `NULL`，不能写入伪造的零。Repository 不返回设备密码、SNMP community、Token、服务端绝对路径或任意环境变量。

LLDP 历史 schema 中既有的邻居 `capabilities`、`model` 字段不做破坏性删除或数据清理；它们属于内部兼容存储，不进入设备详情公开 DTO/API/Web。公开契约收口由 Query/Application 映射完成，Repository 迁移不得借此重建或截断用户历史表。

## 依赖关系

Repository 依赖 Database/PathResolver/站点上下文，被 Service、Application、Job 和 Query Service 调用；SQLite connection 不跨线程或进程共享。

## 数据与状态

数据库、WAL、备份和可重建分析表位于系统应用数据局点目录；Repository 负责事务/锁边界，不把凭据、原始日志或报告静默删除。

## 测试与修改

修改 schema、索引、SQL、分页或事务时先运行 database、paths、migration、repository 和对应 Service/API 定向测试，检查旧库兼容与 locked/WAL 行为；全量数据库/组合验证在最终集成时运行。当前低 CPU 限制下，本轮文档同步未运行测试或构建。

## 生成与清理

测试数据库使用 `tmp_path`；运行数据库/备份/临时导出由 PathResolver 和维护清理白名单管理，禁止直接递归删除未知数据。

## 相关文档

参见 [设备管理页面](../../../apps/desktop_renderer/src/views/devices/README.md)、[数据与路径](../../../docs/storage/DATA_LAYOUT.md)、[Job Center](../../../docs/job-center/README.md)和[数据安全 Skill](../../../.agents/skills/netconsole-data-safety-skill/SKILL.md)。
