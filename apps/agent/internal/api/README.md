# Agent HTTP API

本目录实现 Go Agent 的 HTTP 服务端和请求路由，负责把受控 API 映射到任务核心、目标、Ping/iPerf 与采集包能力，不提供任意命令执行或任意路径访问。

主要入口是 `server.go`；配置和状态由相邻内部包提供。使用 `go test ./internal/api` 验证接口，API 改动同时检查 Agent Controller 与对应 Web/Traffic 契约。
