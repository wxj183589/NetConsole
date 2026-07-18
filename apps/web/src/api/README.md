# Web API 客户端

本目录封装 Vue 对 FastAPI 的请求、响应类型和 WebSocket/轮询适配，按业务域拆分。它只做传输层映射和轻量错误处理，不编排设备、数据库或任务业务。

主要入口是各域的 `*.ts` 及其测试；契约来源于 Backend Router 和 Application Service。修改 DTO、分页或事件字段后运行对应 Vitest 测试并检查服务端映射。

## 用途与边界

本目录是 Renderer 到 FastAPI 的传输适配层，负责请求、响应、分页、轮询和 WebSocket 映射；不编排设备、数据库、Job 或 Export。

## 主要入口

各业务域的 `*.ts` 是入口，`client.ts` 提供公共请求客户端，配套 `*.test.ts` 固化 DTO 和事件行为。

## 依赖关系

客户端依赖 Backend Router 的 DTO、Application Service 的用例契约以及 Web 类型层；Electron 能力不应从这里直接访问 Node。

## 数据与状态

这里只保存请求参数、响应映射和轻量错误信息；任务、设备、文件和会话状态由 API/Store 管理，敏感凭据不进入响应。

## 测试与修改

运行对应 Vitest 和 Web 全量定向测试。修改字段、分页、事件游标或错误码时同步检查 Python DTO/Router、Store 和页面测试。

## 生成与清理

API 客户端不生成持久文件；测试 mock、快照和临时响应只能写测试临时目录，禁止把真实回显或 Token 提交到源码。

## 相关文档

参见 [API/Application 边界审计](../../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md)、[Web 架构](../../../../docs/WEB_ARCHITECTURE.md) 和 `src/netconsole/models/api/`。
