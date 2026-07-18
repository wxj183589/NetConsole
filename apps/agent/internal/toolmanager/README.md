# Agent 工具管理

本目录探测、定位并校验 Agent 随包的 fping/iPerf 工具，处理 Windows/其他平台进程差异。它不从根 `tools/` 读取运行时工具，也不允许 IPOP 进入 Agent 包。

主要入口为 `manager.go`；工具来源是版本化 `resources/tools` 及构建后的交付目录。使用 `go test ./internal/toolmanager`，修改路径时检查构建和运行目录规则。
