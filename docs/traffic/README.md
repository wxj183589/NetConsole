# 统一流量测试

## 1. 当前边界

Traffic 是 NetConsole 的本机流量测试能力，统一承载本地 iPerf Server/Client、高频 Ping、TCP 端口探测、事件、样本、摘要、任务关联和历史查询。独立 Windows Go Agent、AgentTrafficAdapter、AgentSupervisor、远程 iPerf、远端任务映射和远程结果同步已在 v1.5.13 退役；v1.5.14 继续维持本机能力边界。

当前调用链为：

```text
Vue Renderer
    ↓ REST / WebSocket
FastAPI traffic_router
    ↓
TrafficWebApplicationService
    ↓
TrafficTestApplicationService
    ↓
LocalTrafficAdapter / TrafficEventStore / TrafficRunRepository
```

Renderer 只能提交 `LOCAL` 执行目标；Backend 不启动、轮询或关闭外部 Agent。历史 Traffic 记录中的 `executor_kind`、`agent_id`、`traffic_agent_tasks` 和旧同步字段仅作数据库兼容读取，不新增记录、不恢复远端任务。

## 2. 当前 API

- `GET /api/traffic/execution-targets`：只返回 `LOCAL`；
- `POST /api/traffic/iperf/server`：启动本机 iPerf Server；
- `POST /api/traffic/iperf/client`：启动本机 iPerf Client；
- `POST /api/traffic/fping`：启动本机高频 Ping；
- `GET /api/traffic/runs`、`/{id}`、`/summary`、`/events`、`/ping-samples`：查询本机运行和历史事实；
- `POST /api/traffic/runs/{id}/cancel`、`/retry`：取消或重试本机运行；
- `/ws/traffic/{id}`：只推送本机运行的增量事件、样本和心跳。

历史远端执行目标提交会返回 `TRAFFIC_EXECUTION_TARGET_INVALID` 或等价的本机-only 错误，不会创建新的 Run、Task 或映射。

## 3. 数据边界

```text
<data_root>/sites/<site>/files/network_tools/traffic/
├─ parsed/traffic_runs.sqlite
└─ runs/<traffic_run_id>/
   ├─ events.jsonl
   ├─ summary.json
   └─ raw/
```

`traffic_runs.sqlite` 保留旧列和旧表以读取历史数据库；新的本机运行只写 `traffic_runs`、`traffic_ping_samples` 及既有本地事件/摘要，不写 `traffic_agent_tasks`。iPerf interval 事实仍由 `network_tools/iperf/parsed/iperf_results.sqlite` 保存。

## 4. 生命周期

本机任务由 `TrafficTestApplicationService` 管理，`LocalTrafficAdapter` 负责子进程、事件、取消、超时和终态收口。Backend 关闭只等待本机适配器和事件流，不等待远端执行端。重复取消保持终态幂等；重试只创建新的本机 Run，并保留 `retry_of_traffic_run_id` 关联。

## 5. 修改与测试

修改阈值、事件、取消/重试、恢复、API 或 Renderer 时，运行 Traffic Application、Repository、API、WebSocket、Renderer 和相关 Job Center 测试。不要恢复 `apps/agent`、`agent_adapter.py`、`agent_supervisor.py`、Agent API/WebSocket 或远程执行 Feature。

相关代码：

- `src/netconsole/services/traffic/application_service.py`
- `src/netconsole/services/traffic/local_adapter.py`
- `src/netconsole/services/traffic/web_application_service.py`
- `src/netconsole/backend/api/traffic_router.py`
- `src/netconsole/repositories/traffic_run_repository.py`
