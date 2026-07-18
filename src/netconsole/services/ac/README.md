# AC 服务

本目录实现 AC/FIT-AP 资源查询、命令、光衰、Mesh-Link 和身份适配等业务 Service。它通过 Repository/Parser/Job 提供用例，不直接处理 HTTP 或 Vue 状态。

主要入口为 `ac_service.py`、`query_service.py`、`mesh_link_*` 和光衰服务。修改命令、字段或身份映射时运行 AC API、Job、Parser 和 Repository 定向测试。

## 用途与边界

本目录实现 AC/FIT-AP 资源查询、命令、光衰、Mesh-Link 和身份适配 Service；它通过 Parser/Repository/Job 提供用例，不直接处理 HTTP、Vue 或原始数据库连接。

## 主要入口

`ac_service.py`、`query_service.py`、`ac_command_service.py`、`mesh_link_*` 和 optical service 是当前主要入口。

## 依赖关系

服务依赖 H3C/AC Parser、device/AC Repository、Application Service 和 Job Center，由 FastAPI API 或任务 handler 调用；身份 adapter 仍是只读诊断边界。

## 数据与状态

查询和写操作使用局点数据库、设备会话和任务快照；凭据留在受控连接上下文，原始回显和历史数据按 PathResolver 保存。

## 测试与修改

修改命令、字段、光衰、Mesh-Link 或身份映射时运行 AC API、Job、Parser、Repository 和 Web parity 测试，保持命令顺序与未解析状态。

## 生成与清理

批量采集/刷新进入 Job，正式 XLSX/CSV 进入 Export Process；会话、原始回显和临时结果按局点白名单清理，不静默删除历史。

## 相关文档

参见 [AC 管理](../../../../docs/AC_MANAGEMENT.md)、[AP Identity](../../../../docs/AP_IDENTITY.md) 和 [Job Center](../../../../docs/JOB_CENTER.md)。
