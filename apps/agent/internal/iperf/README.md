# Agent iPerf 执行器

本目录负责 iPerf3 的 TCP/UDP 参数校验、进程生命周期、输出解析和 Windows/其他平台差异。它只服务 Agent 的受控流量任务，不替代 Python Traffic Service。

工具路径由 Agent 工具管理器提供，原始输出和结果写入运行数据根。使用 `go test ./internal/iperf`，协议字段变化时同步检查 Traffic API 契约。
