# NetConsole 分层架构

本文定义 NetConsole 当前推荐架构。新功能必须遵守本文；存量功能按 [迁移地图](REFACTOR_MAP.md) 渐进收敛，不以大规模移动文件破坏现有导入。

## 总体结构

```text
Qt6 UI
  ↓ 只负责显示、按钮、表格、进度、弹窗和页面状态
Job Center / Task Manager
  ↓ 统一提交、调度、取消、进度、日志和终态
Worker Process
  ↓ 采集、解析、导出和批量操作在独立进程执行
Domain Services
  ↓ AC / SNMP / MR / iperf / Export / Agent
Repositories / Data Store
  ↓ SQLite / 文件 / 缓存 / 报告
```

依赖只能自上而下。Domain Service、Repository、Parser、Adapter 和 Worker 不得反向导入 UI 页面。

## 各层职责

### UI Layer

- 创建和更新 QWidget / QFluentWidgets 控件。
- 收集用户输入，构造 `JobSpec`、`BackgroundJob` 或 `ExportJob`。
- 订阅 `progress / log / finished / error / cancelled`，刷新页面状态。
- 使用 ViewModel / Presenter 将结构化结果转换为可展示数据。
- 不持有跨线程、跨进程复用的 SQLite connection 或 repository。

UI 可以依赖 Job Center、ViewModel 和轻量 UI helper。页面文件只保留布局、信号绑定、轻量校验和状态刷新。

### Job Center / Task Manager

- 以 `job_id + task_type + params` 描述普通后台任务。
- 通过注册表将 `task_type` 路由到领域 handler。
- 管理任务进程、取消文件、JSONL 事件、错误和临时文件。
- 为 UI 提供 `start_job / cancel_job / is_running` 与 Qt signals。
- 不包含 AC、SNMP、MR 等具体业务规则。

### Worker Process

- 在自己的进程内创建 service、repository、数据库连接和临时状态。
- 定期检查取消标志。
- stdout 只输出 UTF-8 JSONL；stderr 只输出诊断信息。
- 只返回结构化结果，不访问 QWidget，不导入 UI page。

重 CPU、重 IO、重网络、批量采集、大日志解析和所有导出必须进入独立进程或项目已有的受治理独立进程机制。

### Domain Services

- 承载 AC、SNMP、MR、网络工具、轨道交通、Agent 等业务用例和规则。
- 可以依赖 Repository、Parser 和 Adapter。
- 不依赖 Qt UI，不弹窗，不读取表格控件。
- 不把持久化 SQL、设备输出解码或 Excel 样式散落到页面。

### Repositories / Data Store

- Repository 只负责 SQLite、文件、缓存等数据读写。
- 每个线程/进程创建自己的连接，不跨线程或进程共享。
- 路径通过 `PathResolver` 解析，不硬编码局点或用户路径。
- 主应用数据库保持稳定；解析分析输出按对应业务文档治理。

### Parser / Adapter

- Parser 只把原始输入转换为结构化数据，不访问 UI、不写报告。
- Adapter 负责 SSH、Telnet、SNMP、外部命令和编码边界。
- 设备输出优先 `utf-8-sig / utf-8`，失败后尝试 `gb18030 / gbk`；内部 worker 协议固定 UTF-8。

### Export Layer

- `ExportJob` 只携带可序列化的数据源、筛选条件、目标路径和样式参数。
- `ExportProcessManager` 管理独立导出进程。
- 导出 handler 负责生成本地 CSV/XLSX/PDF 等报告。
- 临时文件成功后原子替换目标文件；失败和取消清理不完整文件。
- 本地 XLSX 保持列宽、筛选、冻结和文本格式，兼容 WPS Office / Microsoft Office；不引入 WPS 云服务。

### Agent Boundary

- Agent 可以规划和调用受控 Domain Service / Job，但不能绕过 Job Center 操作 UI 或长任务。
- Agent 输入必须转换为可审计的 `task_type + params`，输出走同一事件协议。
- Agent 不直接持有 QWidget、数据库连接、凭据对象或未序列化 model。
- Agent 自动化必须遵守功能开关、权限、取消、日志和现场数据边界。

## 强制依赖规则

- UI → Job Center / ViewModel / 轻量 UI helper。
- Job Center → Domain Service handler。
- Domain Service → Repository / Parser / Adapter。
- Repository → 数据存储。
- Parser → 纯解析依赖。
- Export → 数据源和报告生成依赖。
- Domain Service 禁止依赖 UI。
- Worker Process 禁止导入 `netconsole.ui.pages`。

## 明确禁止

- 页面内直接 SSH、Telnet、Netmiko、SNMP Walk 或外部网络请求。
- 页面内直接生成 Excel/CSV/PDF、写 `Workbook.save()` 或 `to_excel()`。
- 页面内直接解析大文件日志、递归扫描目录、压缩打包。
- 页面内执行长时间数据库扫描、大批量 SQL 或数据转换。
- 页面内继续新增零散 QThread/QProcess；仅明确的实时 UI 采样展示可例外，且必须有退出治理。
- 向单个无限增长的 if/elif dispatcher 追加任务。

## 明确允许

- UI 创建 `JobSpec / BackgroundJob / ExportJob`。
- UI 调用 `submit_background_job()` 或 `submit_export_task()`。
- UI 订阅进度和终态事件。
- UI 使用 ViewModel / Presenter 展示结构化结果。
- 小于 300ms、无网络/重 IO、结果规模明确的轻量校验和状态变更留在 UI。

## 新功能模板

```text
netconsole/
  ui/pages/<feature>_page.py           # 布局、信号、状态
  ui/<feature>_view_model.py           # 可选，展示转换
  services/job_center/handlers/<domain>_jobs.py
  services/<domain>/<feature>_service.py
  repositories/<feature>_repository.py
  parsers/<feature>_parser.py          # 如需要
  tests/test_<feature>.py
```

开发步骤：

1. 判断任务是否可能超过 300ms，或是否包含网络、磁盘、大查询、解析、批量处理。
2. 在领域 handler 注册新的 `task_type`，禁止修改兼容 dispatcher。
3. handler 通过 `JobContext` 获取 params、路径、进度和取消。
4. Worker 内创建 service/repository，输出结构化 result。
5. UI 只提交 Job 并处理五类事件。
6. 导出另建 `ExportJob`，不得把全量表格行从 UI 传入进程。
7. 补成功、空数据、失败、取消和冻结模式验证。

