# Job Center 服务

本目录实现后台 Job 的模型、注册表、运行器、查询、取消、事件和 Worker/进程协议。设备、采集、Traffic 等长耗时任务必须通过这里或明确的兼容边界执行。

主要入口为 `job_registry.py`、`job_runner.py`、`task_application_service.py` 和 `worker_protocol.py`；`legacy_tasks.py` 仍是兼容层，不能写成全部迁移完成。修改生命周期时运行 Job Center、Web API 和取消测试。

## 用途与边界

本目录实现后台 Job 的模型、注册、运行、查询、取消、事件和 Worker/进程协议；它承载长耗时 IO/CPU/网络，不让 Router/Vue 阻塞。

## 主要入口

`job_registry.py` 注册 handler，`job_runner.py`/`runtime/task_runtime.py` 执行，`task_application_service.py` 提供应用调用，`handlers/` 按领域提供实现。

## 依赖关系

Job Center 由 Application/API 调用，依赖 Service、Repository、LocalProcessAdapter、Export/Agent/Traffic handler；`legacy_tasks.py` 是兼容层，不代表全部已迁移。

## 数据与状态

任务快照和事件写入每局点 `tasks.db`，Worker 通过 JSONL/协议传递进度；SQLite connection 不跨进程共享，敏感 bootstrap 不进入日志。

## 测试与修改

修改生命周期、状态、取消、重试、事件或注册能力时运行 Job Center、Web API、Worker、领域 handler 和依赖层测试。

## 生成与清理

Worker/进程临时目录、事件日志和取消资源由 JobContext/PathResolver 清理；正式报告交给 Export Process，强停/失败不得删除原始证据。

## 相关文档

参见 [Job Center](../../../../docs/JOB_CENTER.md)、[后台任务策略](../../../../docs/background_task_policy.md) 和 `handlers/README.md`。
