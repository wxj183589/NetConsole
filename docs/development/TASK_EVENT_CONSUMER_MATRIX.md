# Task Event Consumer Matrix

本矩阵是 `task_events` 自动保留策略的消费者审计结果。`task_events` 只承载任务运行期间的短期结构化事件；任务摘要、终态、错误摘要、结果引用和 Artifact 引用仍由 `task_snapshots` / `task_results` / Artifact manifest 负责。自动策略只删除完整生命周期已经结束且超过保留期的 `task_events`，不删除任务摘要、结果、快照、日志或业务数据。

| consumer | read/write | current-task-required | historical-required | long-term-required | retention-safe | reason |
|---|---|---:|---:|---:|---:|---|
| Task Center list | read | yes | no | no | yes | 列表字段来自 `task_snapshots`、结果引用和 authority index，不读取事件正文。 |
| Task Center detail | read | yes | limited | no | yes | 详情使用任务快照、错误/成功摘要和结果引用；事件仅补充最近进度。事件为空时任务仍存在。 |
| Task Detail log tail | read | yes | no | no | yes | 只显示运行过程 tail；终态旧任务显示“详细运行记录已按保留策略清理”。 |
| Task API / WebSocket | read/write | yes | no | no | yes | REST/WebSocket 提供当前状态和短期事件 tail；终态快照不依赖完整事件历史。 |
| TaskApplicationService / TaskRepository | read/write | yes | no | no | yes | 任务生命周期写入事件；自动清理只在 Repository 事务内删除事件，并重新校验终态。 |
| local recovery / startup reconciliation | read/write | yes | no | no | yes | 只需活动任务和当前快照；活动态永远保护，恢复不依赖已过期终态事件。 |
| Network Tools | read/write | yes | no | no | yes | 事件只用于当前任务进度；诊断结果由领域结果/Artifact authority 保存。 |
| File Management | read/write | yes | no | no | yes | 下载队列只依赖活动任务；文件本体、descriptor 和 Artifact 引用不在 `task_events` 中。 |
| Agent task bridge | read/write | yes | no | no | yes | Agent 当前任务同步使用活动状态；远端事件来自 Agent API，不是本地长期日志 authority。 |
| Online MR | read/write | yes | no | no | yes | 当前 mapping 位于 `online_mr_task_sessions`，映射中的任务在 Repository 事务内保护；MR 事实/raw/package 由 Online MR owner 保存。 |
| Ground | read/write | yes | no | no | yes | Ground 使用自己的事件/raw/READY archive；清理前只读检查 `task_id/controller_task_id` 引用，命中即保护。 |
| Site Package / Export | read/write | yes | no | no | yes | 当前合并使用 snapshot、result、mapping 和可用事件；长期导出文件、包和业务事实不依赖旧运行事件。 |
| Artifact / File Store | read/write | yes | no | yes | yes | Artifact manifest、结果引用和文件本体是长期 authority；不会从 `task_events` 重建或删除。 |
| Log Center | read/write | no | yes | yes | yes | Log Center 读取独立的 `app.log` / managed log roots，由 `AppLogger` 与 `LogHousekeeper` 管理；没有 `task_events` 读取路径。 |
| Traffic event store | read/write | yes | no | no | yes | Traffic 长期/领域事件由 `TrafficEventStore` 保存；`task_events` 只记录任务控制状态。 |
| System maintenance progress | read/write | yes | no | no | yes | 维护任务进度是短期运行信息；应用日志和清理结果由各自 authority 保存。 |
| SiteRetention / TaskHistoryStore | read/write | no | isolated evidence | no | isolated | 这是旧的显式维护证据/候选流程，不是运行时 Task Center authority；新自动保留服务不调用它。 |

## Long-term log authority proof

Log Center 的事实来源是 `src/netconsole/core/app_logger.py` 写入的日志目录和 `AppCleanupService` / `LogHousekeeper` 管理的日志文件。System Maintenance 日志接口读取 managed logs；Renderer 侧使用 `/api/system-maintenance/logs`，而不是 Task API 的 `/tasks/{task_id}/logs`。全仓 `task_events` 消费者审计中，Log Center 没有读取 `task_events` 的调用链，因此 `LOG_CENTER_DEPENDS_ON_TASK_EVENTS=NO`。

## Protection conclusion

- `PENDING`、`STARTING`、`RUNNING`、`STOPPING` 永远不进入候选。
- Online MR 当前 mapping、Ground 当前引用和无法验证的外部引用 fail-closed 保护。
- 只删除超过配置天数的终态任务事件；`task_snapshots`、`task_results`、`task_result_blobs`、tombstone、Artifact、Log Center、Ground、Online MR、raw 和业务数据库保持不变。
- 任务摘要仍可打开；旧终态任务没有事件时不是“任务不存在”。
