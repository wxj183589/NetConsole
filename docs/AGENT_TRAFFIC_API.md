# Agent 结构化流量测试协议

## 1. 当前状态

Web 演进阶段 4B-1 扩展了 Windows Go Agent 协议和 Python `AgentHttpClient`；阶段 4B-2 已增加 `TrafficTestApplicationService`、Agent 轮询、Controller/Agent 任务映射和 Traffic 数据库；阶段 4C 已在 Controller 侧增加 FastAPI Traffic 路由、独立 Traffic WebSocket 和 Vue 流量测试页面，Agent 协议本身未改变。

`ping-probe` 始终表示 TCP Connect Probe，不是 ICMP Ping。真实 ICMP 高频 Ping 使用独立任务类型 `fping`，两者不能互换或合并统计。

## 2. 认证与统一响应

所有接口继续使用可选的 `X-Agent-Token`。成功响应为 `{"ok":true,"data":...}`；新增流量协议错误在原错误对象中增加稳定 `code`，不会返回 Token、工具绝对路径以外的任意目录内容或 Go 堆栈。

本阶段常用错误码：

- `AGENT_TRAFFIC_INVALID_CONFIG`
- `AGENT_TRAFFIC_TOOL_NOT_FOUND`
- `AGENT_TRAFFIC_UNSUPPORTED`
- `AGENT_TRAFFIC_PORT_IN_USE`
- `AGENT_TRAFFIC_PROCESS_START_FAILED`
- `AGENT_TRAFFIC_PROCESS_FAILED`
- `AGENT_TRAFFIC_TASK_NOT_FOUND`
- `AGENT_TRAFFIC_EVENT_CURSOR_INVALID`
- `AGENT_TRAFFIC_RESULT_NOT_READY`
- `AGENT_TRAFFIC_OUTPUT_READ_FAILED`

## 3. 任务接口

继续复用 Agent 原任务状态：`created / running / stopping / completed / failed / cancelled`。同一 `task_type` 只允许一个活动任务；`iperf_server`、`iperf_client`、`fping` 和 `ping_probe` 分别互斥，互不阻塞。重复停止同一任务幂等返回当前快照。

```text
GET  /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/stop
GET  /api/v1/tasks/{task_id}/logs?tail=200
GET  /api/v1/tasks/{task_id}/events?after=<sequence>&limit=<n>
GET  /api/v1/tasks/{task_id}/result
```

事件游标规则：

- `sequence` 在单任务内从 1 开始单调递增；
- `after` 是排他游标，省略时等价于 0；
- `limit` 默认 200、最大 1000；
- 结果始终按 `sequence` 升序；
- 响应提供 `next_after` 和 `has_more`；
- 事件追加写入 `events.jsonl`，Agent/Controller 临时断线不会丢失已落盘事件；
- 任务结束或 Agent 重启后仍可查询已有事件。

事件类型包括 `state / stdout / stderr / sample / summary / error / system`。iPerf 只提供带时间戳的原始 stdout/stderr 事件；统一带宽、抖动和丢包指标继续由 Python `iperf_parser.py` 解析，不在 Go Agent 重写第二套解析器。

结果接口读取任务内 `result.json`，返回终态、摘要、最后事件序号和安全 artifact 描述。Artifact 只返回文件名、类型和可用状态，不返回服务器绝对路径；结果尚未生成时返回 `AGENT_TRAFFIC_RESULT_NOT_READY`。

## 4. fping

```text
POST /api/v1/fping/start
POST /api/v1/fping/stop       # 通用 stop 的薄包装
GET  /api/v1/fping/status     # 通用 active task 的薄包装
```

请求字段：

| 字段 | 约束 | fping 5.5 参数 |
| --- | --- | --- |
| `targets` | 1～64 个 IP 或主机名，去重 | 目标参数数组 |
| `interval_ms` | 1～60000，默认 100 | `-p` |
| `timeout_ms` | 1～60000，默认 100 | `-t` |
| `packet_size` | 1～65507，默认 64 | `-b` |
| `count` | 有限模式 1～1000000，默认 20 | `-c` |
| `continuous` | `true` 时 `count` 必须为 0 | `-l` |
| `source_address` | 可选合法 IP | `-S` |

