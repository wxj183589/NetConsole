# Agent 配置

本目录解析并校验 Agent 的本地配置、目标清单和相关默认值。它只接受模板约定的字段，不保存真实密码、Token 或生产目标。

主要入口是 `config.go`；配置文件由运行目录或启动参数提供。使用 `go test ./internal/config` 验证，修改字段时同步检查 `resources/config` 模板和 Agent 文档。
