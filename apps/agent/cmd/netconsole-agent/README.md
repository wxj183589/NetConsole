# NetConsole Agent 主程序

本目录包含 Windows Go Agent 的唯一命令行入口 `main.go`。它负责读取受控配置、初始化任务/API/工具组件并管理进程生命周期，不应在此实现新的设备命令或前端业务。

依赖使用 Go module 和 `internal` 包；真实配置、日志、任务和采集包位于 Agent 数据根。修改后运行 `go test ./...`，构建产物写入规定的 `dist/agent/`，不得保留在源码目录。
