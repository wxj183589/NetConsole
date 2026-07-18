# Agent 任务核心

本目录定义 Agent 任务、事件和状态的基础模型，是 HTTP、Ping、iPerf、MR sidecar 等执行组件共享的内核。它不负责 UI，也不直接决定控制器的展示映射。

主要入口为 `task.go` 与 `event.go`；状态只在 Agent 运行数据根持久化。使用 `go test ./internal/core` 验证生命周期和事件语义，变更后检查 Controller 映射。
