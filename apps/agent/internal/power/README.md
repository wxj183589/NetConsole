# Agent 防休眠

本目录封装 Agent 启动和长任务期间的防休眠管理。Windows 实现调用 `SetThreadExecutionState`，退出时恢复系统电源行为；失败只记录状态，不阻断采集，也不永久修改系统电源计划。其他平台为空实现，不代表 CentOS Agent 已支持。

主要入口为 `manager.go`，平台差异位于对应文件；生命周期由调用方成对管理。使用 `go test ./internal/power`，修改后检查异常退出时的恢复路径。
