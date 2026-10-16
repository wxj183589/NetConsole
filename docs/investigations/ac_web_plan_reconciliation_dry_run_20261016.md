# Phase 2-C：历史 AC Web 动作计划受控协调预演（Dry-Run）

- Dry-Run 时间：`2026-10-16T14:43:41Z` 至 `2026-10-16T14:43:42Z`
- 最新 main：`c22323d683f92873fa4e9ebb00854ee0f9a434fb`
- 数据根：`D:\NetConsoleData`（仅只读）
- 计划目录：`D:\NetConsoleData\runtime\cache\ac_web_action_plans`（由 `PathResolver` 解析）
- Task DB：`9` 个，全部通过 SQLite `mode=ro` 打开

## 结论

本轮只执行状态证明读取和 PR #88 分类模拟，不调用 Backend、`TaskRepository`、`POST /reconcile`、cleanup 或设备命令。计划 JSON、Task Center SQLite、tombstone 和运行文件均未被本轮写入。

历史计划共 `40` 条，其中原始 `EXECUTING` `21` 条。对这批执行中计划，Dry-Run 得到：`COMPLETED=14`、`FAILED=2`、`CANCELLED=0`、`UNKNOWN_OR_UNVERIFIED=5`、活动任务 `0`、身份歧义 `0`。

本次重新核对以正式数据当前内容为准，不强行复用 Phase 2-A 的旧统计。当前 `21` 条执行中计划中，`16` 条为可核验终态候选，`5` 条仍无法核验；全库只读扫描未发现符合 owner/source/type 的活动 AC Web Task。

## 与 Phase 2-A 统计差异

| 指标 | Phase 2-A | 本次 Dry-Run | 差异 |
|---|---:|---:|---:|
| 可核验 COMPLETED | 15 | 14 | -1 |
| 可核验 FAILED | 2 | 2 | +0 |
| UNKNOWN_OR_UNVERIFIED | 4 | 5 | +1 |

差异来自当前 Task 证据重新读取后的分类变化；没有修改正式计划或 Task Center 数据，也没有把缺失证据推断为失败或成功。

## 逐条预演结果

记录编号按本轮计划文件修改时间和文件名排序生成，仅用于报告，不是原始 plan_id。

| 记录 | 局点 | 原始状态 | Task 状态 | Task 证据 | Tombstone | 证据等级 | 有效状态 | 预期变化 | 允许正式协调 | 原因 | 风险 | 人工复核 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P01 | 宁波地铁12号线 | EXECUTING | FAILED | UNIQUE_TASK_ID_SCOPE | NO | TASK_ID_SCOPE | FAILED | status EXECUTING -> FAILED; add status_reconciliation | YES | TASK_TERMINAL | MEDIUM | 必需 |
| P02 | 宁波地铁12号线 | EXECUTING | COMPLETED | UNIQUE_TASK_ID_SCOPE | NO | TASK_ID_SCOPE | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | MEDIUM | 必需 |
| P03 | 宁波地铁6号线 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P04 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P05 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P06 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P07 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P08 | 宁波地铁12号线 | EXECUTING | FAILED | UNIQUE_TASK_ID_SCOPE | NO | TASK_ID_SCOPE | FAILED | status EXECUTING -> FAILED; add status_reconciliation | YES | TASK_TERMINAL | MEDIUM | 必需 |
| P09 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P10 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P11 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P12 | 宁波地铁10号线 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P13 | 宁波地铁10号线 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P14 | 宁波地铁12号线 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P15 | hzl10 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P16 | 宁波地铁10号线 | EXECUTING | COMPLETED | DIRECT_PLAN_ID | NO | DIRECT_PLAN_ID | COMPLETED | status EXECUTING -> COMPLETED; add status_reconciliation | YES | TASK_TERMINAL | LOW | 必需 |
| P17 | 宁波地铁10号线 | EXECUTING | MISSING | MISSING_TOMBSTONE | YES | TOMBSTONE | UNKNOWN_OR_UNVERIFIED | NO_CHANGE | NO | TASK_HISTORY_CLEANED | HIGH | 必需 |
| P18 | 宁波地铁10号线 | EXECUTING | MISSING | MISSING_TOMBSTONE | YES | TOMBSTONE | UNKNOWN_OR_UNVERIFIED | NO_CHANGE | NO | TASK_HISTORY_CLEANED | HIGH | 必需 |
| P19 | hzl10 | EXECUTING | MISSING | MISSING_TOMBSTONE | YES | TOMBSTONE | UNKNOWN_OR_UNVERIFIED | NO_CHANGE | NO | TASK_HISTORY_CLEANED | HIGH | 必需 |
| P20 | hzl10 | EXECUTING | MISSING | MISSING_TOMBSTONE | YES | TOMBSTONE | UNKNOWN_OR_UNVERIFIED | NO_CHANGE | NO | TASK_HISTORY_CLEANED | HIGH | 必需 |
| P21 | hzl10 | EXECUTING | MISSING | MISSING_TOMBSTONE | YES | TOMBSTONE | UNKNOWN_OR_UNVERIFIED | NO_CHANGE | NO | TASK_HISTORY_CLEANED | HIGH | 必需 |

