# Job Center 使用说明

Electron 提供复用现有 Vue/FastAPI/Core 的独立统一任务窗口。设备管理和配置采集主页只保留紧凑摘要与打开入口；文件管理保留领域下载队列，但通用日志、跨模块筛选和统一详情仍进入任务窗口。停止、重试、Artifact 下载和本机打开动作必须由任务 owner capability 明确授权，未支持能力不得假成功。统一取消只调用对应 owner 的既有 Application Service，owner 未接线时禁用；`STOPPING` 只在 owner 已确认停止请求后返回。设备 Export 还必须同时持有当前进程内的受管 Export spec、与持久化 `ExportJob` 一致的专用 cancel 路径和仍活跃的受管进程，服务重建、spec/进程丢失或终态竞态均拒绝写 `STOPPING`。统一任务的 `message/error/error_summary/phase/stage` 等文本，以及日志的嵌套 `message/error/traceback/diagnostic/state/stage`，在 DTO 输出前统一脱敏 Windows/UNC 绝对路径；Artifact DTO 固定为安全 ID、显示名、大小、类型和受控 endpoint。关闭任务窗口不改变后台任务生命周期。

独立窗口加载 `/desktop/tasks`，使用精简 `TaskWindowLayout`，但继续复用同一 `JobCenterView`、`useTaskStore` 和 Task API；主窗口 `/tasks` 仍使用正式应用 Shell。Main 先显示“正在加载任务中心”状态页，随后等待目标页面 `did-finish-load`、Vue mounted、解析主题和 Job Center interactive 四项信号。IPC 只有全部满足时返回 `success: true`；导航失败、渲染进程退出、无响应或 10 秒超时返回 `success: false` 并显示可重试错误页。错误页可在主窗口打开 `/tasks`，页面调用方收到失败结果也会回退主窗口路由。任务 ID 和模块只进入白名单 query，桌面日志只记录生命周期事件，不记录 query、Token 或本机路径。

Job Center 是普通后台任务的统一调度层；Export Process 是共享同一事件协议的专用导出通道。

> 2026-07-14 代码核对：Registry 当前注册 88 个 task type，分布于 11 个领域 handler 模块。新增三个本地 Traffic handler及两个 Online MR Agent 包同步/导入 handler；注册与进程协议已统一，但多数既有 handler 仍经 `legacy_tasks.py` 薄适配，领域迁移未完成。设备批量连接测试和批量详情采集仍是专用线程路径，不属于 Job Center。

## 代码组成

- `job_models.py`：`JobSpec / BackgroundJob / JobResult / JobProgress / JobError`。
- `job_events.py`：五类标准事件构造函数。
- `job_context.py`：params、progress、cancel、`PathResolver`。
- `job_registry.py`：`task_type → handler` 注册和分发。
- `job_runner.py`：统一捕获取消、异常和 traceback。
- `worker_protocol.py`：UTF-8 JSONL 编码、解析和分块缓冲。
- `services/job_center/runtime/task_state.py`：`PENDING / STARTING / RUNNING / STOPPING / COMPLETED / FAILED / CANCELLED` 状态契约。
- `services/job_center/runtime/task_event_hub.py`：统一任务 Worker/Service 事件并提供 WebSocket stream；Agent 配置和健康状态使用独立 `AgentEventHub`。
- `services/job_center/runtime/task_runtime.py`：Job/取消文件、JSONL 分块解析、状态、终态和清理；提供 `TaskApplicationService`。
- `task_application_service.py`：任务应用层、快照更新、恢复核对和跨进程协作取消。
- `repositories/task_repository.py`：每局点 `tasks.db` 的快照、事件、WAL 和查询。
- `repositories/online_mr_task_session_repository.py`：复用同一局点 `tasks.db` 保存 Online MR Controller Task 与 Session 的最小映射，不保存连接配置或凭据。
- 历史 `src/netconsole/ui/job_process_manager.py` 已删除；其状态、取消和事件职责分别由永久 Service/Runtime/Adapter 承担，旧路径只在最终迁移矩阵中追溯。
- `local_process_adapter.py`：纯 Python Worker 进程宿主，复用同一 `TaskApplicationService/TaskRuntime`，供非 Qt 应用层启动本地 Job；stdout/stderr 使用可用字节增量读取，不能等到 64 KiB 缓冲区填满或进程退出后才发布 JSONL 事件。Windows 下使用 Job Object 回收子进程树，并通过完成回调同步外部业务 Run 终态。`force_stop_job()` 只在业务层有界协作停止失败后立即 terminate/kill 进程树，不替代普通取消。
- `handlers/`：AC、配置、设备、文件、Mesh、网络、在线 MR、轨道交通、Traffic 领域分区；网络工具无线扫描的既有任务由独立兼容 handler 承接。

