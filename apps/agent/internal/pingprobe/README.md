# Agent Ping 探测

本目录提供 Agent 侧兼容 `ping_probe`，实际使用并发 TCP Connect 并以 `mode=tcp` 返回，验证端口可达性，不等同于 ICMP Ping、RTT 或丢包。真实高频 ICMP 使用 `internal/fping` 的独立强类型任务。本目录不实现 fping 参数，也不直接访问 Vue 或数据库。

主要入口是 `pingprobe.go`；结果进入任务事件链。使用 `go test ./internal/pingprobe`，修改结果字段时检查 Agent API 与 Controller DTO。
