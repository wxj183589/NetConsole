# Task 数据生命周期设计

> 本文是 DEV COPY 夜间审计后的设计方案，不是执行记录。未执行删除、更新、插入、迁移、schema 修改、压缩或 VACUUM；等待负责人确认。

## 当前问题

审计范围仅为 `D:\NetConsoleData-dev\sites\*\db\tasks.db` 的 9 个当前局点库，SQLite 连接为 `mode=ro` 并设置 `PRAGMA query_only=ON`。

| 指标 | 当前值 |
| --- | ---: |
| `tasks.db` 物理合计 | 441,303,040 bytes（420.86 MiB） |
| `task_events.payload_json` | 145,174,109 bytes（138.45 MiB） |
| `task_snapshots.result_json` | 32,768,357 bytes（31.25 MiB） |
| `task_results.canonical_json` | 154,057,980 bytes（146.99 MiB） |
| 三类 payload 合计 | 332,000,446 bytes（约 316.62 MiB） |

三类字段合计是逻辑文本字节，不等于 SQLite 文件可直接回收的物理空间；设计使用字段审计值与物理文件值分别核算。主要问题是把任务状态、审计事件、恢复上下文、业务结果和原始响应长期复制到同一 SQLite 热表中。

## 数据边界

- **允许读取**：仅 `D:\NetConsoleData-dev`；生产根 `D:\NetConsoleData` 不写入、不作为迁移源、不做修复。
- **Task Center**：面向任务列表、恢复、重试、错误定位和结果入口，保存小而稳定的状态与摘要。
- **Artifact/History**：面向完整采集结果、原始响应、报告正文和可复查的过程历史，保存不可变内容并以 hash/引用关联任务。
- **临时执行上下文**：owner、worker/agent、checkpoint、resource keys 和短期 lease；任务结束或过期后不应继续膨胀。
- 未确认 producer/consumer 契约前按 `UNKNOWN = PROTECT`，本方案不授权直接清理历史数据。

## 当前数据职责

| 职责 | 应包含 | 当前风险 |
| --- | --- | --- |
| 任务状态 | `status`、`progress`、`stage`、`current/total`、时间、终态 | 高频 progress/state 事件重复保存完整 JSON |
| 任务审计 | 终态、错误、取消、Artifact 生命周期、操作者和版本 | `finished` 事件可能带 MB 级业务结果 |
| 业务结果 | AP/LLDP/MESH/MR、设备列表、配置和命令回显 | snapshot、canonical、event 多处复制 |
| 临时执行上下文 | owner、agent、PID、checkpoint、恢复键 | 结束后仍留在 snapshot 大 JSON 中 |

## 建议调整

### `task_events.payload_json`

本次 320,455 条事件共 145,174,109 bytes。超过 100 KiB 的 68 条记录应优先纳入 producer 契约评审；审计报告只记录元数据，不复制正文。

| 类别 | event_type | 建议 |
| --- | --- | --- |
| A：长期审计 | `finished`、`error`、`cancelled` | 保留终态、错误码/摘要、result/artifact 引用、hash、schema/producer 版本；完整结果外置。`finished` 不再携带大型业务正文。 |
| B：只保留 summary | `progress`、`state`、`log`、`file_management_waiting`、`file_management_hidden` | 保留最新状态或受限窗口内的摘要；进度变化可按时间桶/有效变化去重。原始过程进入可选 History。 |
| C：转 Artifact 引用 | `artifact_finalized`、`artifact_rejected`、`file_management_descriptor` | 保留 `artifact_id`、kind、size、sha256、状态、路径相对引用和错误摘要；文件/响应正文只在 Artifact。 |

### `task_snapshots.result_json`

当前 5,940 行、32,768,357 bytes；最大记录约 1.70 MiB。snapshot 应只承担恢复和列表展示，不承担业务结果仓库。

