---
name: netconsole-job-center-skill
description: "NetConsole Job Center、后台 Job、JobSpec、BackgroundJob、JobContext、QProcess、JSONL worker、进度、取消、强制停止、handler 注册或 UI 阻塞迁移任务时使用。纯 Excel/PDF 导出使用 netconsole-export-report-skill；简单同步 UI 更新或纯 parser 修复不使用本 Skill。"
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
- “只更新一个 QLabel 或修复纯 parser 正则。”

# 输入与输出

- 输入：任务类型、可序列化参数、领域 service、进度阶段、取消点、结果/错误和 frozen 要求。
- 输出：Job model/handler/UI 提交链修改、生命周期说明、测试和迁移状态。
- 允许修改生产代码：允许，限 Job Center、领域 handler/service、UI 提交入口和测试；不得借迁移改设备命令、schema 或业务结果。

# 开始前读取

- `docs/ARCHITECTURE.md`、`docs/JOB_CENTER.md`、`docs/REFACTOR_MAP.md`、`docs/background_task_policy.md`。
- `src/netconsole/background_worker.py`、`src/netconsole/services/background_job.py`、`src/netconsole/services/background_process_manager.py`。
- `src/netconsole/services/job_center/`、`src/netconsole/ui/job_action_helper.py`、`src/netconsole/ui/background_process_bridge.py`。
- `src/netconsole/core/background_tasks.py`、`src/netconsole/core/shutdown_manager.py`、`tests/test_job_center.py`。

# 工作流程

1. 判断任务是否含网络、磁盘、大查询、解析、压缩、批量或可能超过 300ms；符合则进入 Job Center。
2. 用 `JobSpec`/兼容名 `BackgroundJob` 表达 `job_id + task_type + params + cancel_path`；参数必须可 JSON 序列化。
3. 在 `src/netconsole/services/job_center/handlers/<domain>_jobs.py` 注册 handler；新增任务不得继续堆入 `legacy_tasks.py`。
4. Worker 内创建 service、Repository、SQLite connection 和临时状态，通过 `JobContext` 报进度、日志并检查取消。
5. stdout 只输出 UTF-8 JSONL 协议事件；普通 print、设备回显和 traceback 进入 stderr/结构化日志。
6. UI 使用 `submit_background_job()`，处理 progress、log、finished、error、cancelled 和强制停止，并在终态释放 controller。
7. 覆盖源码与 frozen 启动路径、取消宽限、临时 Job/cancel 文件和进程清理。

# 项目约束

- 不向 Worker 传 QWidget、QObject、连接对象、Repository、SQLite connection 或未序列化 model。
- Worker 不导入 `netconsole.ui.pages`，不弹窗，不访问 UI。
- 当前仍有 `handlers/legacy_tasks.py` 兼容实现；它是只迁出、不迁入区域，不得描述为已全部完成迁移。
- 普通 Job Center 仍以本地 Worker Process 为主；Windows Go Agent 是独立执行端，通过 Controller/Traffic 适配接入，不等同于 Job Center 完全远程化。CentOS 离线部署和完整远程 Agent 管理仍未实现。
- 页面回调只绑定结构化结果，不做重查询、解析或导出。

# 验证与失败报告

- 测试成功、空结果、业务失败、异常 traceback、取消唯一终态、强制停止、页面关闭、临时文件清理和 frozen 命令构造。
- 检查 Job 参数 JSON 序列化、stdout 无污染、数据库连接不跨进程。
- 无法验证冻结包时明确说明只验证了源码模式。
- 输出 task_type、注册位置、事件/取消策略、legacy 影响、临时文件和验证命令。

# 相关 Skills

- 导出进程：`netconsole-export-report-skill`。
- SNMP Job：`snmp-collector-design-skill`。
- 在线 MR 长任务：`netconsole-online-mr-skill`。
