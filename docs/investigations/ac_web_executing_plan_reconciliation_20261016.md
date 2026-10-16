# Phase 2-A：AC Web 动作计划状态一致性调查

日期：2026-10-16  
仓库基线：`main / 5b65713751324d3cfbf3adc7e5aa9a4ec48c1191`  
调查分支：`codex-A/phase2-a-ac-web-plan-reconciliation-20261016`  
数据范围：`D:\NetConsoleData`，仅只读

## 结论摘要

本轮确认这是一个代码生命周期缺口，不是 21 个 AC 动作仍在执行：

1. AC Web 计划 JSON 在执行前被写成 `EXECUTING`；Worker 结束时由 Task Center 写 Task 终态，Worker 不负责回写计划 JSON。
2. 计划终态同步是懒执行的，只在计划详情 GET 或审计 GET 中调用 `_refresh_plan_status()`。Backend 启动、Task Center 恢复和任务历史清理都不会遍历并协调 AC 计划文件。
3. `_refresh_plan_status()` 找不到 Task 或 Task 未通过授权检查时直接返回，不写入任何“未知/不可核验”状态，因此历史清理后仍可永久显示 `EXECUTING`。
4. 当前实现还没有在 `_refresh_plan_status()` 内显式比较 `snapshot.site_name` 与请求局点；通常由按局点打开的 Repository 作用域间接保护，但这不是足够的防御边界。
5. 正式数据中的 21 条 `EXECUTING` 计划没有活动 Worker、活动 AC Web Task 或匹配的运行文件。17 条可由同局点授权 Task 终态核验，4 条已经丢失 Task 快照且有 Task Center tombstone，结果必须保持 `UNKNOWN_OR_UNVERIFIED`，不能批量认定为失败。

本轮没有修复正式数据，也没有修改产品业务代码。

## 工作区和运行环境

- `main` 工作区干净，HEAD 为 `5b657137`，与 `github/main` 一致。
- 现有源码 Electron 保持运行，未关闭、未切换局点、未删除锁文件。
- 当前运行实例：Vite `127.0.0.1:5173`，Python Backend `127.0.0.1:64460`；进程路径均来自 `D:\study\NetConsole-Workspace\NetConsole` 的 Electron/Vite/.venv。
- 当前应用配置局点为 `宁波地铁10号线`。只读取 `application.json`，没有调用会触发任务恢复或计划写回的 API/Service。
- 未发现 `background_worker`、AC 配置 Worker、设备连接进程或匹配本次 21 条 Task ID 的运行文件。

## 只读边界和取证方法

计划目录由当前 `PathResolver(data_root=...)` 解析为：

```text
D:\NetConsoleData\runtime\cache\ac_web_action_plans
```

取证只使用：

- `Path.read_text()` 和 `Path.stat()` 读取计划 JSON 与文件时间。
- SQLite URI `file:<path>?mode=ro` 读取各局点 `tasks.db`。
- 只读进程、端口和运行文件枚举。

没有实例化会执行 `initialize()` 的 `TaskRepository`，没有调用 `preview_action_plan()`、`action_audit()`、`recover_tasks()` 或其他可能调用 `_save_plan()`、孤儿恢复、清理或任务写回的服务入口。报告中的计划编号 `P01` 至 `P21` 是按文件更新时间排序的脱敏行号，不是原始 plan ID；没有输出 token、digest、凭据、设备命令或未脱敏设备标识。

## 正式数据总量核验

`ac_web_action_plans` 实际共有 40 个有效 JSON 文件：

| 指标 | 结果 |
|---|---:|
| 全部计划文件 | 40 |
| `EXECUTING` | 21 |
| `COMPLETED` | 19 |
| JSON 损坏/非对象 | 0 |
| 已过期 `expires_at` | 40 |
| 缺少 `created_at` 字段 | 40 |
| 全部文件更新时间范围 | 2026-07-23 12:52:02 至 2026-10-15 09:32:49 |
| 21 条 `EXECUTING` 更新时间范围 | 2026-07-23 12:52:02 至 2026-10-15 09:32:49 |
| 21 条 `EXECUTING` 的过期时间范围 | 2026-07-23 12:56:58 至 2026-10-15 09:37:48 |

21 条 `EXECUTING` 按局点分布：

| 局点 | 数量 |
|---|---:|
| `hzl10` | 11 |
| `宁波地铁10号线` | 5 |
| `宁波地铁12号线` | 4 |
| `宁波地铁6号线` | 1 |
| 合计 | 21 |

### 21 条执行中计划的逐条脱敏映射