## 安全检查结果

- `DRY_RUN_IDEMPOTENT=PASS`：同一脱敏输入连续分类两轮，结果完全一致。
- `PLAN_CONTENT_CHANGED_BY_DRY_RUN=0`；Task DB 文件内容变化=`0`。若出现变化，只能归因于调查期间外部活动，不能归因于本工具。
- 计划文件 SHA-256 指纹数量：`40`，调查前后稳定=`True`；Task DB SHA-256 指纹数量：`9`，调查前后稳定=`True`。报告不输出完整摘要值。
- 9 个 Task DB 全库 tombstone 数量：`569`；符合 AC Web owner/source/type 且处于活动状态的 Task：`0`；本批计划关联的活动 Task：`0`。
- 与本批计划 Task ID 对应的运行文件数量：`0`。本次启动前外部进程检查未发现匹配的 NetConsole/Electron 进程，未终止或重启任何进程。
- 只读 `PRAGMA quick_check`：`ok`。
- SQLite 全部以 `mode=ro` 打开；未实例化会自动初始化或写回的 Repository/Backend/ApplicationService。未输出 plan token、digest、AC 命令、凭据或完整 Task ID；未产生生产快照、备份、临时写文件或恢复操作。

## 计划状态分布

| 原始状态 | 数量 |
|---|---:|
| `COMPLETED` | 19 |
| `EXECUTING` | 21 |

## 未来正式执行建议

本轮只有 `16` 条执行中计划满足当前 PR #88 的终态证明规则，分别为可核验的完成/失败候选；`5` 条不得自动协调。建议未来正式执行时逐条重新读取并校验同局点、同 Task ID、owner/source/type、结果 plan_id 和当前终态，不能直接复用本次 Dry-Run 结果。

`5` 条 `UNKNOWN_OR_UNVERIFIED` 必须继续保留未知，不得由 tombstone 推断成功或失败，不得删除计划，不得重新执行 AC 命令。任何状态回退只能回退计划审计字段，不能撤销已经发送到 AC 的设备动作。

正式执行前检查清单：
1. 重新读取计划文件和对应 Task DB，确认文件指纹、局点、plan_id、task_id、owner、source、合法 task_type、Task 终态及结果中的 plan_id 未发生漂移。
2. 对每条候选逐条授权，不使用全量批处理；发现新活动 Task、身份歧义、局点不一致、结果缺失或指纹变化时立即跳过并人工复核。
3. 确认 Task 终态审计已在 retention cleanup 前持久化，并验证协调与恢复、cleanup、重复终态回调之间的锁顺序和幂等键。
4. 先记录可审计的 before/after 状态及操作者、原因、时间、代码版本；失败时保留诊断证据，不把已完成 Task 改回活动状态。
5. 回退范围仅限计划终态/审计字段，不能撤销已发送到设备的动作；任何设备动作重试必须另行授权，且不属于本次协调。
6. 未知记录不做自动协调；历史 tombstone 仅证明历史已清理，不证明成功、失败或取消。

## 当前结论与后续授权

当前仅可将 `16` 条候选列入后续人工逐条审查，`5` 条继续保持未知。若要进入正式协调，需要用户另行明确授权生产计划审计字段写入、候选范围、执行窗口、并发/cleanup 停止策略及失败回退边界；本报告不构成该授权。

## 交付边界

```text
PUBLISH=NO
TAG_CREATED=NO
RELEASE_CREATED=NO
INSTALLER_BUILD=NO
MAIN_MERGE=NO
PR78_MERGE=NO
PR83_MERGE=NO
PRODUCTION_DATA_MUTATION=NO
PRODUCTION_TASK_CLEANUP=NO
AC_PLAN_FILE_MUTATION=NO
DEVICE_CONFIG_MUTATION=NO
WPS_REMOTE_WRITE=NO
PRODUCTION_RECONCILIATION=NO
DRY_RUN_ONLY=YES
```
