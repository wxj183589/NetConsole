# Application Service 组合层

本目录编排跨 Repository、Service、Job 和 Export 的用户用例，为 FastAPI 与 Electron Backend 提供稳定调用边界。它不实现 Router DTO，也不把业务状态放入 Vue。

主要子域为 AC、桌面动作和轨道交通；修改用例编排时检查依赖层测试、事务/任务边界和错误映射，长耗时工作必须进入 Job/Export。

## 用途与边界

本目录编排跨 Repository、Service、Job 和 Export 的用户用例，为 FastAPI/Electron Backend 提供稳定调用边界；不实现 Router DTO 或 Vue 业务。

## 主要入口

`ac/`、`desktop/` 和 `rail_transit/` 提供领域应用入口，公共用例通过业务 Service、Query Service 和 Job Center 组合。

## 依赖关系

Application 层向下依赖 Service、Repository、Job/Export adapter，向上由 FastAPI 或 Desktop 调用；禁止把设备连接和 SQL 直接写进 Router。

## 数据与状态

用例通过 PathResolver/Repository 读写业务数据，通过 Job/Export 传递长任务状态；应用层不持有跨请求的 SQLite connection 或 Renderer 状态。

## 测试与修改

运行对应 Application/API/Repository/Job 测试和依赖层 Guard。新增用例先定义输入输出、错误、事务、取消和权限边界，再接入 Router。

## 生成与清理

长耗时 IO/CPU/网络进入 Job，正式文件进入 Export Process；临时会话、数据库和报告由 PathResolver/Job/Export 白名单清理，不静默删除原始数据。

## 相关文档

参见 [下一阶段开发指南](../../../docs/DEVELOPMENT_GUIDE.md)、[API 边界审计](../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md) 和 [Job Center](../../../docs/JOB_CENTER.md)。
