# 旧/专用存储辅助

本目录保存尚未归并到通用 Repository 的专用数据库辅助，目前用于 MR 数据库访问。新持久化能力优先评估 `repositories/` 和 PathResolver，不在此复制连接管理。

主要入口为 `mr_db.py`；数据库路径、锁、WAL 和清理遵守数据安全规则。修改 schema 或连接边界时运行 MR、数据库和路径测试。

## 用途与边界

本目录保存尚未归并到通用 Repository 的专用存储辅助，目前是 MR 数据库访问边界；新持久化能力必须先评估 `repositories/`，不在此复制连接管理。

## 主要入口

`mr_db.py` 提供 MR 专用 schema/查询辅助，调用方通过显式 PathResolver/数据库上下文取得文件位置。

## 依赖关系

存储辅助依赖 SQLite、PathResolver 和 MR Service/Repository 调用方；不被 Vue、Router 或 Electron 直接使用，连接不得跨线程/进程共享。

## 数据与状态

MR 数据库、WAL、备份和可重建分析表位于局点数据根；原始日志、会话和正式报告保持独立目录与生命周期。

## 测试与修改

修改 schema、锁、WAL、查询或迁移时运行 MR、database、paths 和相关 Service 测试，使用临时数据库验证旧库兼容。

## 生成与清理

测试 DB 和临时迁移写入 `tmp_path`；生产数据库/备份清理只能由 data-safety 白名单工具执行，不直接递归删除未知路径。

## 相关文档

参见 [数据与路径](../../../docs/storage/DATA_LAYOUT.md)、[仓库 Repository](../repositories/README.md) 和 [数据安全 Skill](../../../.agents/skills/netconsole-data-safety-skill/SKILL.md)。
