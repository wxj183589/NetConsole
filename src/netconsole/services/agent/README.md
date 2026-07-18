# Agent Controller 服务

本目录管理 Python Core 对 Windows Go Agent 的注册配置、健康检查、认证、HTTP 客户端和事件映射。Token 只留在 Controller 进程内，不能返回 API 或写日志。

主要入口为 `controller.py`、`http_client.py`、`credential_vault.py` 和 `event_hub.py`。修改协议、重试或状态时运行 Agent Controller/API/WebSocket 测试。

## 用途与边界

本目录管理 Python Core 到 Windows Go Agent 的配置、健康检查、认证、HTTP 客户端和事件映射；不实现 Agent 内部任务或任意远程命令。

## 主要入口

`controller.py` 负责控制面，`http_client.py` 负责受控请求，`credential_vault.py` 管理进程内凭据，`event_hub.py` 收敛任务事件。

## 依赖关系

服务依赖 Agent Repository、PathResolver、HTTP/WebSocket 协议和 Go Agent API，由 Application/Router/Online MR 调用；Token 不返回 DTO。

## 数据与状态

Agent 配置和状态写入每局点 `agents.db`；凭据只在当前 Python Controller 进程内存存在，健康/任务事件通过受控映射传递。

## 测试与修改

修改协议、认证、重试、健康或事件状态时运行 Agent Controller、HTTP/WebSocket、Fake Agent 和相关 Web/Traffic 测试。

## 生成与清理

Agent 任务/原始日志/采集包由 Go Agent 数据根管理，Controller 只保存必要映射；停止、超时和异常路径必须清理会话句柄而不删除正式包。

## 相关文档

参见 [Agent Controller](../../../../docs/AGENT_CONTROLLER.md)、[Agent 流量协议](../../../../docs/AGENT_TRAFFIC_API.md) 和 [独立 Agent](../../../../docs/AGENT.md)。
