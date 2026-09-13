# Task Event Retention 验收记录

## 1. 结论

本专项将 `tasks.db.task_events` 定义为短期任务运行轨迹，默认保留 7 天。自动保留只删除已经进入正式终态且 `finished_time` 早于 cutoff 的 `task_events`；任务快照、任务主记录、结果引用、结果 Blob、tombstone、Artifact、Log Center、Ground、Online MR、MESH、原始数据和业务数据库均不在删除范围内。

`CODE_STATUS=READY_FOR_MAIN`

本轮没有执行 Production retention cleanup、VACUUM、VACUUM INTO、数据库替换、rollback 或 Production GC。

## 2. 产品语义与边界

- Task Center 继续承担当前/近期任务查看。
- `task_events` 只承担短期运行过程记录，不是长期日志或审计档案。
- terminal task 的最终状态、时间、成功/失败摘要、错误摘要、结果引用和 Artifact 引用继续由现有任务快照/结果 authority 保留。
- Log Center 继续使用独立的 `app.log` / managed log roots；长期日志不依赖 `task_events`。
- Artifact / File Store 继续保留长期文件与结果；Business DB 继续保留正式业务事实。
- 用户“从列表移除”仍走既有 Operational Cleanup，不被 retention 替代。
- 未新增 TaskHistoryStore、Task Archive DB、第二套历史 API 或历史浏览器。
- 未把 `ProductionMaintenanceCapability`、rollback owner、evidence bundle 或 Production gate 引入普通任务生命周期。

## 3. 保留策略

| 项目 | 规则 |
|---|---|
| 默认天数 | 7 天 |
| 可选天数 | 3、7、14、30 天 |
| 可清理状态 | `COMPLETED`、`FAILED`、`CANCELLED` |
| cutoff | `finished_time < now - retention_days` |
| 永久保护状态 | `PENDING`、`STARTING`、`RUNNING`、`STOPPING` |
| 外部保护 | Online MR current mapping、Ground current mapping；外部引用不可验证时 fail-closed |
| 删除对象 | 仅 `task_events` |
| 不删除对象 | `task_snapshots`、`task_results`、`task_result_blobs`、任务主记录、tombstone、Artifact、日志、业务数据 |
| 触发方式 | 复用桌面运行时 startup maintenance hook；`last_task_event_cleanup_at` 距今不足 24 小时则跳过 |
| 调度边界 | 未新增 scheduler、daemon 或 Windows Scheduled Task |
| 物理回收 | 不自动执行 VACUUM / VACUUM INTO |

清理在 `TaskRepository` 事务内进行；单个受限批次最多 500 个任务，事件删除批次限制在 1000--5000 行范围内。批次失败会回滚该批次，且不会触碰快照、结果、tombstone 或外部文件。

## 4. 消费者审计

消费者矩阵见 [TASK_EVENT_CONSUMER_MATRIX.md](./TASK_EVENT_CONSUMER_MATRIX.md)。审计结论如下：

- Task Center 列表、详情和 Task API 的核心摘要来自快照、结果引用和 authority index；事件清空后任务仍可查看。
- Task Detail 在终态任务事件为空时显示“详细运行记录已按保留策略清理”，不会显示“任务不存在”。
- Log Center 的长期日志调用链不读取 `task_events`。
- Online MR 和 Ground 的当前映射在 retention 删除前只读检查并保护。
- site_import 的任务状态、自动切换局点和详情路径不依赖长期事件时间线。
- File Management、Artifact、Export、Agent、MESH、Online MR 正式结果、Ground 正式结果和业务数据均保持各自 authority。

`LONG_TERM_LOG_AUTHORITY=Log Center managed logs (app.log/managed log roots)`

`LOG_CENTER_DEPENDS_ON_TASK_EVENTS=NO`

## 5. Settings UI

系统设置新增“任务运行记录保留时间”，选项为 3 天、7 天（默认）、14 天、30 天。帮助文案为：

> 仅影响任务运行过程记录，不删除日志中心、任务结果、导出文件或业务数据。

旧安装缺少该字段时在内存中使用 7 天默认值；没有新增 schema migration，也没有启动时批量改写旧任务数据库。

## 6. 查询效率

在宁波地铁12号线 `tasks.db` 的只读连接上执行了 retention 相关查询计划检查：

- `task_events WHERE task_id IN (?)` 使用 `idx_task_events_task_sequence (task_id, sequence DESC)`。
- terminal snapshot 候选查询使用 `idx_task_snapshots_status_updated (status, updated_time DESC)`。

因此事件大表按候选任务 ID 定向读取，不新增索引。

## 7. Production 只读分布

报告文件：`D:\study\NetConsole-Workspace\diagnostic\task-event-retention-20260913\TASK_EVENT_AGE_DISTRIBUTION.json`

报告覆盖 `D:\NetConsoleData` 下现有 9 个 `sites/*/db/tasks.db`，使用 SQLite `mode=ro&immutable=1`。报告生成器输出 `mutation=NONE`，并在刷新报告前后核对 9 个数据库的 size/mtime，未观察到由本报告脚本造成的文件变化。