文件管理下载仍以 `tasks.db` 为状态 SSOT。文件页面恢复时由 `TaskRepository` 在 SQL 层按
`file_management_download + web_file_management + local + site/status` 组合过滤，活动任务优先；本批任务
的 descriptor、hidden、waiting 事件一次查询并聚合，不遍历其他领域历史，也不逐任务读取完整事件流。

## Worker Process 约束

- 普通任务由 `background_worker.py` 执行，导出由 `export_worker.py` 执行。
- Worker Process 不导入 Renderer、Electron 或 FastAPI 对象，也不访问 DOM。
- 网络、重 IO、重 CPU、解析和批量操作在进程内创建自己的 service/repository/数据库连接。
- stdout 只写统一 JSONL，原始日志和诊断信息进入 stderr 或结构化 log event。

### 一次性敏感 bootstrap

设备新增/编辑表单的未保存连接测试复用同一 `LocalProcessAdapter -> background_worker -> device_connection_test` 链路。Job 参数和 Job JSON 只保存地址、端口、用户名、厂商/类型、跳板元数据、`device_uuid` 与 `saved_device / ephemeral / none` 凭据来源；临时密码不进入参数、`tasks.db`、事件、日志或结果。`saved_device` 由 Worker 按 `device_uuid` 从设备 Repository 解析，`ephemeral` 由宿主通过 Worker stdin 的一次性敏感 bootstrap 注入。

敏感 bootstrap 不写临时文件、环境变量或 SQLite，只允许单次消费；宿主写入后、Worker 消费后以及任务完成/失败/取消时均清空受管缓冲和临时 Device 密钥字段。需要临时凭据的任务在宿主异常退出后不得恢复：恢复核对将其安全标记为失败并要求用户重新提交。该通道属于共享 Job Runtime 能力，不授权 Renderer 直连设备，也不允许用 base64、普通 Job 参数或独立线程绕过任务中心。

## 模型关系

- `JobSpec` 是普通后台任务的正式模型。
- `BackgroundJob` 是 `JobSpec` 的兼容名称，旧导入继续有效。
- 永久入口是 `TaskApplicationService`、`TaskRuntime`、`LocalProcessAdapter` 与领域 handler；已删除的 Qt Manager/Adapter 名称不得重新作为兼容入口。
- `ExportJob` 是导出专用模型，增加 output/tmp/db/filter/context 等字段。
- 两类任务共享事件字段和 JSONL 解析，但使用不同 worker 和 manager，避免导出规则污染普通任务。
- 七状态是宿主生命周期契约，不改写 Worker 的五类既有 JSONL 事件；现有页面继续消费 `progress/log/finished/error/cancelled`。
- 当前已提供任务历史、TaskRepository、FastAPI 任务路由和 WebSocket；阶段 4B-2 允许 `TaskApplicationService.create_external_task/record_external_event` 将 Agent Traffic 映射到同一任务中心，但它仍不是独立 Controller daemon。

## Online MR Application 映射

阶段 5B-2A 的 `OnlineMrApplicationService` 是纯 Python LOCAL 启动边界。它通过 `LocalProcessAdapter` 提交既有 `online_mr_collection_start` Job，并把 `site_name`、`device`、`device_id` 和 owner 作为顶层任务摘要传入，避免 Task Center 从嵌套连接配置推断归属。创建任务前先在所属局点 `tasks.db` 写入可空 Session 映射；采集侧创建会话后发出 `online_mr_session_created`，应用层再幂等关联 Session。