| 记录 | 局点 | JSON 状态 | Task Center | 直接 `plan_id` 结果证据 | Worker/计划运行文件 | 清理证据 | 结论 |
|---|---|---|---|---|---|---|---|
| P01 | 宁波地铁12号线 | EXECUTING | FAILED | 无 | 未发现 | 无 tombstone | 状态不一致；可核验失败 |
| P02 | 宁波地铁12号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P03 | 宁波地铁6号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P04 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P05 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P06 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P07 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P08 | 宁波地铁12号线 | EXECUTING | FAILED | 无 | 未发现 | 无 tombstone | 状态不一致；可核验失败 |
| P09 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P10 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P11 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P12 | 宁波地铁10号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P13 | 宁波地铁10号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P14 | 宁波地铁12号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P15 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P16 | 宁波地铁10号线 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |
| P17 | 宁波地铁10号线 | EXECUTING | 缺失 | 无 | 未发现 | `explicit_task_cleanup` | UNKNOWN_OR_UNVERIFIED；保留审计事实 |
| P18 | 宁波地铁10号线 | EXECUTING | 缺失 | 无 | 未发现 | `explicit_task_cleanup` | UNKNOWN_OR_UNVERIFIED；保留审计事实 |
| P19 | hzl10 | EXECUTING | 缺失 | 无 | 未发现 | `explicit_task_cleanup` | UNKNOWN_OR_UNVERIFIED；保留审计事实 |
| P20 | hzl10 | EXECUTING | 缺失 | 无 | 未发现 | `explicit_task_cleanup` | UNKNOWN_OR_UNVERIFIED；保留审计事实 |
| P21 | hzl10 | EXECUTING | COMPLETED | 有 | 未发现 | 无 tombstone | 状态不一致；可核验完成 |

说明：P01、P08 的失败 Task 以及 P02 的完成 Task 没有在 `result_json` 中保留直接 `plan_id` 字段；它们仍具有同 Task ID、同局点、`owner=web_ac`、`source=local`、合法 `task_type` 的强身份关联。后续修复必须把“直接 plan_id 证据”和“Task ID + 作用域证据”分层，不得把宽泛的同类型终态 Task 当成计划证明。

## 汇总分类

以下主分类只针对 21 条当前为 `EXECUTING` 的计划，互斥且合计为 21；“孤儿候选”和“状态不一致”是交叉维度，不重复计入主分类。

```text
TOTAL_EXECUTING_PLANS=21
MATCHED_ACTIVE_TASKS=0
MATCHED_COMPLETED_TASKS=15
MATCHED_FAILED_TASKS=2
MATCHED_CANCELLED_TASKS=0
MISSING_TASK_SNAPSHOTS=4
ORPHANED_PLAN_CANDIDATES=4
AMBIGUOUS_OR_UNVERIFIED=0
CONFIRMED_STATE_MISMATCH=17
```

证据补充：

- 9 个局点 Task DB 只读扫描共看到 7468 条 Task 快照。
- 与全部计划 Task ID 对应的授权 AC 动作 Task 共 35 条：33 条 `COMPLETED`、2 条 `FAILED`，没有 `PENDING/STARTING/RUNNING/STOPPING`。
- 全部 5 条缺失 Task 的计划（含 1 条当前 JSON 已是 `COMPLETED` 的历史计划）均有 `task_retention_tombstones.reason=explicit_task_cleanup`；仅就已删除 Task 的执行结果不能判定成功或失败。
- 21 条执行中计划中只有 2 条仍有 Task event 行；event payload 没有 `plan_id`。Task history cleanup/retention 会使事件证据进一步减少。
- 没有发现同一计划 Task ID 出现在其他局点、其他任务类型或未授权 owner/source 下；`AMBIGUOUS_OR_UNVERIFIED=0` 是本次实际数据结果，不代表后续修复可以省略作用域校验。
- Task authority index 仅有 2 条其他记录，没有命中本批 21 条计划 Task ID。

## 状态生命周期和根因

### 计划和 Task 是两条独立持久化链

`AcWebApplicationService.execute_action_plan()` 先将计划写为 `EXECUTING` 并保存 `task_id`，再调用 `LocalProcessAdapter.start_job()`。启动异常时，当前代码将计划改为 `START_FAILED`；资源冲突则回滚到 `CONFIRMED`。这两条分支本身不会产生本批长期 `EXECUTING` 残留。

Worker 结束时，`LocalProcessAdapter._wait_for_process()` 调用 `TaskApplicationService.complete()` 写入 Task 终态并触发 Task event；没有调用 AC Web 计划的 `_save_plan()`。因此计划 JSON 不会在 Worker 正常结束时自动终态化。

### 只有查看详情/审计才会懒同步

Router 中：

- `GET /actions/plans/{plan_id}` 调用 `preview_action_plan()`。
- `GET /actions/plans/{plan_id}/audit` 调用 `action_audit()`。

两者都会调用 `_refresh_plan_status()`；该方法对授权 Task 的 `COMPLETED/FAILED/CANCELLED` 才写回计划 JSON。也就是说，Worker 已完成但用户没有再次打开计划详情时，文件可以一直保持 `EXECUTING`。

