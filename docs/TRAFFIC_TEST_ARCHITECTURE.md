# 统一流量测试架构

## 1. 当前状态

阶段 4B-2 已建立纯 Python 流量测试应用层，统一支持本地或 Windows Go Agent 执行：

- iPerf Server；
- iPerf Client（TCP/UDP、上传/下载/双向）；
- fping v5 高频 Ping。

本阶段没有 Traffic REST API、Traffic WebSocket 路由或 Vue 页面。原 Qt iPerf/Ping 页面继续可用，Online MR 页面、目标规则、会话和联动编排没有迁入通用 Traffic 服务。SNMP Center 与无线勘测继续保持 `DISABLED`。

## 2. 组件关系

```mermaid
flowchart TD
    CALLER["Future Qt / FastAPI Adapter"] --> APP["TrafficTestApplicationService"]
    APP --> TASK["TaskApplicationService / tasks.db"]
    APP --> RUNS["TrafficRunRepository / traffic_runs.sqlite"]
    APP --> LOCAL["LocalTrafficAdapter"]
    APP --> REMOTE["AgentTrafficAdapter"]
    LOCAL --> HOST["LocalProcessAdapter"]
    HOST --> WORKER["Existing background_worker / Job Registry"]
    WORKER --> IRUN["Existing IperfProcessRunner / Parser / ResultStore"]
    WORKER --> FPING["Existing fping v5 Runner"]
    REMOTE --> CLIENT["Existing AgentHttpClient"]
    CLIENT --> AGENT["Windows Go Agent"]
    SUP["AgentTrafficSupervisor"] --> REMOTE
    LOCAL --> EVENTS["TrafficEventStore / TrafficEventHub"]
    REMOTE --> EVENTS
```

没有第二套 Task Manager、Agent Client、iPerf parser 或 Python Core。Local/Agent Adapter 只负责执行差异，业务调用者统一依赖 `TrafficTestApplicationService`。

## 3. 领域模型

固定测试类型：

```text
IPERF_SERVER
IPERF_CLIENT
HIGH_FREQUENCY_PING
```

固定执行端：

```text
LOCAL
AGENT
```

统一关联字段：

```text
traffic_run_id
controller_task_id
parent_task_id
correlation_id
retry_of_traffic_run_id
```

重试总是创建新的 Traffic Run 和 Controller Task，不覆盖旧记录。iPerf Server/Client 可用 `correlation_id` 配对；`parent_task_id` 只为后续 Online MR 联动预留，阶段 4B-2 没有接入 MR 父任务。

Task 生命周期继续只有七状态：

```text
PENDING → STARTING → RUNNING → STOPPING
                         ├─ COMPLETED
                         ├─ FAILED
                         └─ CANCELLED
```

远端 `sync_state` 为 `ACTIVE / STALE / CREDENTIAL_REQUIRED / AGENT_OFFLINE / COMPLETED / ERROR`，只描述 Controller 与 Agent 的同步健康度，不是第八个 Task 状态。

## 4. 本地执行边界

本地调用链：

```text
TrafficTestApplicationService
→ LocalTrafficAdapter
→ LocalProcessAdapter
→ Existing background_worker
→ traffic_local_* handler
→ LocalTrafficAdapter worker execution
→ Existing iPerf/fping Core
```

三个 Job type：

```text
traffic_local_iperf_server
traffic_local_iperf_client
traffic_local_fping
```

`LocalProcessAdapter` 是既有 `TaskRuntime` 的纯 Python进程宿主，只负责 `Popen`、stdout/stderr 并发读取、等待、取消宽限、terminate/kill 和 shutdown。Windows 下优先使用 Job Object 的 kill-on-close 回收 Worker 及其 iPerf/fping 子进程树；绑定失败时降级到原 terminate/kill 路径。它不复制任务状态机，也不依赖 PySide6 或 FastAPI。

父进程完成回调会把 TaskRuntime 终态同步回 `TrafficRun`，包括强制停止后的 `CANCELLED` 收口和 `worker_forced_stop` 系统事件，避免本地 Run 长期停留在 `STOPPING`。

Worker stdout 只承载低频 Job JSONL；带宽区间、RTT 和丢包样本直接写 Traffic EventStore/Repository，不能进入全局 Task Event 表。fping 多目标使用独立进程和共享取消，样本按批次写 SQLite；timeout 保持 `rtt_ms=null`，没有有效样本时返回 `TRAFFIC_PARSE_FAILED`，不伪造零延迟或零丢包。

## 5. Agent 执行与凭据

Agent 启动前必须满足：

- 配置存在、未归档且启用；
- Runtime Snapshot 为 `ONLINE`；
- 对应 `iperf_server`、`iperf_client` 或 `fping` capability 为 `true`；
- `task_events` 与 `task_result` 为 `true`；
- Token 认证模式下，当前 `SessionCredentialVault` 中存在凭据。

能力只使用 Agent Runtime Snapshot，不根据操作系统名称猜测。

Token 只在 Controller 进程内、每次 HTTP 请求前读取。禁止写入：