Online MR 业务阶段使用 `OnlineMrPhase`，不会扩展七状态 Task 契约。启动连接失败时 Task 为 `FAILED`，已创建会话 metadata 同步为 `FAILED`；显式恢复核对可将没有活动 Task 宿主的旧会话标为 `ABORTED`，但不触发解析、打包或 raw 清理。

LOCAL 入口通过 Worker 内纯 Python `OnlineMrTrafficCoordinator` 管理 fping/iPerf；普通停止、显式时长到期和 SSH 异常都必须等 Traffic 与 SSH writer 收口后才写 metadata、发布 ZIP 并结束 Task。`stop_operation()` 使用协作取消；`force_stop_operation()` 先短暂协作等待，再调用有界进程树强停。`online_mr_task_sessions` schema v2 保存实际时长、停止原因、强停标记和错误摘要；Task/Session/Mapping 终态由同一应用服务幂等 reconcile，重复停止不得二次取消或重复生成 ZIP。

`online_mr_agent_packages_sync` 和 `online_mr_agent_package_import` 是两个一次性 Job。前者只读 Agent 状态、工具、包及当前局点设备候选；后者只下载并导入用户选中的既有包。认证 Token 只通过受管进程的临时环境传递，任务参数和 Job 文件只保存 Profile ID、地址和非敏感选项。取消检查继续传入流式下载；远程任务 start/stop 不在这两个 handler 中。

## Task Center API

- `GET /api/tasks`：任务列表，可按七状态过滤；
- `GET /api/tasks/{id}`：任务详情；
- `GET /api/tasks/{id}/events`：结构化状态、进度和日志事件；
- `POST /api/tasks/{id}/cancel`：只对本地 Runtime-backed 任务写协作取消并进入 `STOPPING`；Agent Traffic 必须由后续 Traffic API 调用 `TrafficTestApplicationService.cancel()`，通用任务 API 不会伪造远端停止成功；
- `/ws/tasks`：初始快照与 Event Hub/SQLite 增量事件。

本地 Worker 由宿主进程持有。正常关闭宿主会走既有取消/清理；崩溃后重启会将失去 PID 宿主的活动快照核对为 `FAILED`。任务中心不得仅依据旧数据库状态显示伪 `RUNNING`。

Worker 内为只读映射恢复临时创建的 `TaskApplicationService` 必须关闭启动期孤儿回收；只有宿主进程可以核对并回收宿主所有的活动任务，避免子进程把仍存活的父任务误判为遗留任务。

## 事件协议

每个事件至少包含：

```text
type, job_id, stage, current, total, message,
result, error, traceback, cancelled
```

进度：

```json
{"type":"progress","job_id":"a1","stage":"query","current":20,"total":100,"message":"正在查询","result":null,"error":"","traceback":"","cancelled":false}
```

`progress` 可选携带 JSON `details`，仅用于同一任务的可恢复计数，不增加新事件类型或第二套状态机。例如安全清理使用 `processed_files/deleted_files/failed_count/freed_bytes`；普通 handler 继续传字符串 `message`，现有消费者保持兼容。任务取消仍只产生一个 `cancelled` 终态，最后一条持久进度可用于恢复取消前的部分计数。

日志：

```json
{"type":"log","job_id":"a1","stage":"query","current":0,"total":0,"message":"已读取缓存","result":null,"error":"","traceback":"","cancelled":false,"level":"info"}
```

完成：

```json
{"type":"finished","job_id":"a1","stage":"","current":0,"total":0,"message":"后台任务完成","result":{"rows":[],"total":0},"error":"","traceback":"","cancelled":false}
```

`finished` 可选携带 `terminal_state=COMPLETED|FAILED|CANCELLED`。它只用于 Worker 已正常返回、仍需保留结构化 `result`，但业务结果应落成失败或取消终态的场景；未提供时仍按 `COMPLETED` 处理，不新增事件类型。

