# Task Cleanup DTO 契约修复与真实 GUI Gate 验收

日期：2026-09-10  
Branch：`main`  
HEAD：`d84f0334fe2dc345e1a0f0026e37cc8bfee1955e`  
基线：`5216daba661cf3b84ed3e54ace8f0ceae6567724`

## 结论

本轮 DTO 修复、自动化门禁、真实 GUI 手工移除、正常重启复核和 Production 只读预览均通过。Production 没有执行 GC、VACUUM、文件替换或发布操作。

```text
DTO_CONTRACT_FIX = PASS
EXTRA_FORBIDDEN_RETAINED = YES
SINGLE_REMOVE_API = PASS
BULK_REMOVE_API = PASS
PREVIOUS_500_GC_STATE = COMMITTED
OPERATIONAL_GC_ATOMICITY = PASS
REAL_GUI_MANUAL_REMOVE = PASS
REAL_GUI_RESTART = PASS
LOG_CENTER_PRESERVED = PASS
ARTIFACT_PRESERVED = NA
PRODUCTION_DRY_RUN = PASS
PRODUCTION_GC = NOT_RUN
PRODUCTION_VACUUM = NOT_RUN
PRODUCTION_REPLACE = NOT_RUN
PRODUCTION_GC_READY = YES
```

## 修改

- `JobCenterCleanupResultDTO` 正式接收 `dismissed_by`；`ApiModel` 的 `extra="forbid"` 保持不变。
- 单任务和批量清理结果统一返回 `dismissed_by`；多操作人批量结果使用 `mixed`。
- Renderer `TaskCleanupResult` 同步补齐 `dismissed_by`。
- 增加 DTO、单任务 API、批量 API 和清理服务回归断言。

上一轮 T2 的 HTTP 500 根因是清理已经提交后，响应序列化阶段因 `dismissed_by` 被严格 DTO 拒绝。本轮只修复契约，没有改变 GC 算法、保护判断、tombstone schema 或任务 authority。T2 的 `task_snapshots/task_events/task_results` 均为 0，tombstone 保留，证明此前 500 对应的是提交后响应失败而不是部分 GC。

## 自动化验证

- Python 定向：`139 passed, 1 warning`。
- Renderer 定向：`36 passed`。
- Renderer typecheck：通过。
- Consumer Gate：通过：Python `4802 passed, 2 skipped`；Renderer `181 files / 1300 tests`；Electron `37 files / 298 tests`；main-contract-smoke `12 passed`。
- `ruff`、`py_compile`、`git diff --check`：通过。

## 真实 GUI 证据

开发数据根：`D:\NetConsoleData-dev`。

- T3：`system-maintenance-b7cb12f851654ed18093697efd6efe87`，安全终态日志清理任务。
- 手工从任务详情点击“从列表移除”：HTTP `200`，返回 `dismissed_by=local-user`，界面提示“任务记录已从列表移除”。
- 刷新 Task Center 后 T3 消失；T1 `a57bff14ef3149d8b876b6f0b778886d` 和其他未清理任务仍在，T1 详情可再次打开。
- 重启后 T3 未复现，T1 仍存在且详情正常：`REAL_GUI_RESTART=PASS`。
- Logs Center 按 T3 查询仍保留 3 条记录（dismiss API 200、finished、encoding）：`LOG_CENTER_PRESERVED=PASS`。
- T3 没有 Artifact 产物或 Artifact 依赖，因此 `ARTIFACT_PRESERVED=NA`，不虚构 Artifact 验收结论。

截图与日志位于：
`D:\study\NetConsole-Workspace\diagnostic\task-lifecycle-real-gui-20260910`

## 只读数据库复核

使用 SQLite `mode=ro` 读取 `宁波地铁12号线/db/tasks.db`：

- T3：snapshots/events/results = `0/0/0`；tombstone 为 `explicit_task_cleanup`。
- T2：snapshots/events/results = `0/0/0`；tombstone 为 `explicit_task_cleanup`。
- T1：snapshots/events/results = `1/6/1`，未被清理。
- `config/task-authority-index.json` 可解析，T2/T3 均不在 index，未发现 `.tmp`/`.part`。

## Production 只读预览

命令使用 `scripts.maintenance.cleanup_retired_tasks --data-root D:\NetConsoleData --all-sites`，未带 `--apply`；报告：

```text
tasks.db = 9
tasks.db bytes = 402067456
candidate = 7207
safe = 6402
protected = 805
unknown = 0
```

保护原因计数（候选可多重命中）：`RESOURCE_REFERENCE=612`、`ARTIFACT_MANIFEST_REFERENCE=162`、`DURABLE_RESULT_REFERENCE=189`、`ONLINE_MR_TASK=112`、`ONLINE_MR_MAPPING=9`、`RESULT_ARTIFACT_REFERENCE=8`。预览 JSON：
`D:\study\NetConsole-Workspace\diagnostic\task-lifecycle-real-gui-20260910\TASK_RETIREMENT_PREVIEW.json`

Production 数据根未执行写入、GC、VACUUM、VACUUM INTO、替换、WAL/SHM 删除、打包、改版本或打 tag。
