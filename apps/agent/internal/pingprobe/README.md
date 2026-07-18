# Agent Ping 探测

本目录提供 Agent 侧基础 Ping 探测和结果归一化能力，供健康检查与受控任务使用。它不实现 fping 高级参数，也不直接访问 Vue 或数据库。

主要入口是 `pingprobe.go`；结果进入任务事件链。使用 `go test ./internal/pingprobe`，修改结果字段时检查 Agent API 与 Controller DTO。
