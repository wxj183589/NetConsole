# Online MR Task Session Contract

状态：`CONFIRMED`（基于 `origin/main` `5d88bd40` 的代码和定向测试）。

## 结论

`online_mr_task_sessions` 是 Online MR 的 operational authority（选项 A），不是可以从
`task_snapshots`、`task_events` 或会话目录临时重建的缓存。它保存 Controller task 与本地/Agent
session 的一一映射、执行器、远端 task/package 身份、生命周期阶段、停止原因、强停标记、终态和
错误摘要。任务表只能提供任务状态，不能重建远端 Agent 标识、Controller 截止时间或导入包关联。

该表与 `tasks.db` 同库，但由 `OnlineMrTaskSessionRepository` 独立维护 schema v3。删除映射只能由
显式会话清理事务执行；通用 task retention 不得删除仍有映射的任务。

## Consumer Matrix

| Consumer / path | 读写 | 证据与契约 |
| --- | --- | --- |
| `OnlineMrApplicationService` | 写入 `create/save/mark_stopping/mark_terminal/update_*`；读取 task/session；重启恢复 active mapping | `src/netconsole/services/online_mr/application_service.py`、`src/netconsole/repositories/online_mr_task_session_repository.py`。LOCAL/AGENT 生命周期先更新 mapping，再由任务/会话终态收口。 |
| Online MR API / Web control | 读取 operation snapshot、状态、错误和 Agent 远端状态 | `src/netconsole/services/online_mr/api_facade.py`、`web_control_service.py`、`agent_web_control_service.py`、`src/netconsole/backend/api/online_mr_router.py`。Router 不自行实现状态机。 |
| Task Center query | 读取 mapping 摘要并按 `controller_task_id` 关联任务列表 | `src/netconsole/services/job_center/query_service.py` 的 `online_mr_task_sessions` join；缺表时仅保持兼容查询，不代表 mapping 可丢失。 |
| restart / resume / reconcile | 读取 active mapping；进程恢复将未收口 mapping 标记为 `STALE/recovered_aborted` | `OnlineMrTaskSessionRepository.list_active()`、`recover_active_as_aborted()` 及 Online MR application service 生命周期测试。恢复不得假造完整 ZIP。 |
| Site Return Package | 预检校验 task 引用、局点 alias、Agent pair 和 mapping identity；应用阶段在同一事务插入 mapping，并以完整 mapping 语义检测冲突 | `src/netconsole/services/site_sync.py::_preview_task_merge`、`_validate_task_merge_references`、`_immutable_task_conflicts`、`_apply_task_merge`。相同 mapping 重放幂等；冲突 fail-closed，不能 newer-wins。 |
| import/export | `collection_return` 包携带 `online_mr_task_sessions`；导入与 `task_results -> task_snapshots -> task_events` 一并合并。普通报告导出不把 mapping 当作业务结果副本 | `docs/storage/SITE_PACKAGE_FORMAT.md`、`src/netconsole/services/site_sync.py`。映射字段不能从 manifest 推断或扩展局点 alias。 |
| Ground Unattended | 不直接写 Online MR mapping；关联的深度采集/任务通过 Controller task 和 session 关系受保护 | `src/netconsole/services/site_retention.py` 的 Online MR protection 与 Ground 任务关联。此处是间接 consumer，不能据此删除映射。 |
| Renderer UI | 通过 Online MR API 读取 DTO；不直接访问 SQLite | `apps/desktop_renderer/src/views/rail-transit/OnlineMrRealtimeView.vue`、`OnlineMrAnalysisView.vue`、`components/OnlineMrLocalControl.vue` 及对应 API client。 |
| cleanup / retention | 会话删除使用 `delete_session_records()`，在事务中删除 mapping 和可删除 task rows；typed retention 把有 mapping 的 task 标记为 protected | `src/netconsole/repositories/online_mr_task_session_repository.py`、`src/netconsole/services/site_retention.py`。默认 retention 不删除 mapping、raw、session metadata 或 package。 |

## Lifecycle and compatibility rules

1. `controller_task_id` 是 mapping 主键；`session_id`、非空 `(agent_id, agent_task_id)` 必须保持唯一。
2. schema 升级只允许加列/索引并保留既有行；旧 v1/v2 行可读取并由恢复流程显式收口。
3. `site_id` 必须匹配目标 Registry stable id 或已声明 alias；任意其他值导入失败关闭。
4. `task_results` 是终态结果 authority；mapping 是 session identity/lifecycle authority，两者不能互相替代。
5. Agent 远端终态在 package 安全导入前不能把 Controller task 或 mapping 标为完成。
6. `force_stop`、`STALE`、`TASK_ONLY_FAILED` 等终态必须保留停止原因/错误摘要；不得伪造正常 ZIP。
7. Online MR session/raw/analysis data 属于 `LONG_TERM_MANUAL_DELETE`；物理删除需要显式会话动作和隔离目录演练。

## Required regression evidence

- `tests/test_online_mr_application_service.py`：schema migration、active recovery、终态和敏感字段边界。
- `tests/test_site_sync_task_merge.py`：四表回传合并、幂等、mapping identity conflict、引用校验和 fail-closed。
- `tests/test_site_retention.py`：有 Online MR mapping 的任务受到 retention protection。
- `tests/test_online_mr_task_session_contract.py`：本契约文档与关键代码入口保持同步。

