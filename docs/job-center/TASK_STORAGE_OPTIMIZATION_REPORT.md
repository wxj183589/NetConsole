# tasks.db 表级空间审计、重复 payload 清理与物理瘦身报告

日期：2026-08-27
范围：上一轮 `D:\NetConsoleData-dev` DEV candidate 实测结果；`D:\NetConsoleData` 未读取、未复制、未写入、未迁移、未删除。
状态：本报告保留上一轮实测证据；本次 main 集成只做代码、契约和隔离 fixture 验证，不重复执行活动 DEV compact。

## 结论

本轮没有按 `Recent10` 机械删除任务历史，也没有删除全部 `task`、`task_events` 或 `task_snapshots`。空间主要来自 `task_results.canonical_json` 的重复完整结果。已将结果正文迁移为 UTF-8 hash-keyed、zlib 压缩的 `task_result_blobs`，读路径 Blob-first、缺失/损坏/hash 不一致/非法 JSON 均 fail closed；随后通过 candidate rebuild、`VACUUM INTO`、`quick_check`、任务列表/详情/结果/Online MR parity 后原子替换 DEV 数据库。

上一轮 DEV 物理瘦身阶段的主文件累计指标为（`PREVIOUS_DEV_MEASURED_RESULT`）：

```text
TASKS_DB_BEFORE_BYTES=418013184
TASKS_DB_AFTER_BYTES=236990464
TASKS_DB_RECLAIMED_BYTES=181022720
TASKS_DB_RECLAIM_PERCENT=43.305505%
```

这是上一轮阶段（Blob migration 后、physical compact 前）的 before/after。若从本轮最早的全站审计基线计算，完整阶段为 `457744384 -> 236990464`，累计减少 `220753920` 字节（`48.226462%`）；两组数字分别对应不同阶段，未混用。

`CURRENT_CODE_INTEGRATION_RESULT` 是本次基于最新 `github/main` 的代码集成与隔离测试结果，不自动承诺再次产生上述磁盘收益；任何 DEV/Production 物理操作都必须另行批准并使用候选库。

## 表级空间审计

审计文件：

- `D:\study\diagnostic\NetConsole\tasks-db-space-audit\TASKS_DB_SPACE_AUDIT.md/json`：physical compact 前审计；
- `D:\study\diagnostic\NetConsole\tasks-db-space-audit\after-compact\TASKS_DB_SPACE_AUDIT.md/json`：physical compact 后审计；
- `D:\study\diagnostic\NetConsole\tasks-db-space-audit\final-integrity\TASK_STORAGE_INTEGRITY_AUDIT.md/json`：结果 authority、Blob、snapshot、event、Online MR、Ground 引用和 artifact manifest 完整性审计。

脚本优先探测 SQLite `dbstat`。本机 Python SQLite 未提供 `dbstat`，所以 `table_bytes/index_bytes` 使用已记录的逻辑字段/key 权重估算；`row_count`、`page_count`、数据库主文件字节和每个 TEXT/JSON/BLOB payload 的 NULL/平均/最大/总字节由 SQLite 查询精确取得。报告不会把估算表字节冒充为 dbstat 物理页字节。

### TASKS_DB_TOP_TABLES

物理 compact 前按估算分配字节排序：

1. `宁波地铁12号线.task_results`：3,904 rows，table 162,574,095，index 1,511,456，合计 164,085,551 bytes；
2. `宁波地铁12号线.task_events`：193,503 rows，table 98,981,669，index 20,886,030，合计 119,867,699 bytes；
3. `hzl10.task_events`：89,272 rows，table 49,589,134，index 9,719,345，合计 59,308,479 bytes；
4. `hzl10.task_results`：808 rows，table 16,201,856，index 327,125，合计 16,528,981 bytes；
5. `宁波地铁10号线.task_events`：22,861 rows，合计 13,963,304 bytes。

物理 compact 后的 Top：

1. `宁波地铁12号线.task_events`：194,151 rows，合计 123,267,927 bytes；
2. `hzl10.task_events`：89,272 rows，合计 60,046,036 bytes；
3. `宁波地铁10号线.task_events`：22,861 rows，合计 14,313,893 bytes；
4. `宁波地铁1号线.task_events`：22,248 rows，合计 11,916,359 bytes；
5. `宁波地铁12号线.task_result_blobs`：2,925 rows，合计 5,889,284 bytes。

