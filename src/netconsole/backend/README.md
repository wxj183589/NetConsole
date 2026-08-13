# Python Backend

本目录提供 FastAPI 后端组合根、生命周期和 Electron 受管 Backend 运行入口。Router 只负责 DTO、鉴权、Service 调用和响应映射，设备/数据库/任务逻辑留在业务层。

主要子目录为 `api/`，启动与资源路径遵守 `PathResolver`/运行环境规则。修改后运行 Backend、Router boundary 和 Electron runtime 定向测试。


## 用途与边界

本目录是 Python Backend 的 FastAPI 组合根、生命周期和 Electron 受管运行入口；Router 只做 DTO/鉴权/Service 映射，不实现设备、数据库或任务状态机。

## 主要入口

`api/` 提供 HTTP/WebSocket Router，Backend runtime/lifespan 负责启动和关闭；主进程入口由项目 `main.py`/Electron runtime 编排。

## 依赖关系

Backend 组装 Application/Query Service、Repository、Job/Export、Agent Controller 和 PathResolver；Web/Electron 只能通过 API/Bridge 使用。

## 数据与状态

生命周期管理数据库连接、任务/导出进程和应用数据目录；凭据不进入响应，SQLite connection 不跨线程/进程共享。

## 测试与修改

运行 Backend、Router boundary、依赖层、Electron runtime 和相关 API 测试。新增 Router 必须保持 DTO/Service/鉴权/错误边界，长任务进入 Job。

## 生成与清理

Backend 不把运行数据写入源码；日志、数据库、任务、导出临时文件由 PathResolver/Job/Export 维护，关闭和异常路径必须可清理。

## 相关文档

参见 [当前架构](../../../docs/ARCHITECTURE.md)、[API 边界审计](../../../docs/development/API_APPLICATION_BOUNDARY.md) 和 `api/README.md`。