### 缺失 Task 的分支会永久保持原值

当前 `_refresh_plan_status()` 的逻辑在以下情况直接返回 `None`：

- `task_id` 为空；
- Task 快照不存在；
- Task 不满足 owner/source/type 授权。

这些分支没有 `_save_plan()`，也没有 `UNKNOWN_OR_UNVERIFIED` 的派生状态。因此 PR #87 清理完 Task Center 记录后，关联计划文件不会被协调，正好解释了 P17-P20。

### Backend 重启恢复不包含计划协调

`TaskApplicationService` 启动及延迟启动阶段会恢复/协调本地 Task 的孤儿状态，并运行 Task event retention；`AcWebApplicationService.recover_tasks()` 也只处理授权 Task、运行文件和 artifact。两者都没有遍历 `ac_web_action_plans` 并对缺失 Task 产生未知状态。

### 过期时间不是本批 EXECUTING 的终态规则

`preview_action_plan()` 只在 `status == PREVIEW` 且超时时写成 `EXPIRED`。对于 `EXECUTING`，过期的 `expires_at` 不会覆盖 Task 终态，也不能被用来推断设备命令成功或失败。本次 21 条全部已过期只是历史年龄证据，不是失败证据。

## PR #87 关系

PR #87（合并提交 `c5ca5f67`）的修改范围包括 Task Center 的清理资格、Task 快照/事件/结果删除与 tombstone、跨局点通知及相应测试；没有修改 `AcWebApplicationService` 的计划生命周期，也没有读取或删除 `runtime/cache/ac_web_action_plans`。

当前 `TaskCleanupService`/`TaskRepository` 清理边界是：

- 删除 Task Center 自己的 `task_events`、`task_results`、`task_snapshots`；
- 写入 `task_retention_tombstones`；
- 不触碰 AC Web 计划 JSON、设备数据库、AC 配置或设备命令。

应用缓存清理还将 `ac_web_action_plans` 列为保护目录，且常规 runtime cache 扫描目录不包含它。因此 PR #87 没有破坏计划文件，但它会让计划关联的 Task 证明消失；缺少一个跨 authority 的“未知/不可核验”协调层是本问题的直接背景。

## Worker、锁和重复执行风险

- 当前 21 条计划没有匹配的 `background_jobs/<task_id>.json`、`.cancel` 或 `export_jobs/<task_id>.json`。
- 当前进程中没有对应的 AC Web worker 或设备连接进程。
- 当前授权 AC 动作 Task 没有活动状态，因此没有发现仍有效的 AC 配置资源锁。其他模块的通用 runtime 锁文件存在，但不属于本批计划的 Task 证明。
- 当前 `execute_action_plan()` 只接受 `CONFIRMED`，不会因为历史 `EXECUTING` 计划被重新查看而再次执行命令；本轮没有发现由计划修复触发重复设备命令的证据。
- 未来修复绝不能把缺失 Task 的 `EXECUTING` 重置为 `CONFIRMED`，也不能自动重新提交 Worker；否则会制造重复 AC 配置风险。

## 隔离 TEST 根复现

新增测试文件：`tests/test_phase2_ac_web_plan_reconciliation_audit.py`。测试只使用内存 fake、`tmp_path` 和临时 JSON，不打开正式数据库、不启动 Worker、不调用 API。

执行结果：

```text
tests/test_phase2_ac_web_plan_reconciliation_audit.py: 11 passed
```

本轮同时执行了既有相关测试：

```text
动作计划/重启/取消/局点边界、AC 任务恢复、Worker 启动失败、孤儿 Task 恢复、清理后不可复活、Task Center 清理：9 passed, 1 warning
```

16 个隔离场景的覆盖关系如下：

