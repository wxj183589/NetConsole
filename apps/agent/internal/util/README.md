# Agent 内部工具

本目录收纳 Agent 内部复用的 JSON 和平台文件替换辅助函数，保持小而稳定，不放业务状态机或跨层依赖。

主要入口为 `json.go` 与 `replace_*.go`；文件写入必须使用调用方传入的受控路径。使用 `go test ./internal/util`，修改原子替换逻辑时检查异常清理。