```text
JobSpec / job JSON / command line
tasks.db / traffic_runs.sqlite
events.jsonl / raw logs / summary
Traffic DTO / Supervisor state
```

停止使用明确的 `agent_id + agent_task_id`。Controller Task ID 与 Agent Task ID 始终独立；通用 `/api/tasks/{id}/cancel` 不处理 Agent Traffic，避免页面显示成功但远端继续运行。阶段 4C 的 Traffic API 必须调用 `TrafficTestApplicationService.cancel()`。

## 6. Supervisor 与恢复

`AgentTrafficSupervisor` 提供：

```text
start
stop
attach
detach
recover_active_runs
```

它使用单一 asyncio 调度循环、有限并发、事件游标和指数退避，不为每个 Agent 任务创建永久线程。远端状态映射固定为：

```text
created   → STARTING
running   → RUNNING
stopping  → STOPPING
completed → COMPLETED
failed    → FAILED
cancelled → CANCELLED
```

Controller 已进入 `STOPPING` 后不会被远端 `running` 回退；必要时按具体远端 Task ID 幂等重发停止。未知远端状态只记录同步错误并保留最后 Task 状态，不伪造终态。

Controller 正常关闭只停止轮询并将活动映射标记为 `STALE`，不会停止 Agent 任务。恢复查询以 `traffic_agent_tasks.sync_state != COMPLETED` 为准，即使远端或 Run 已进入终态，只要 mapping 未完成仍会继续对账。重启后：

- 有 Token：从未完成映射恢复轮询并对账；
- 无 Token：标记 `CREDENTIAL_REQUIRED`，保留最后 Task 状态；
- 重新录入 Token：再次调用 `recover_active_runs()`；
- completed：必须取得 result 后才进入 Controller 完成态；
- failed/cancelled：Agent 重启导致 result 缺失时可用任务快照和错误摘要收口。

如果 Agent 启动已成功但本地登记失败，Controller Task 保持原始 `FAILED`，Run 先进入等待远端清理的失败清理态。后续远端 `cancelled` 或 `task not found` 只完成清理 mapping，不覆盖原始启动失败错误。

本地任务不能被新宿主接管；宿主 PID 失效后沿用既有规则标记 `FAILED`。

## 7. 数据边界

统一运行索引：

```text
data/sites/<site>/files/network_tools/traffic/
├─ parsed/traffic_runs.sqlite
└─ runs/<traffic_run_id>/
   ├─ events.jsonl
   ├─ summary.json
   ├─ remote_result.json
   └─ raw/
```

`traffic_runs.sqlite` 包含：

| 表 | 用途 |
| --- | --- |
| `traffic_runs` | Run、Controller Task、配置、状态、摘要和相对文件引用 |
| `traffic_agent_tasks` | Agent/Controller Task 映射、远端游标和同步状态 |
| `traffic_ping_samples` | 新独立高频 Ping 的结构化样本 |

SQLite 使用 WAL、busy timeout、foreign keys、显式事务、独立连接和幂等 schema 初始化。Ping 批量写入并用 Run/序号及目标/探测序号去重。

iPerf interval 不写入 Traffic 库。事实源继续是：

```text
data/sites/<site>/files/network_tools/iperf/parsed/iperf_results.sqlite
```

本地和 Agent iPerf 都复用现有 Python parser；Agent 重放用远端事件键幂等写 interval。`traffic_runs.local_iperf_run_id` 只保存关联。

## 8. 事件边界

每个 Controller Traffic Event 包含：

```text
sequence
timestamp
traffic_run_id
controller_task_id
source
type
payload
remote_sequence
```

`sequence` 在单 Run 内由 Controller 单调递增；Agent 原始序号单独保留为 `remote_sequence`，重复轮询不会重复镜像。事件类型为 `state / stdout / stderr / sample / summary / error / system`。

`TrafficEventHub` 使用有界队列。慢订阅者可丢弃中间绘图样本，但关键事件溢出时会断开订阅，调用者从 EventStore 游标恢复；Repository/EventStore 才是完整事实源。事件写入前会拒绝敏感键并脱敏绝对路径。

## 9. 错误与当前限制

Traffic 错误使用稳定 `TRAFFIC_*` code。启动失败、工具缺失、连接拒绝/超时、解析失败、停止超时、凭据缺失、能力不支持、远端同步和结果缺失互相区分；Task/Traffic Run 不保存 traceback 或 Token。

当前限制：

- 没有 Traffic REST API、WebSocket 路由或 Vue 页面；
- Supervisor 尚未绑定 FastAPI lifespan；
- Controller 不是 Windows Service，退出后本地任务不会继续；
- 只接入现有 Windows Go Agent，CentOS Agent 尚未实现；
- 本地高频 Ping 暂不支持指定源地址，Agent 支持强类型 `source_address`；
- 未迁移 Online MR、原 Qt iPerf/Ping、设备、AC、FIT-AP、MESH、SNMP Center 或无线勘测。

阶段 4C 只能在本架构上增加 REST/WebSocket/Vue 接入，不得把业务执行、Token、工具路径或任意命令下放到页面和路由。
