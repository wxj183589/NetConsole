# Agent MR sidecar

本目录管理车载 MR sidecar 的启动、模板、平台进程和采集结果收敛。它只编排 Agent 侧受控采集，不保存长期业务数据库或提供任意 SSH 命令。

主要入口为 `collector.go`、`sidecar.go` 和模板文件；会话、日志、结果包由 Agent 运行目录承载。使用 `go test ./internal/mr`，修改时检查 Online MR 导入契约。
