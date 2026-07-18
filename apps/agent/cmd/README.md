# Agent 命令入口

本目录只保留 Go Agent 的可执行程序入口，不承载协议实现或业务存储。入口通过 `main.go` 组装 `internal` 包并启动独立 Agent HTTP 服务。

依赖由 `apps/agent/go.mod` 管理；运行配置和数据来自 Agent 运行目录，不回写源码目录。修改入口后执行 `go test ./...`，需要打包时使用 Agent 的 Windows 构建脚本并检查输出目录。
