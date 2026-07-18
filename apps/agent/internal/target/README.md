# Agent 目标管理

本目录管理 Agent 可连接目标的本地清单、读取和安全更新。目标数据只允许使用模板定义的字段，凭据不应写入 Git 或日志。

主要入口为 `store.go`；真实清单位于 Agent 数据根。使用 `go test ./internal/target`，字段或文件名变化时同步检查 Controller 配置映射。