失败：

```json
{"type":"error","job_id":"a1","stage":"","current":0,"total":0,"message":"连接设备失败","result":null,"error":"连接设备失败","traceback":"...","cancelled":false}
```

取消：

```json
{"type":"cancelled","job_id":"a1","stage":"","current":0,"total":0,"message":"后台任务已取消","result":null,"error":"后台任务已取消","traceback":"","cancelled":true}
```

stdout 不得混入设备原始回显或普通 print；诊断内容写 stderr。

## 新增后台任务

1. 在对应领域 service 实现业务用例。
2. 在 `handlers/<domain>_jobs.py` 新增接收 `JobContext` 的 handler。
3. 将 `task_type` 加入该模块 `HANDLERS`，禁止改兼容 dispatcher。
4. 在循环、批量和阶段边界调用 `context.check_cancelled()` 与 `context.progress(...)`。
5. 返回 JSON 可序列化 dict。

需要保留统计结果但让任务终态不是 `COMPLETED` 的 handler，可在返回 dict 中加入 `terminal_state`；`JobRunner` 会提升到 `finished` 事件字段并从 `result` 中移除。

```python
def device_status_refresh(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    context.progress("connect", 0, 1, "正在连接设备")
    service = DeviceStatusService(context.paths)
    result = service.refresh(dict(context.params))
    return {"device": result}

HANDLERS["device_status_refresh"] = device_status_refresh
```

应用日志与安全维护复用 `system_maintenance_cleanup`：扫描只返回白名单候选，正式清理必须携带 1～365 天、非空且不重复的类别白名单和明确确认。自动模式固定只选择 `runtime_logs`，不自动清理缓存、临时文件或任何局点业务日志；同一数据根使用跨进程认领，成功后 24 小时内不重复提交，持续运行的 Backend 每 24 小时复查。Worker 按每条记录时间流式过滤当前日志，删除前重新扫描，并在每项后写带 `details` 的标准进度；取消保留未处理文件。CSV/TXT/XLSX 通过现有 Export Process 和公共 `WebArtifactStore` 最终化，Task DTO 与 Renderer 只获得安全显示名和 Artifact ID，不获得服务端物理路径。

## 从 Vue 提交普通任务

Vue 只向具名 FastAPI endpoint 提交白名单 DTO；Router 调用对应 Application Service 创建或复用 Job，并返回安全 task id/状态。页面通过 Task API 或 WebSocket 恢复状态，取消时调用 owner 的正式取消入口。页面不得自行创建进程、解析 JSONL 或在完成回调中做重查询/解析。

## 新增导出任务

1. 在 `services/export/export_handlers.py` 或专用导出 service 实现 handler。
2. UI 只传筛选、业务 ID、格式和明确确认；数据库路径、临时输出根与 Artifact 由 Application Service 解析。
3. 由导出进程读取数据、生成临时文件、完成后替换目标文件。
4. 通过同一 JSONL 协议回传进度和终态。

不得从 Renderer 当前表格遍历无上限行后塞进 Job。小型静态数据的 inline 例外必须符合现有导出 builder 限制。

## 取消任务

- 普通任务：调用 owner Application Service 的 `cancel` 入口。
- 导出任务：调用 Export Application Service 的专用取消入口，且必须确认受管 spec/进程仍存在。
- manager 写入 UTF-8 取消文件并请求进程退出；超时后 kill。
- handler 应在批次边界检查取消文件，返回 cancelled 终态。
- 失败/取消后 manager 清理 Job、cancel 和临时输出文件。

## 统一 Traffic Job

