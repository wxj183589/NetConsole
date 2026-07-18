# Agent 托盘平台适配

本目录提供 Agent 托盘相关的平台占位和 Windows 实现边界。它只承载进程展示/平台适配，不建立第二套任务或配置系统。

入口为平台对应的 `tray_*.go` 文件；平台构建由 Go 编译选择文件。使用 `go test ./internal/tray`，Windows 行为变化需在目标环境做人工 smoke。
