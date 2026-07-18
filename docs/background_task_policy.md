# 后台任务规范

本文定义 Electron-only 架构中的后台任务边界。旧 QThread/QWidget 规范已经退出活动架构；历史原文由 Git 保存，当前实现以 [Job Center](JOB_CENTER.md)、[导出进程规范](export_process_policy.md)和[开发规则](DEVELOPMENT_RULES.md)为准。

## 核心规则

```text
Vue Renderer
  -> FastAPI Router（DTO / 鉴权 / Service 调用）
  -> Application Service
  -> TaskApplicationService / TaskRuntime / LocalProcessAdapter
  -> Worker Process / Repository / Infrastructure
```

- Vue 只做布局、输入、轻量校验和状态绑定，不执行设备连接、数据库、大文件或 CPU 密集任务。
- Router 不创建线程、进程、数据库连接或设备 Client。
- 超过 300 ms 的网络、磁盘、解析、压缩、大查询和批量操作进入 Job Center。
- 所有导出进入独立 Export Process；普通 Job 不复制 Export 状态机。
- Worker/handler 不访问 DOM、Electron 对象、FastAPI Request/Response 或 Renderer 状态。
- SQLite connection 在任务自己的线程/进程中创建，不跨线程或进程共享。

## 任务契约

每个耗时任务必须明确：

- 稳定的 owner、task type 和可序列化参数；
- `QUEUED/RUNNING/STOPPING/COMPLETED/FAILED/CANCELLED` 等正式状态；
- 可见进度、阶段、日志、错误摘要和最终 Artifact；
- 是否支持取消、强停、重试、恢复和幂等；
- 退出时的资源清理、进程树回收和临时文件策略；
- 凭据、绝对路径和 Token 的脱敏边界。

取消必须由任务 owner 的 Application Service 确认；前端不得假取消。窗口关闭只隐藏窗口，不停止后台任务；应用退出由统一屏障停止新任务、等待受管清理并回收子进程。

## 前端轮询与实时通道

- 低频状态可通过 REST 游标/分页轮询；高频采样使用具名 WebSocket，不进入全局任务流。
- 组件卸载时必须停止 timer、订阅和 AbortController，但不得误停服务器任务。
- 页面刷新后从持久 Task/Session/Mapping 恢复，不以 Pinia、localStorage 或组件内数组作为事实源。

## 禁止项

- 恢复 PySide/PyQt/QThread/QProcess/QWidget 运行路径或测试 fixture；
- 在 Vue、Electron Main/Preload 或 Router 中复制业务状态机；
- 使用任意 shell/SQL/路径调试接口；
- 将密码、Session Token、Agent Token 或服务端绝对路径写入任务参数、日志、URL、SQLite 或 API DTO；
- 用前端提示冒充任务已启动、已取消、已导出或已持久化。