- 本地类型固定为 `traffic_local_iperf_server / traffic_local_iperf_client / traffic_local_fping`，handler 只调用 `LocalTrafficAdapter`；
- Controller 侧 `LocalProcessAdapter` 只负责 `Popen`、双管道读取、等待、Job Object 进程树回收和 terminate/kill，状态仍由既有 `TaskApplicationService/TaskRuntime` 管理；`shutdown(timeout_seconds)` 的 timeout 是取消派发、协作等待、terminate、kill 和最终状态收口共用的总预算，不再按阶段累加；取消持久化或磁盘写入变慢时不会阻塞宿主超过 deadline；`prepare/Popen/mark_running` 不持有状态锁，关闭与慢启动并发时会拒绝登记并立即回收新进程；Traffic 只订阅完成回调同步自身 Run 终态；
- Worker Job JSON、Task 快照和日志不得写入设备密码、Community 或临时凭据；确需向本地 Worker 传递时，只能通过带长度上限的一次性 stdin 敏感启动帧，消费后清零字节缓冲。敏感启动帧丢失时任务明确失败，不得从 Task 数据恢复或把凭据降级写入参数。
- Worker stdout 只返回低频进度、摘要和唯一终态；iPerf interval、RTT、丢包和原始区间直接写 `TrafficEventStore`/业务 Repository，不进入全局 Task Event 表；
- Agent Traffic 不进入 Worker Process。`AgentTrafficSupervisor` 在持有会话凭据的 Controller 进程内轮询，并通过外部任务入口持久化状态；
- Agent Task 使用 `source=agent, owner_pid=0`，因此不会被本地 orphan 核对误判；本地 Traffic 继续沿用宿主 PID 退出后标记 `FAILED` 的规则；
- `sync_state` 只表示远端同步健康度，不是第八个 Task 生命周期状态。完整边界见 [统一流量测试架构](TRAFFIC_TEST_ARCHITECTURE.md)。

## 在线 MR 长运行 Job

- `online_mr_collection_start` 是持续运行的本地 Worker Process 任务，而不是一次性查询；任务建立 SSH 会话后持续采集并把状态作为 JSONL progress 事件返回。
- 页面只提交可序列化配置。设备连接目标由 Worker 使用自己的 repository/数据库连接重建，页面不携带 Netmiko 会话对象。
- terminal monitor、隐藏 probe 模式和 ar5drv 命令序列集中在 `src/netconsole/services/online_mr/collection_commands.py`，原始设备回显只写 session 的 UTF-8 raw log。
- 用户停止由对应 owner Application Service 请求 TaskRuntime 写入协作取消。在线 MR 使用可配置的清理宽限期，让 handler 关闭采集循环、SSH 和文件句柄、更新会话状态并完成打包；超时再由 LocalProcessAdapter 强制回收进程树。
- 停止后的压缩包原子写入 session 的 `outputs` 目录；失败时删除临时包但保留完整 session/raw 目录。
- Vue 可通过受控游标轮询或 WebSocket 跟踪日志尾部，但不得在 Renderer 做大文件解析。手动和实时解析使用 `online_mr_parse` Job，分析报告使用 Export Process。
- 当前执行端仍是本地 Worker Process，未实现 Windows/CentOS Agent；命令、配置、路径、会话与打包均已脱离 UI，为后续替换执行端保留边界。

## AC 资源刷新 Job

- `ac_fit_ap_resources_refresh` 保持原 task_type；`mode=load` 读取现有资源，`mode=collect` 通过 `AcService / AcResourceService` 执行设备采集，兼容旧调用方。
- 页面不再创建 `AcResourceCollectThread`。Worker 内加载 AC 设备、创建 repository，并调用已有 `collect_h3c_fit_ap_resources` 完成 AP 列表、状态、地址、Radio、BSSID 和 LLDP 采集解析。
- `source=auto` 只选择已验证的数据策略。当前 H3C AP 资源由 CLI 信息最完整，因此默认继续使用 CLI；不得因架构迁移强制改成 SNMP。
- AC Domain 只接受现有 H3C CLI 采集；`source=snmp` 必须明确拒绝，不能借设备管理 SNMP v1/v2c 基础识别恢复 AC SNMP 采集。
- CLI 原始回显、命令 JSONL、collect run、parser 和 repository 写入规则保持原状。命令失败转换为 Job error，用户取消转换为唯一 cancelled 终态。
- AP 统一模型和轨旁业务不属于本阶段，继续使用现有专用服务。