| 场景 | 证据 | 结果 |
|---|---|---|
| EXECUTING + COMPLETED | 新增终态映射测试、既有动作计划测试 | 终态可懒映射；当前计划不会主动同步 |
| EXECUTING + FAILED | 新增终态映射测试 | 可映射 FAILED |
| EXECUTING + CANCELLED | 新增终态映射测试、既有动作计划测试 | 可映射 CANCELLED |
| EXECUTING + RUNNING | 新增活动 Task 测试 | 保持 EXECUTING，不清理 |
| EXECUTING + Task 缺失 | 新增缺失 Task 测试 | 当前无变化；后续应为 UNKNOWN_OR_UNVERIFIED |
| EXECUTING + history cleaned | 正式 tombstone + 缺失 Task fixture | 当前无变化，不能推断终态 |
| Task ID 跨局点 | 新增同局点防御缺口测试 | 当前方法缺显式 site guard，后续必须拒绝 |
| Task ID 被其他类型占用 | 新增授权 type 测试 | 当前无变化，不能使用未授权类型证明 |
| JSON 损坏 | 新增只读解析测试 | 抛出 PLAN_NOT_FOUND，不改文件 |
| 计划过期 | 新增只读解析测试、既有过期测试 | 仅 PREVIEW 才转 EXPIRED |
| Worker 启动失败 | 既有 LocalProcessAdapter 测试 | Task 失败且运行文件清理；计划入口另写 START_FAILED |
| Worker 异常退出 | 既有 Task orphan recovery 测试 | Task 可被恢复为 FAILED；计划仍需显式协调 |
| Backend 正常重启 | 既有动作计划重建 Service 测试 | Task 可复用，计划同步仍是访问触发 |
| Backend 异常退出后重启 | 既有孤儿恢复测试 | 只恢复 Task，不扫描计划文件 |
| 多局点历史计划 | 新增多局点 fixture、正式分布 | 文件可并存，必须按 site 作用域读取 |
| 多次恢复幂等 | 新增幂等测试 | 已写终态不重复写入 |

## 最小安全修复方案（本轮不实施）

建议下一阶段只在现有 AC Web/Task 边界内增加受控协调，不引入新全局框架或数据库迁移：

1. 增加一个纯“证明读取 + 分类”的计划协调路径，明确区分 `ACTIVE`、可验证终态和 `UNKNOWN_OR_UNVERIFIED`；不要把现有 GET 默认变成无界全量扫描。
2. 对同局点、同 Task ID、`owner=web_ac`、`source=local`、合法 `task_type` 的单一 Task 才允许映射终态，并显式校验 `snapshot.site_name == plan.site_id`。若结果中带 `plan_id`，必须要求精确相等；只有 Task ID/作用域证据时应保留证据等级，不能把弱证据伪装成完整计划证明。
3. 对 Task 缺失、已被 tombstone 清理、未授权或跨局点记录，返回/展示 `UNKNOWN_OR_UNVERIFIED` 及原因，原始计划事实可保留为 `EXECUTING`；绝不能改成 FAILED、CONFIRMED，也不能重新执行。
4. 终态写回只放入明确的恢复入口，使用已有计划锁和原子临时文件替换，要求幂等、审计可追踪、并发失败安全。恢复入口不连接设备、不触发 Worker、不释放活动资源锁。
5. 计划历史默认保留，不在启动时删除旧计划；如需扫描，应使用有界、按局点、按 manifest/index 或明确任务列表的方式，并测量启动耗时。
6. API/UI 如需新增 `UNKNOWN_OR_UNVERIFIED`，优先增加可选的 reconciliation 字段而不是破坏既有 status 枚举；需要单独补齐 API、Renderer 和导出契约测试。

建议后续最小修改文件（待授权后确认）：

- `src/netconsole/application/ac/web_application_service.py`
- 计划 DTO/Router 的可选一致性字段（如最终契约确需）
- `tests/test_ac_application_job_contract.py` 或独立 reconciliation 测试
- 本调查报告及后续修复审计记录

本轮不需要也不建议修改：设备采集、AC 命令 Worker、数据库 Schema、Task Center 通用框架、WPS、MESH、轨旁 AP、PR #78/PR #83 相关代码。

## 正式数据处理结论

- 本轮正式数据修复：不需要，且未执行。
- 21 条计划：不删除、不改写、不批量标记失败。
- 缺失 Task 的 4 条执行中计划：当前只能标记为未知/不可核验的修复候选，不能从 tombstone 推断设备动作结果。
- 17 条存在终态 Task 的执行中计划：具备受控终态协调候选，但应在后续获批后按作用域和证据等级处理。

## 后续人工确认事项

1. 业务负责人确认是否接受新增 `UNKNOWN_OR_UNVERIFIED` 展示语义及对应 API/UI 可选字段。
2. 确认是否允许对 15 条完成、2 条失败的计划执行一次性受控终态协调；不能将 4 条缺失 Task 计划纳入自动终态修复。
3. 确认是否需要保留或补充计划级审计记录，以便在 Task Center 历史清理后仍能说明“结果未知”而不是误报失败。
4. 本轮没有进行 GUI 计划状态修复验收；需在后续代码获批后安排人工确认。

## 本轮状态

```text
PUBLISH=NO
TAG_CREATED=NO
RELEASE_CREATED=NO
INSTALLER_BUILD=NO
PRODUCTION_DATA_MUTATION=NO
PRODUCTION_TASK_CLEANUP=NO
AC_PLAN_FILE_MUTATION=NO
DEVICE_CONFIG_MUTATION=NO
WPS_REMOTE_WRITE=NO
MAIN_MERGE=NO
PR78_MERGE=NO
PR83_MERGE=NO
```

本轮调查完成后停止，等待用户批准下一阶段的代码修改。