### 全量 Production 事件分布

| 年龄 | terminal_task_count | event_rows | estimated_bytes |
|---|---:|---:|---:|
| `<=3d` | 38 | 9,584 | 7,412,422 |
| `3-7d` | 367 | 16,708 | 19,975,620 |
| `7-14d` | 536 | 45,162 | 46,497,303 |
| `14-30d` | 1,131 | 81,550 | 81,224,964 |
| `30-90d` | 5,453 | 279,514 | 254,542,939 |
| `>90d` | 0 | 0 | 0 |
| 合计 | 7,525 | 432,518 | 409,653,248 |

当前事件 payload 的逻辑字节合计为 196,021,255；当前 Python SQLite 构建不提供 `dbstat` 虚拟表，因此无法把 `task_events` 的物理页大小宣称为精确值。报告中的 `estimated_bytes` 是按事件行比例分摊的可复现估算，不等同于 DELETE 后立即释放的磁盘空间。

对宁波地铁12号线单库，当前只读计数为 212,449 个事件行，`tasks.db` 文件大小为 160,104,448 bytes；7 天预测为 203,658 个事件行、75,468,368 个逻辑 payload bytes。

### 7 天预测

- 预计可清理事件行：406,226
- 预计可清理逻辑 payload：186,332,593 bytes
- 按报告估算的事件页分摊：382,265,206 bytes

上述数值只用于容量评估。本轮未删除这些事件，也未执行物理 compact。

## 8. 自动化验证

### Retention 定向测试

- terminal 8 天前删除，6 天前保留
- RUNNING 任务保留
- FAILED 最终摘要保留
- Online MR current mapping 保护
- Ground current mapping 保护
- 中断时当前事务回滚
- 重跑幂等，重启后不会重新膨胀
- 7→14 与 14→3 设置变化生效
- Log Center 文件不受影响

定向跨域回归：`272 passed, 3 warnings`。

### Full Gate

- Python：`4860 passed, 2 skipped`
- Renderer：`1300 passed`
- Electron：`298 passed`
- Architecture：`12/12 PASS`
- Main contract smoke：`12 passed`
- Documentation path guards：`22 passed`
- Ruff：`All checks passed`
- `NEW_FAILURES=0`
- `FULL_GATE=PASS`

Renderer 与 Electron 的验证为自动化测试和构建契约；真实设备、安装包现场启动和人工 GUI 验收不在本专项范围内。

## 9. 数据保护与运行态注意事项

- `PRODUCTION_DATA_MUTATED=NO`：本专项的读取、报告和验证没有执行 Production DML、DELETE、VACUUM、VACUUM INTO 或替换。
- 最终只读复核显示 `hzl10` 在本轮期间出现过文件修改时间漂移但 size 未变；同一时段该站 `devices.db` 及 sidecar 也有运行态时间变化。该漂移不能归因于本专项脚本，且刷新报告前后未观察到本次报告脚本造成的变化。
- 因 Production 仍可能存在外部运行态写入，未来首次实际 retention cleanup 前必须重新建立稳定基线，并按现有运行维护流程确认 writer stop；本验收不授权也不执行该清理。
- 当前运行时不支持 `dbstat` 时，只能把逻辑 payload 与估算页分摊用于容量判断；若需要精确物理页证据，应在支持 `dbstat` 的只读环境重新生成报告。

## 10. 最终字段

```text
DEFAULT_RETENTION_DAYS=7
SUPPORTED_RETENTION_OPTIONS=3,7,14,30
TASK_EVENT_CURRENT_ROWS=432518 (9个Production tasks.db；宁波地铁12号线=212449)
TASK_EVENT_CURRENT_BYTES=196021255 (logical payload bytes; physical dbstat unavailable)
TASK_EVENT_CURRENT_PHYSICAL_BYTES=UNAVAILABLE_DBSTAT
<=3D_ROWS=9584
3_7D_ROWS=16708
7_14D_ROWS=45162
14_30D_ROWS=81550
30_90D_ROWS=279514
GT_90D_ROWS=0
PREDICTED_ROWS_REMOVED_AT_7D=406226
PREDICTED_LOGICAL_BYTES_AT_7D=186332593
LONG_TERM_LOG_AUTHORITY=Log Center managed logs (app.log/managed log roots)
LOG_CENTER_DEPENDS_ON_TASK_EVENTS=NO
ACTIVE_TASK_PROTECTION=PASS
ONLINE_MR_PROTECTION=PASS
GROUND_PROTECTION=PASS
FINAL_ERROR_SUMMARY_PRESERVED=PASS
TASK_DETAIL_AFTER_EVENT_RETENTION=PASS
SITE_IMPORT_REGRESSION=PASS
REMOVE_FROM_LIST_REGRESSION=PASS
RETENTION_IDEMPOTENT=PASS
RETENTION_TRANSACTION_ATOMIC=PASS
AUTO_VACUUM_ADDED=NO
NEW_SCHEDULER_ADDED=NO
PRODUCTION_DATA_MUTATED=NO
FULL_GATE=PASS
NEW_FAILURES=0
CODE_STATUS=READY_FOR_MAIN
```