```text
TASKS_TOP_TABLE_BEFORE=宁波地铁12号线.task_results
TASKS_TOP_TABLE_AFTER=宁波地铁12号线.task_events
```

因此问题的答案是：瘦身前主要是 `task_results` 的完整结果正文和 `task_events` 的既有审计轨迹；瘦身后主要剩余 `task_events`，因为其状态轨迹仍是 Task Detail 的审计数据，未按假设的 N 条记录删除。

### Site bytes

下表使用本轮最早全站审计到最终 compact 后的主文件字节，包含前置 Blob rollout 和本轮 physical compact；`demo`/`legacy` 的增长是 schema/SQLite 页粒度，未进行不安全的强行重建。

| site | before bytes | after bytes | net reduction bytes | result |
| --- | ---: | ---: | ---: | --- |
| demo | 94,208 | 102,400 | -8,192 | SQLite page floor |
| hzl10 | 95,297,536 | 62,971,904 | 32,325,632 | PASS |
| legacy-dfd356e96ea0 | 102,400 | 110,592 | -8,192 | SQLite page floor |
| sxl1 | 561,152 | 585,728 | -24,576 | SQLite page floor |
| 宁波地铁10号线 | 36,085,760 | 15,638,528 | 20,447,232 | PASS |
| 宁波地铁12号线 | 291,942,400 | 137,138,176 | 154,804,224 | PASS |
| 宁波地铁1号线 | 23,478,272 | 13,357,056 | 10,121,216 | PASS |
| 宁波地铁6号线 | 8,478,720 | 6,381,568 | 2,097,152 | PASS |
| 杭州地铁4号线-信号-A网 | 1,572,864 | 585,728 | 987,136 | PASS |
| 杭州地铁4号线-信号-B网 | 131,072 | 118,784 | 12,288 | PASS |

实际 candidate compaction 的物理输入还包含当时存在的 SQLite sidecar；该组逐站记录见 `TASK_RESULT_COMPACTION_ALL_APPLY.json`。8 个站点原子替换成功，所有 candidate `quick_check=ok`；两个小库因 compact 后没有严格小于 before 而保留源库。

站点目录总空间（包含原有业务文件和按安全策略保留的 rollback 副本）为：

```text
SITE_TOTAL_BEFORE=8269204955
SITE_TOTAL_AFTER=8048102875
SITE_TOTAL_RECLAIMED_BYTES=221102080
EXTERNAL_BYTES_CREATED=1291091968
```

`EXTERNAL_BYTES_CREATED` 是本轮及前置 DEV cutover 尝试保留的 rollback/backup 字节，已计入站点总空间，没有把搬到 backup 的数据算作回收；本轮 Blob migration 与 compact candidate 本身没有留下 archive/history 无限增长库，candidate/staging 文件已清理。

## Payload 与 authority 决策

物理 compact 前，`task_results.canonical_json` 的精确 payload 字节合计为 `187,171,489`；compact 后仅未替换的小库保留 `533` 字节。结果行仍保留任务绑定、事件类型、hash、byte size、schema 和创建时间等元数据；已 ready 的正文唯一存放在 `task_result_blobs`，以 `content_sha256` 去重。新 runtime rows 的 `canonical_json` 为空，不会在 compact 后被下一次任务写回；旧 full-only/dual rows 仍由 Blob-first/legacy read-through 兼容读取。

```text
TASK_EVENTS_ROWS_BEFORE=340099
TASK_EVENTS_ROWS_AFTER=340747
TASK_SNAPSHOTS_ROWS_BEFORE=6097
TASK_SNAPSHOTS_ROWS_AFTER=6147
DUPLICATE_PAYLOAD_ROWS_REMOVED=1208
OBSOLETE_SNAPSHOT_ROWS_REMOVED=0
```

before/after 审计跨越了 DEV 运行期间的业务写入，观察到新增 50 个 task/snapshot 和 648 个 event；physical compact 本身没有删除任何 task/event/snapshot。`DUPLICATE_PAYLOAD_ROWS_REMOVED=1208` 来自最初 dry-run 的 1,029 条宁波12号线重复正文和后续其余站点 179 条重复正文；重复的是完整正文副本，不是删除任务行。

