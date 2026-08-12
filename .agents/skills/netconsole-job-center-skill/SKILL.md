---
name: netconsole-job-center-skill
description: "NetConsole Job Center、后台 Job、JobSpec、BackgroundJob、JobContext、Worker Process、JSONL、进度、取消、强制停止、handler 注册或 Renderer 阻塞迁移任务时使用。纯 Excel/PDF 导出使用 netconsole-export-report-skill；简单同步 UI 更新或纯 parser 修复不使用本 Skill。"
---

# 目标

新增、迁移或修复普通后台任务，使 UI 只提交可序列化 Job 并处理标准事件，Worker Process 承载网络、磁盘、解析、批量和重计算。

# 触发与反例

触发示例：

- “把这个设备采集迁到 Job Center。”
- “新增一个 domain handler，支持进度和取消。”
- “background_worker 返回失败、取消后仍有进程或临时文件。”

不应触发：

- “新增 Excel 报告导出。”
- “只更新一个 Vue 文本状态或修复纯 parser 正则。”

# 输入与输出

- 输入：任务类型、可序列化参数、领域 service、进度阶段、取消点、结果/错误和 frozen 要求。
- 输出：Job model/handler/UI 提交链修改、生命周期说明、测试和迁移状态。
- 允许修改生产代码：允许，限 Job Center、领域 handler/service、UI 提交入口和测试；不得借迁移改设备命令、schema 或业务结果。

# 开始前读取

- `docs/ARCHITECTURE.md`、`docs/job-center/README.md`、`docs/architecture/REFACTOR_MAP.md`、`docs/job-center/BACKGROUND_TASK_POLICY.md`。
- `src/netconsole/background_worker.py`、`src/netconsole/services/background_job.py`、`src/netconsole/services/job_center/local_process_adapter.py`。
- `src/netconsole/services/job_center/`、`src/netconsole/backend/api/job_center_router.py`、`apps/desktop_renderer/src/views/job-center/JobCenterView.vue`。
- `src/netconsole/core/background_tasks.py`、`src/netconsole/core/shutdown_manager.py`、`tests/test_job_center.py`。

# 工作流程

1. 判断任务是否含网络、磁盘、大查询、解析、压缩、批量或可能超过 300ms；符合则进入 Job Center。
2. 用 `JobSpec`/兼容名 `BackgroundJob` 表达 `job_id + task_type + params + cancel_path`；参数必须可 JSON 序列化。
3. 在 `src/netconsole/services/job_center/handlers/<domain>_jobs.py` 注册 handler；新增任务不得继续堆入 `legacy_tasks.py`。
4. Worker 内创建 service、Repository、SQLite connection 和临时状态，通过 `JobContext` 报进度、日志并检查取消。
5. stdout 只输出 UTF-8 JSONL 协议事件；普通 print、设备回显和 traceback 进入 stderr/结构化日志。
6. Application Service 使用 `submit_background_job()`；Vue 通过 Task API 处理 progress、log、finished、error、cancelled 和强制停止，并在终态释放页面订阅。
7. 覆盖源码与 frozen 启动路径、取消宽限、临时 Job/cancel 文件和进程清理。
8. 分离七状态调度生命周期与业务结果；`COMPLETED` 只表示 Worker 正常收口。批量任务的部分失败/警告必须使用结构化结果驱动列表、详情、筛选、汇总和页面提示，不从日志文本推断。

# 项目约束

- 不向 Worker 传 Renderer/DOM/Electron 对象、连接对象、Repository、SQLite connection 或未序列化 model。
- Worker 不导入 Vue/Electron/FastAPI Router，不弹窗，不访问 UI。
- 当前仍有 `handlers/legacy_tasks.py` 兼容实现；它是只迁出、不迁入区域，不得描述为已全部完成迁移。
- 普通 Job Center 仍以本地 Worker Process 为主；Windows Go Agent 是独立执行端，通过 Controller/Traffic 适配接入，不等同于 Job Center 完全远程化。CentOS 离线部署和完整远程 Agent 管理仍未实现。
- 页面回调只绑定结构化结果，不做重查询、解析或导出。
- 不新增 `partial`/`warning` 作为第八个 Task 状态；用业务结果字段表达 `PARTIAL_SUCCESS/WARNING`。如果列表 `has_warning` 与详情结果不一致，必须报告为代码缺口，不能只改文案掩盖。

# 验证与失败报告

- 测试成功、空结果、业务失败、异常 traceback、取消唯一终态、强制停止、页面关闭、临时文件清理和 frozen 命令构造。
- 检查 Job 参数 JSON 序列化、stdout 无污染、数据库连接不跨进程。
- 无法验证冻结包时明确说明只验证了源码模式。
- 常见失败包括：`COMPLETED` 被误写成全部成功、列表未读取详情结果、取消/强停产生多个终态、stdout 被普通输出污染、SQLite connection 跨进程。
- 输出 task_type、注册位置、调度状态、业务结果聚合、事件/取消策略、legacy 影响、临时文件、文档同步和验证命令。

# 相关 Skills

- 修改 Task/Job/Worker 共享契约前：`netconsole-change-review-skill`。
- 导出进程：`netconsole-export-report-skill`。
- 设备 SNMP v1/v2c：遵守设备管理 Service/Task 边界；SNMP Center、MIB/OID 与 SNMPv3 已删除。
- 在线 MR 长任务：`netconsole-online-mr-skill`。