## AC 光衰刷新 Job

- `ac_fit_ap_optical_refresh` 保持原 task_type；`mode=load` 读取并关联现有光衰，`mode=collect` 在 Worker 内调用 `AcOpticalService`。`refresh_scope=all/single` 分别承载全量和单 AP 刷新，不增加平行 task_type。
- 页面不再创建 `FitApOpticalCollectThread`，只提交 device/AP 标识、并发、来源和取消宽限期，并在 finished/failed/cancelled 后恢复按钮。未显式传入并发时默认使用共享 FIT-AP 光衰并发 64；旧设置或旧调用传入 1000/200 时，Worker 仍按目标 AP 数、用户请求值和当前平台安全上限裁剪实际 worker 数。
- `AcOpticalService` 继续调用既有 `collect_h3c_fit_ap_optical`；AP 控制台启用、Telnet 命令、解析、重试、历史合并、raw log 和 repository 写入语义均不改变。
- AP 在线/离线关联和交换机侧光模块状态在 Domain 层合并。交换机侧无光不直接改写在线 AP 的 AP 侧异常；AP 离线仍按现有状态映射为历史光衰展示。
- 采集取消转换为唯一 cancelled 终态；全部失败转换为结构化 error；部分失败以 finished 返回 `partial_success/failed_aps`，便于 UI 保留现有结果并提示。
- `ac_fit_ap_optical_refresh` 与轨旁 `trackside_ap_optical_update` 对同一 `site_id + ac_device_uuid + fit_ap_optical` 写入 `resource_keys`，`TaskApplicationService` 通过所属局点 `tasks.db` 的 `BEGIN IMMEDIATE` 原子检查和保存阻止同一 AC 重复光衰任务；任务进入 completed/failed/cancelled 或重启 orphan reconcile 后即释放占用，不使用永久文件锁。
- 轨旁 `trackside_ap_optical_update` 的业务结果 `status` 使用 `SUCCESS / PARTIAL_SUCCESS / FAILED / NO_TARGET / CANCELLED`；其中 `FAILED/CANCELLED` 通过 `finished.terminal_state` 映射为 Task 终态，仍保留 `success_count/failed_count/target_count` 等统计。
- 光衰采集结果的 `collection` 会返回 `requested_concurrency`、`effective_concurrency`、`platform_concurrency_limit` 和 `round_summaries`，用于诊断旧并发配置是否被裁剪以及重试轮次是否下降。
- FIT-AP/AP 侧光衰采集会通过同一 `progress.details` 携带单 AP 结构化事件，不新增事件类型。轨旁 `trackside_ap_optical_update` 和 AC `ac_fit_ap_optical_refresh` 均可收到 `plan_ready / ap_started / ap_completed / ap_retry_started`，字段包含 `phase/event/round/index/total/completed/ap_uuid/ap_name/ap_mac/ap_ip/station/status/reason_code/error_message/rx_power/tx_power/elapsed_ms/success_count/failed_count/effective_concurrency`。任务窗口只展示阶段、当前 AP、单 AP 结果、重试、摘要和必要失败原因；原始 CLI 回显继续写入采集 raw log，不灌入任务中心日志。
- 轨旁光衰更新的总体进度由交换机分支、FIT-AP 分支和最终保存/聚合步骤共同聚合；FIT-AP 目标数未确认前不能只按交换机数报满，运行态快照带 `prevent_running_100` 时最多显示 99%，只有任务终态事件才显示 100%。
- 本阶段不修改数据库 schema、AP 统一模型、轨旁 AP 业务或 MR/Mesh；旧 MIB/SNMP Collection 已在后续 E6A 阶段删除。

## AC 命令动作 Job

