# Job Center 运行时

本目录实现后台 Worker 启动、任务状态、事件分发和取消文件的运行时协议。

运行时通过 `PathResolver` 管理临时 Job 文件，并使用严格 UTF-8 Worker 协议；任务快照持久化和领域 handler 仍由 Job Center 上层负责。
