# API DTO 模型

本目录定义 FastAPI 与 Web/Electron 之间的 Pydantic 请求、响应和分页模型，按业务域拆分。DTO 只表达契约和校验，不访问数据库、设备或执行任务。

修改字段、枚举或可空性时同步 Router、Application Service、Web `types/api` 与测试；敏感凭据不得进入响应模型。

## 用途与边界

本目录定义 FastAPI 与 Web/Electron 之间的 Pydantic 请求、响应、分页和事件 DTO；只做契约校验，不访问数据库、设备、文件或任务执行器。

## 主要入口

各业务域 `*.py` 提供 DTO，`common.py` 和 `task.py` 提供共享分页/任务结构；Router 与 Web API 类型是主要消费者。

## 依赖关系

模型依赖 Pydantic 和领域值约束，被 Backend API、Application Service 和前端 `src/types` 映射；模型不反向依赖 Vue/Electron。

## 数据与状态

DTO 表示单次请求/响应或事件快照，不持有长期状态；Token、密码、community 等凭据必须被模型排除或脱敏。

## 测试与修改

修改字段、枚举、可空性或序列化时运行 API、Router boundary、Web API 和相应 Pydantic 测试，检查旧客户端兼容性。

## 生成与清理

模型不生成文件；测试 JSON、快照和临时响应写入 pytest 临时目录，禁止把真实设备回显或凭据写入 fixture。

## 相关文档

参见 [API 边界审计](../../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md)、[Web 架构](../../../../docs/WEB_ARCHITECTURE.md) 和 `src/netconsole/backend/api/README.md`。
