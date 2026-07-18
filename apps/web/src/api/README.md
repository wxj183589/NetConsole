# Web API 客户端

本目录封装 Vue 对 FastAPI 的请求、响应类型和 WebSocket/轮询适配，按业务域拆分。它只做传输层映射和轻量错误处理，不编排设备、数据库或任务业务。

主要入口是各域的 `*.ts` 及其测试；契约来源于 Backend Router 和 Application Service。修改 DTO、分页或事件字段后运行对应 Vitest 测试并检查服务端映射。

## 用途与边界

本目录是 Renderer 到 FastAPI 的传输适配层，负责请求、响应、分页、轮询和 WebSocket 映射；不编排设备、数据库、Job 或 Export。

## 主要入口

各业务域的 `*.ts` 是入口，`client.ts` 提供公共请求客户端，配套 `*.test.ts` 固化 DTO 和事件行为。

### 设备详情

`deviceManagement.ts` 映射以下 `/api/device-management/devices/{device_uuid}` 契约：

- `GET /overview`
- `GET /interfaces` 与 `GET /interfaces/{interface_name}`
- `GET /transceivers`
- `GET /lldp`
- `GET /config-snapshots`
- `GET /tasks`
- `GET /business-associations`
- `POST /refresh`

接口、光模块、LLDP、配置和任务列表保留服务端分页/筛选参数；历史查询复用设备管理 history 契约。客户端只映射 Pydantic DTO，不根据厂商、版本、角色或 capability 选择命令。刷新是否可执行以 overview 的 `command_profile.executable` 为准，任务状态由共享 Task Store 轮询。

LLDP 客户端公开字段保留本地接口、归一化本地接口、邻居系统名/MAC/接口/IP、关联设备 UUID、关联状态和采集时间；不映射历史存储中的邻居 `capabilities`、`model`。不得通过任意字典或透传响应绕过该白名单。

## 依赖关系

客户端依赖 Backend Router 的 DTO、Application Service 的用例契约以及 Web 类型层；Electron 能力不应从这里直接访问 Node。

### 轨旁 AP 业务导出

`tracksideApBusiness.ts` 通过 `POST /api/rail-transit/trackside-ap-business/export` 创建正式导出任务，并通过 `/artifacts/{artifact_id}/download` 构造受控下载请求。Vue 只轮询任务和调用 Runtime Adapter，不生成 XLSX、不接收服务端绝对路径，也不兼容历史导出路由。

## 数据与状态

这里只保存请求参数、响应映射和轻量错误信息；任务、设备、文件和会话状态由 API/Store 管理。设备密码、SNMP community、Token、服务端绝对路径和任意环境变量不得进入响应。设备详情缺失值保持 `null`，合法数值 `0` 不得被空值映射吞掉。

## 测试与修改

开发阶段运行对应 Vitest 定向测试。修改字段、分页、事件游标或错误码时同步检查 Python DTO/Router、Store 和页面测试；全量 Web 测试、类型检查和生产构建只在最终集成组合上运行。当前低 CPU 限制下，本轮文档同步未运行上述命令。

## 生成与清理

API 客户端不生成持久文件；测试 mock、快照和临时响应只能写测试临时目录，禁止把真实回显或 Token 提交到源码。

## 相关文档

参见 [设备管理页面](../views/devices/README.md)、[API/Application 边界审计](../../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md)、[Web 架构](../../../../docs/WEB_ARCHITECTURE.md) 和 [API DTO 模型](../../../../src/netconsole/models/api/README.md)。
