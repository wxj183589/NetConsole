# Agent 配置模板

本目录保存可提交的 `config.example.json` 与 `targets.example.json` 等脱敏模板，用于说明字段和首次初始化形状。真实配置必须放到 Agent 本地数据目录。

模板由 Agent 配置包校验；不在此目录生成运行文件。修改字段后运行 `go test ./internal/config`，并同步检查示例与启动脚本。