Payload 审计还覆盖了每个发现的 JSON/TEXT/BLOB 字段：NULL count、平均长度、最大长度、总 payload bytes 和 duplicate count 均保存在上述 JSON。`task_events` 的历史 payload 中仍有少量旧格式 result-like 行，但未发现可安全按 Recent10 规则删除的完整重复事件组；新写入的 terminal event 持久化为 result reference/hash/summary，实时 websocket 仍可发送完整业务结果给当前消费者。

## Snapshot、任务历史和清理边界

`task_snapshots` 是每个 task 的 current/recovery 投影主表，不是无限历史表；当前各站点为一 task 一条 snapshot，没有发现可安全退役的第二条 snapshot，所以 `OBSOLETE_SNAPSHOT_ROWS_REMOVED=0`。它继续保留：

- `PENDING`、`RUNNING`、`PAUSED`（如有）、`RECOVERY` 和最新 terminal status/progress；
- `result_id`、result hash/summary、artifact/result reference；
- Online MR 当前 session 关联和 Ground current mapping 所需的 task id 关系。

统一 `TaskCleanupService` 提供 `can_cleanup`、`preview_cleanup` 和 `cleanup_tasks`。明确清理只接受 terminal task，并在同一事务中显式删除 task-owned event/result/snapshot 行；active 状态、Online MR mapping、Ground 引用、resource key、artifact/package/result reference、未知状态或不可验证 authority 均 fail closed。清理不删除 artifact 文件、Ground 数据、Online MR session、归档文件，也不依赖 FK cascade；未新增 `TaskHistoryStore`。

本轮 DEV 没有为了获得空间执行全量历史 task 删除；完整性审计结果为所有可用站点 PASS，Online MR session 为 9 行且无孤儿，Ground 引用无孤儿。

## Task Center parity 与测试

列表查询不再选择 `task_results.canonical_json` 或 snapshot full result；详情、结果打开、重放和下载引用读取走 Blob-first authority。candidate parity 覆盖 task list、task detail、result content、status counts、result/artifact reference、Online MR mapping 和 sample 任务。任务重启恢复继续使用当前 snapshot/owner/recovery 契约。

```text
TASKS_DB_CANONICAL_RESULT_AUTHORITY=PASS
TASKS_DB_DUPLICATE_PAYLOAD_REMOVED=PASS
TASKS_DB_OBSOLETE_SNAPSHOT_RETIREMENT=PASS
TASK_LIST_PARITY=PASS
TASK_DETAIL_PARITY=PASS
TASK_RESTART_RECOVERY=PASS
TASKS_DB_QUICK_CHECK=PASS
TASKS_DB_SIZE_REDUCTION=PASS
```

已通过的定向回归包括：

- `tests/test_job_center_cleanup.py` + `tests/test_task_storage_optimization.py`：7 passed；
- `tests/test_job_center_web_api.py`：46 passed；
- `tests/test_job_center.py`：21 passed；
- `tests/test_task_result_rollout.py`：19 passed；
- `tests/test_task_repository_storage_governance.py`：26 passed；
- `tests/test_site_sync_task_merge.py`：15 passed；
- `tests/test_database_functional_compatibility.py`：10 passed；
- `tests/test_integrated_site_package_validation.py`：18 passed；
- `tests/test_storage_no_reinflation.py`：15 passed；
- Ruff、`py_compile`、`git diff --check`：PASS。

本轮没有重新跑 29 张 GUI 截图；自动化覆盖了 Task Center API/list/detail/result/cleanup contract。真实安装包、设备现场、WPS/Excel 和 Update All 的现场验收仍沿用既有报告的独立状态，不能由本报告的数据库 parity 代替。

## 最终边界

```text
PRODUCTION_DATA_TOUCHED=NO
TASKS_DB_SPACE_AUDIT=PASS
TASKS_DB_SIZE_REDUCTION=PASS
TASK_LIST_PARITY=PASS
TASK_DETAIL_PARITY=PASS
TASK_RESTART_RECOVERY=PASS
```

主线整体扩展 Gate 仍不能写成全部 PASS：既有工程态/Update All/完整 Python baseline 的未通过项仍需按既有验收报告单独处理；本轮 tasks.db 结果不覆盖这些外部设备和 GUI 现场限制。
