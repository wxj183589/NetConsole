# Agent 内部包

本目录是 Go Agent 的私有实现边界，按 API、配置、任务核心、fping/iPerf、MR、目标和系统工具拆分。外部程序只能通过 Agent HTTP API 使用这些能力。

包之间通过明确的 Go 接口传递任务、事件和结果；凭据与运行数据不提交。修改任一子包后在 `apps/agent` 执行 `go test ./...`，清理由运行维护脚本负责。

## 用途与边界

这里是 Agent 的私有 Go 实现，包含 HTTP、配置、任务核心、流量工具、MR sidecar、目标和平台适配；外部程序只能使用 Agent API。

## 主要入口

命令入口在 `../cmd/netconsole-agent/`；本目录按子包提供 `api`、`config`、`core`、`fping`、`iperf`、`mr` 和目标管理等实现。

## 依赖关系

子包使用 `apps/agent/go.mod` 和内部接口协作；工具路径由 toolmanager 提供，任务状态由 core 提供，不依赖 Python 或 Vue。

## 数据与状态

目标、任务事件、日志和采集包写入 Agent 运行数据根；凭据只在受控进程内存中使用，源码与测试不得带真实值。

## 测试与修改

在 `apps/agent` 执行 `go test ./...`；修改公共事件/API/包格式时同时检查 Controller、Traffic 和 Online MR 的契约测试。

## 生成与清理

工具执行输出、sidecar 会话和采集包进入 `.local/agent/` 或系统 Agent 数据根，构建物进入 `dist/agent/`；使用 Agent 脚本清理。

## 相关文档

参见 [Agent 总说明](../README.md)、`docs/AGENT.md` 和 `docs/AGENT_TRAFFIC_API.md`。