- `ac_command_action_execute` 统一承载现有 AC 命令动作，动作由 `action` 参数区分，不为固化 AP、远程登入、保存等动作增加细碎 task_type。
- 页面保留危险动作确认弹窗，并提交 device/action/command_sequence/confirm_required 等可序列化参数；页面不再创建 `AcCommandActionThread` 或直接执行 CLI。
- 页面关闭或切换 AC 功能页时请求取消当前命令动作 Job，终态统一恢复按钮，避免遗留命令进程或把取消误报为失败。
- `AcCommandService` 复用 `H3cAcCommandProfile` 和 `run_h3c_ac_action`。固化新上线 AP 保留 `system-view → wlan auto-ap persistent all → save force → return → quit`；开启 AP 远程登入保留 `screen-length disable → system-view → probe → wlan ap-execute all exec-console enable → return → quit`。
- 原有命令白名单、逐命令超时、提示符/命令回显处理、尾部 read-timeout 特殊成功判定、连接清理、raw log 和 commands JSONL 均保持不变。
- `custom_sequence` 只接受与已验证动作完全一致的命令序列，禁止借统一任务开放任意配置命令。
- 连接、认证、超时、设备命令和保存错误由 Domain 返回结构化错误；handler 转换为标准 error 终态，用户取消转换为唯一 cancelled 终态。
- Worker stdout 只输出 UTF-8 JSONL。设备普通输出即使被旧执行器 print，也会被 background worker 重定向到诊断通道；结构化 command result 可作为 JSON 字段返回。
- 本阶段不迁移 AP 统一模型、轨旁业务、光衰规则、MR/Mesh、Online MR 或 Agent；旧 MIB/SNMP 平台已在后续 E6A 阶段删除。

## 避免 UI 卡死

- UI 不直接等待进程，不调用 `subprocess.wait()`。
- LocalProcessAdapter 对 stdout/stderr 做可用字节增量读取，不等待缓冲区填满或进程退出。
- 大表结果分页或写入结果文件，避免通过 signal 传输超大对象。
- progress slot 只更新控件，不执行查询、解析、导出或逐行昂贵布局刷新。

## Frozen / PyInstaller / Nuitka

- 开发模式普通 worker：`python -m netconsole.background_worker --job <job.json>`。
- 开发模式导出 worker：`python -m netconsole.export_worker --job <job.json>`。
- frozen 普通 worker：`NetConsole.exe --background-worker --job <job.json>`。
- frozen 导出 worker：`NetConsole.exe --export-worker --job <job.json>`。
- `main.py` 必须在加载 UI 前处理 worker 参数。
- manager 在开发模式补充项目代码根到 PYTHONPATH；冻结模式使用应用根。

## 临时文件与取消文件

- Job JSON 和 cancel 文件位于 `.local/runtime/cache/background_jobs` 或 `.local/runtime/cache/export_jobs`。
- 导出先写目标旁的 `.tmp` 文件。
- 成功后使用原子替换；异常、取消、启动失败和进程退出均执行清理。
- 占用错误保留“关闭 WPS/Excel 后重试”的用户提示。

## 永久任务接入核对

1. 标记业务操作的输入、进度、结果、错误、取消和恢复语义。
2. 将重逻辑放入 Application/Domain Service 或 Export handler。
3. 用 Job/ExportJob 表达最小可序列化输入。
4. 复用统一 Service/Runtime/Adapter，不在页面创建进程或解析 JSONL。
5. 回归成功、失败、取消、窗口关闭、应用退出和冻结模式。

完成不能只以“已注册 task type”为依据。还需确认生产页面已接线、owner capability 正确、取消/失败/恢复/冻结态经过验证，且不存在第二套状态源。当前状态见[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)。

## 禁止事项

- Worker/handler 不得操作 DOM/Electron 对象或持有页面对象。
- Job params 不得传 SQLite connection、Repository/Client 实例、Renderer/Electron 对象或不可 JSON 序列化对象。
- 子进程协议 stdout 不得混入普通 print、设备回显或第三方库输出；诊断统一进入 stderr/日志。
- 不得绕开 `.cancel` 和 manager 生命周期另造取消语义，也不得同时发出 finished/failed/cancelled 多个终态。
- 不得在 Renderer 执行大型 Excel/CSV/PDF/图片导出；正式文件导出统一走 Export Process。
