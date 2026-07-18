# Agent Windows 脚本

本目录提供 Agent 的 Windows 构建、启动和运行数据清理批处理入口。脚本只编排既有 Agent 程序和受控目录，不实现新的业务逻辑。

运行数据使用 `.local/agent/` 或系统应用数据目录，构建输出使用 `dist/agent/`。修改脚本后检查路径、编码、工具来源和 `apps/agent/README.md` 中的命令。
