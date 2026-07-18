# Agent 采集包

本目录实现采集包的打包、元数据和安全路径约束，用于把任务产生的原始结果交付给 Controller。包内容必须来自受控运行目录，不能把源码或任意本地文件打包。

主要入口为 `package.go`；包文件写入 Agent 运行数据目录。使用 `go test ./internal/packagex`，修改打包格式时同步检查 Python 导入器和清理策略。
