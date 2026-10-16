# AC Web 动作计划状态协调 Phase 2-B

日期：2026-10-16

基线：`main / 5b657137`

范围：AC Web 固定动作计划与 Task Center 状态协调，以及终态落盘前的最小生命周期接入；不包含设备采集、设备配置、WPS 同步、Task 历史批量清理或正式计划批量修复。

## 结论

原实现的 `GET /actions/plans/{plan_id}` 和审计查询会调用 `_refresh_plan_status()`；当 Task 终态更可信时，该方法直接把状态写回计划 JSON。它同时只按 Task ID、所有者、来源和类型做有限校验，没有显式拒绝错误局点，也没有把缺失 Task 表达为可见的未知状态。这样既让普通查询产生持久化副作用，也可能把不完整或错误作用域的 Task 误当成计划结果。

Phase 2-B 将协调拆成两层：

1. `classify_ac_action_plan_status()` 是纯分类函数，只读取计划和单个 Task 快照，不扫描 Task 历史、不执行命令、不修改文件。
2. GET 计划、审计接口返回 `stored_status`、`effective_status`、`reconciliation_status`、`reconciliation_reason` 和 `evidence_level`。当前 Task 缺失、被 tombstone 清理、局点/所有者/来源/类型不匹配或 `plan_id` 冲突时，显示 `UNKNOWN_OR_UNVERIFIED`。
3. AC Web 动作 Task 创建时仅在 Task 快照中保留受限的 `plan_id` 关联证据；Worker 的完成、失败、取消事件、孤儿恢复事件，以及 Task 清理前回调，均由 `AcWebApplicationService` 的订阅者自动调用逐计划协调。协调只接受同局点、`owner=web_ac`、`source=local`、受控任务类型和一致 `plan_id`，并在 Task 终态证据被删除前写入 `status_reconciliation`。局点切换只对目标局点执行一次有界孤儿恢复。
4. 显式 `POST /actions/plans/{plan_id}/reconcile` 仍保留为有界的人工/诊断重试入口；未知或活动状态不写回，协调异常不改变已经持久化的 Task 终态。
5. 任务刚提交而快照尚未可见时，使用计划内的短启动窗口显示 `EXECUTING`；窗口外改为未知，避免把永久缺失伪装成活动任务。

## PR #88 评审收口

- P1：已接入真实 Task Center 生命周期。Backend 先创建并持久化 AC Web Task，再由事件总线在终态事件落库后触发计划协调；Task cleanup 在删除快照前执行 AC 专属同步守门并发出有界 `tasks.before_cleanup` 事件；启动、Worker 恢复和局点切换通过同一协调事件补偿。非 AC Web 任务、其他局点、其他 owner/source/type 和 `plan_id` 冲突均拒绝协调。
- P2：Renderer 不再把动作计划的状态码、协调码或原因码作为主文案展示；`runtime.ts` 提供中英文 i18n 映射和未知值兜底，`UNKNOWN_OR_UNVERIFIED` 保持“结果无法核验”，不使用成功色语义。
- 历史边界：未带 `plan_id` 的旧 AC Task 只在清理/终态恢复时对最多 256 个计划文件做一次有界、唯一 `task_id` 反向关联；无关联、超出范围、歧义或协调失败均保留 Task 证据。Task 快照已被清理且没有此前保存的 `status_reconciliation` 时，仍保持 `UNKNOWN_OR_UNVERIFIED`，本次不会扫描或补写旧计划。

## 正式数据只读核对

仅通过文件读取和 SQLite `mode=ro` 连接核对 `D:\NetConsoleData`，未调用业务服务、未启动任务、未执行采集或配置命令：

| 项目 | 结果 |
| --- | ---: |
| 有效计划 JSON | 40 |
| `EXECUTING` 计划 | 21 |
| `COMPLETED` 计划 | 19 |
| Task 数据库 | 9 |
| Task 快照 | 7469 |
| Task retention tombstone | 499 |
| `EXECUTING` 对应同局点、授权、终态 `COMPLETED` | 15 |
| `EXECUTING` 对应同局点、授权、终态 `FAILED` | 2 |
| `EXECUTING` 缺失且有 tombstone | 4 |
| 发现跨局点或授权冲突 | 0 |
| 当前在线/离线业务状态 | 未触碰 |

上述 21 条计划均未修改；本次没有清理 Task、更新计划 JSON、写数据库、启动设备任务或同步 WPS。

## 验证记录

- AC Web/Task lifecycle 定向回归：新增自动终态协调、完成/失败/取消、重复回调幂等、恢复作用域、清理前回调和 i18n 映射测试；具体最新结果以 PR #88 当前提交报告为准。
- Python 全量（工作树源码、隔离测试根）：5165 passed，2 skipped，33 warnings。
- Renderer：181 files / 1311 tests；`vue-tsc -b` 和 build 通过。
- Electron：38 files / 303 tests；typecheck、Main/Preload build 通过。
- Main Contract：12 passed，3 warnings。
- Architecture：12/12 passed；Ruff、docs/path、diff-check 通过。
- L4 Local Quality Gate：除 Python 阶段 3 个 Windows 文件锁/并发基线失败外，其余套件通过；失败节点为 Mesh resident 状态文件读取、Demo site 重建和设备兼容性 Demo seed，未触及本次 AC Web 计划协调代码。
- Baseline-aware Python：`PYTHON_BASELINE_RETAINED=0`，`NEW_FAILURES=0`；本地全量 5165 passed，2 skipped。
- 隔离 1000 条纯分类基准：约 0.002 秒；不扫描 Task 历史、不写数据库。

## 后续边界

仍需人工确认：GUI 实际显示、真实 AC 写操作和 Electron 原生交互。自动化已覆盖启动失败/完成/失败/取消的关联证据、受限恢复、清理前顺序、重复终态回调、作用域拒绝和历史未知边界；Phase 2-B 不自动处理这 21 条正式计划，也不把历史终态批量写入正式数据。