命令固定使用参数数组和 Agent 配置的 `tools/windows-x64/fping/fping.exe`，不使用 Shell、不接受工具路径、输出目录、环境变量或任意附加参数。工具可用性要求同目录存在 `cygwin1.dll`，且版本检查确认 `--json` 和 `--src`。

每个任务保存：

```text
raw/fping_raw.log
raw/fping_samples.jsonl
raw/final_summary.json
events.jsonl
result.json
```

停止、失败和异常退出会尽力提交当前摘要。`packet_size` 在 Agent 和本地 Python fping Runner 中都实际传给 `-b`；本地默认与 Agent 使用相同的 1～65507 字节业务约束。

## 5. iPerf 3.21

现有 `/api/v1/iperf/server/*` 和 `/api/v1/iperf/client/*` 保持兼容。本阶段增加以下强类型参数：

- Server：`bind_address`、`port`、`report_interval`、`one_off`；
- Client：`server_host`、`server_port`、`protocol`、`duration_sec`、`parallel`、`bandwidth_mbps`、`reverse`、`bidirectional`、`report_interval`、`udp_packet_length`、`tcp_block_size`、`connect_timeout`（毫秒）。

TCP/UDP 参数分别校验；`reverse` 与 `bidirectional` 互斥；时长限定 1～86400 秒，省略时默认 10 秒，不支持无限时长。旧请求中的 `extra_args` 仅为兼容保留并继续过滤角色、后台模式和日志路径参数，已标记 deprecated；Python Typed Client 和未来 Web API 不发送或暴露它。

## 6. 能力字段

`GET /api/v1/capabilities` 新增或校准：

```text
iperf_server
iperf_client
fping
ping_probe           # 兼容字段，仍为 TCP Connect
tcp_ping_probe       # 明确语义
task_events
task_result
```

`fping` 和 iPerf 能力来自实际工具检测，不按操作系统猜测。旧 Agent 缺少新路由时，Python Typed Client 返回 `AGENT_TRAFFIC_UNSUPPORTED`。

## 7. Python Typed Client

`src/netconsole/services/agent/http_client.py` 复用现有 URL、Token、超时、重定向和错误映射，实现：

```text
start_fping
start_ping_probe
start_iperf_server
start_iperf_client
get_task
stop_task
get_task_events
get_task_result
```

DTO 位于 `src/netconsole/models/agent_traffic.py`，未知事件类型和 payload 字段保持兼容。阶段 4B-2 由 `AgentTrafficAdapter` 调用这些方法，`AgentTrafficSupervisor` 使用排他游标批量轮询；阶段 4C 浏览器路由只调用 Controller 的 `TrafficTestApplicationService`，浏览器不直连 Agent。

`start_ping_probe` 固定调用既有 `POST /api/v1/ping-probe/start`，只发送 `targets / tcp_port / interval_ms / timeout_ms / packet_size / count` 白名单字段。当前 Go Agent 的兼容 `ping_probe` 只持久化原始探测文件和任务状态，不生成 Traffic `result.json` 或 sample 事件；Controller 因此可恢复和收口任务状态，但 Agent TCP 端口探测暂不提供结构化摘要与实时样本。本阶段没有修改 Go Agent 协议。

## 8. Controller 接入边界

阶段 4B-2 已实现 `TrafficTestApplicationService`、Local/Agent Adapter、Traffic Event Hub、Controller Task/Agent Task 映射、本地 `packet_size` 修复和数据存储。现有 `iperf_results.sqlite` 继续作为 iPerf 区间事实源；`traffic_runs.sqlite` 不复制 iPerf interval，只保存运行索引、远端映射和独立 Ping 样本。

远端状态映射固定为 `created→STARTING / running→RUNNING / stopping→STOPPING / completed→COMPLETED / failed→FAILED / cancelled→CANCELLED`。未知状态只进入同步错误，不伪造 Task 终态；Controller 已进入 `STOPPING` 时不会被远端 `running` 回退。Agent iPerf/fping 完成必须先取得最终 result，失败/取消在 Agent 重启导致 result 缺失时可使用任务快照收口；兼容 `ping_probe` 按上一节限制仅以任务快照收口。

阶段 4C 只增加了受控 REST/WebSocket 与 Vue 页面，没有修改本协议，也没有新增任意 Shell/命令执行接口。