**必须保留**：`task_id`、`task_type`、名称、站点、创建/开始/更新时间/结束时间、`status`、`progress`、`stage`、`current`、`total`、owner/device/agent、PID、`resource_keys_json`、checkpoint/recovery state、producer/schema 版本、文本完整性字段、`result_id`、`result_hash`、`result_summary_json`、Artifact 引用及过期/确认/驳回信息。

**外置**：完整 `result_json`、完整设备列表、AP 结果、LLDP 结果、MESH/MR 结果、大型采集响应、原始命令回显和报告正文。snapshot 只保留稳定摘要和可验证的 Artifact 指针。

建议的瘦身结构：`identity`、`lifecycle`、`recovery`、`result_pointer` 四组字段；`result_pointer` 只允许摘要、hash、size、artifact_id/kind，不嵌套业务数组。

### `task_results.canonical_json`

当前 3,572 行、154,057,980 bytes；P50 为 770 bytes，P95 为 137,290 bytes，最大 4,753,798 bytes；410 条超过 100 KiB（合计 145,953,219 bytes）。按 `sha256` 发现 54 个重复组、1,072 行，估算重复超额约 73,062,651 bytes，但这是 hash 重复证据，不等于已经存在可用 Artifact，也不等于可立即删除。

审计发现 59 行包含 `artifact_id` 或 `content_sha256` 字段标记；数据库中的 `task_result_storage_rollout` / `_audit` 只是 rollout 控制表，没有发现可据此确认正文已外置的 Artifact 内容索引。因此：

- **保留**：`result_id`、`task_id`、终态类型、`sha256`、`byte_size`、`schema_version`、创建时间，以及小型 `result_summary_json`。
- **外置**：canonical 中完整设备/AP/LLDP/MESH/MR 结果、原始响应、命令输出、报告正文和可由 hash 定位的重复内容。
- **前置条件**：只有确认 Artifact 已持久化、可读、hash 一致且所有 consumer 已切换，才可在后续迁移阶段移除 canonical 正文；本阶段不执行。

## 最小改动落地顺序（待确认）

1. 先冻结字段契约：Task Center 只读状态/summary/pointer，Artifact owner 负责正文，History owner 负责可选过程审计。
2. 先改 producer 的新写入形状：progress/state/log 做 summary；终态只写 summary + pointer；大型正文单写 Artifact。
3. 增加引用可读性、hash、schema/producer 版本和 orphan 检查；旧行保持只读兼容。
4. 在 DEV COPY 做 COPY/verify/parity 演练，确认 UI、恢复、导出和重试 consumer 后，再另行审批历史迁移与物理回收。

## 预计空间收益

收益是对**未来写入和迁移后逻辑占用**的估算，不代表本次审计已改变 420.86 MiB 文件；不执行 VACUUM 时 SQLite 文件也不会自动缩小。

| 场景 | 预计可避免/外置的 payload | 任务库逻辑目标（估算） |
| --- | ---: | ---: |
| 保守：仅压缩 progress/state/log，终态保留摘要 | 约 100–130 MiB | 约 290–320 MiB |
| 推荐：加上 snapshot 结果外置、canonical >100 KiB 外置 | 约 220–270 MiB | 约 150–210 MiB |
| 激进：重复 hash 去重且 Artifact 全量可验证 | 额外约 70 MiB | 约 80–150 MiB |

推荐目标采用中间区间，不把重复 hash 的 73 MB 当作已实现收益；实际收益必须由迁移前后字节、引用完整性和 consumer parity 共同确认。

## 相关机器报告

- `TASK_EVENTS_RETENTION_ANALYSIS.json`
- `TASK_SNAPSHOT_RETENTION_ANALYSIS.json`
- `TASK_RESULTS_RETENTION_ANALYSIS.json`
- 基线：`TASK_DB_USAGE_REPORT.json`、`TASK_PAYLOAD_ANALYSIS_REPORT.json`
