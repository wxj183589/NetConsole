# Agent fping 执行器

本目录封装 fping v5 的进程启动、参数约束、输出收集和平台差异，向 Agent 任务核心提供高频 Ping 结果。它不实现通用命令执行。

运行工具来自已审计的 `resources/tools` 交付资源；结果和事件写入任务运行目录。使用 `go test ./internal/fping`，Windows 进程改动还需检查工具探测和清理行为。
