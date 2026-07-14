# Online MR Agent 远程执行器

## 当前状态

阶段 5B-13A 已在 Python Controller 中实现单 Agent、单 MR 的远程执行闭环。能力默认关闭，只有设置 `ONLINE_MR_AGENT_EXECUTOR_ENABLED=1` 后，`OnlineMrApplicationService` 才允许 `executor=AGENT`；关闭时稳定返回 `ONLINE_MR_AGENT_EXECUTOR_DISABLED`。

本阶段只增加 Application Service 执行端，不在 Qt、FastAPI 或 Vue 中新增 Agent start/stop 控制入口，也不修改 Go Agent、MR 命令、LOCAL 生命周期、raw 文件名或报告逻辑。

## 组件与依赖

```text
Qt / API（后续入口）
        │
OnlineMrApplicationService
        ├─ LOCAL → LocalProcessAdapter → Online MR Worker
        └─ AGENT → OnlineMrAgentExecutor
                     ├─ Agent Profile + SessionCredentialVault
                     ├─ 固定 Agent HTTP 路由
                     ├─ Task / Mapping 状态收敛
                     └─ DownloadService → PackageImporter → Session
```

LOCAL 与 AGENT 共用 `OnlineMrStartRequest`、统一操作快照和 Task/Session/Mapping 外层模型，但执行器完全隔离。Agent 执行器位于 `src/netconsole/services/online_mr/agent_executor.py`，不创建本地 Worker，不复用 LOCAL 取消或强停路径。

## 启动安全条件

启动前按以下顺序完成校验：

1. 全局开关为 `1`；
2. 请求只指定一个已配置且启用的 Agent Profile；
3. Agent URL 只从 Profile 读取，并继续经过根 URL 规范化；
4. Token 只从进程内 `SessionCredentialVault` 读取；
5. 依次检查 ping、status/version、tools；
6. `mr_collector` 必须 ready；启用 fping/iPerf 时相应工具必须 ready；
7. 当前局点、设备 ID、设备名和主/备静态地址必须与正式设备库一致；
8. 同一设备的 LOCAL/AGENT Mapping 不得并发，且本阶段全 Controller 只允许一个活动 AGENT Online MR。

兼容版本当前接受 `0.2.x` 及更高主版本。路由固定为：

```text
POST /api/v1/mr/collect/start
GET  /api/v1/tasks/<agent_task_id>
POST /api/v1/tasks/<agent_task_id>/stop
GET  /api/v1/packages
GET  /api/v1/packages/<package_id>/download
```

不跟随 Agent 响应中的任意 URL，不接受调用方传入 Agent URL、任意命令、远端路径或 package 删除请求。

## 凭据边界

设备密码只存在于 `OnlineMrStartRequest` 和一次 start HTTP 请求正文的内存对象中。Agent Request 的公共副本会移除密码；Controller Mapping、Task、事件、日志和异常摘要不保存设备密码或 Agent Token。远端 Agent 继续使用脱敏任务参数和私有 sidecar 请求文件，最终 ZIP 禁止包含 `meta/request.private.json` 与 `stop.request`。

## 生命周期与状态收敛

远端 start 成功后，Controller 创建 `source=agent` 的外部 Task 和 AGENT Mapping，并保存：

- 本地 `agent_profile_id`；
- Agent 自报 `agent_id`；
- `agent_task_id`、可用时的远端 Session/Package ID；
- 最近远端状态、最近成功时间、连续失败次数；
- Controller 持久化的 `deadline_at`。

`created/starting/running/stopping` 分别收敛为统一 Task 与 `OnlineMrPhase`。远端进入 `stopped/completed/failed/cancelled` 后，Controller Task 不立即完成，而是先进入 `FINALIZING`，取得 package、下载并交给安全 importer。只有 importer 已原子提交 Session、更新 Mapping 和 Task 后，Controller 才进入终态。

正常停止只调用按 Task ID 的固定 stop 路由。终态重复停止直接返回现有结果；本阶段不提供 Agent force-stop。

## 自动时长与重启恢复

当前 Go Agent 不执行请求中的 `duration_minutes`。Controller 因此把截止时间保存为 `deadline_at`，Supervisor 到期后发送正常停止。浏览器或页面关闭不会终止 Supervisor；Controller 重启后，显式 `recover_mappings()` 会重新扫描 AGENT 活动 Mapping、按 Profile 重新取得内存凭据、查询远端 Task，并继续正常停止、状态轮询和包导入。

如果 Agent 在重启期间不可达，Mapping 保持活动并累计失败次数，不伪造完成态。达到 `ONLINE_MR_AGENT_STATUS_FAILURE_THRESHOLD`（默认 3）后记录 `ONLINE_MR_AGENT_REMOTE_STATUS_UNKNOWN`，后续轮询成功可继续收敛。轮询周期可用 `ONLINE_MR_AGENT_POLL_INTERVAL_SECONDS` 调整，默认 3 秒。

远端 Task 404 会以 `ONLINE_MR_AGENT_TASK_NOT_FOUND` 终结 Controller Task。远端已终态但 package 尚未出现时有限重试；超过阈值后以 `ONLINE_MR_AGENT_PACKAGE_NOT_READY` 失败。下载、校验或导入失败会保留远端 package/raw，并把本地 Task/Mapping 终结为失败，不覆盖已有 Session。

## Mapping schema v3

`tasks.db.online_mr_task_sessions` schema v3 在 v2 基础上增加 Agent Profile、远端 Task/Session/Package、最近状态、失败计数和截止时间字段，并对非空 `(agent_id, agent_task_id)` 建唯一索引。迁移只做加列与索引，不重建或删除既有行，不保存配置 JSON、密码、Token 或绝对路径。

## 当前边界与验收

- 仅单 Agent、单 MR；
- 无 Agent 强停、多 Agent 编排、远端 package 删除、任意命令或 URL；
- Qt/Web 暂未增加 AGENT 控制按钮或 API；
- 不自动解析、不生成报告；导入后沿用既有离线流程；
- LOCAL 仍以 `raw/collector_output_raw.log` 和 `session_meta.json.stop_reason` 为正式契约；Agent 包继续使用 `raw/init_raw.log` 与 `stop_reason.json`，两类执行端不强行统一文件布局。

自动化验证使用 fake Agent HTTP transport 和执行器替身覆盖固定 start/stop 路由、安全开关、身份字段、凭据不落盘、状态重试、正常停止、终态包导入、导入失败、Task 404、截止时间恢复、终态幂等与并发互斥。5C-10A-B Web 自动时长真实设备验收仍是独立现场事项，本阶段不自动连接真实设备。
