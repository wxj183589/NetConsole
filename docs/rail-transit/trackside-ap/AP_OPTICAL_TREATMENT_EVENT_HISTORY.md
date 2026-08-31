# 轨旁 AP 光衰 Treatment Event History 实施说明

## 结论

轨旁 AP 光衰应采用 **Current Summary + Treatment Event History** 双层模型：

- `ap_optical_treatment` 继续是每个 `site_id + ap_identity` 一行的当前处理摘要；
- 新增 `ap_optical_treatment_events`，一条真实异常生命周期一行，允许同一 AP
  保存多个已解决或正在发生的事件；
- summary 是事件历史的当前投影和查询优化，不再承担完整历史事件明细；
- 本文记录已完成的 schema migration、runtime 生命周期、Development 回填和导出
  验收结果。

本实施由 2026-08-31 对开发数据 `hzl10` 的只读审计支撑。实施前旧有效候选中有
`CANONICAL_MISSING_CURRENT_RECORD=42`，另有 `RECURRENCE_EVENT=26`；当前
`ap_optical_treatment` 为 55 行，`recurrence_count` 总和为 0；该值已在回填后按
事件数重建。证据矩阵交付在
Workspace 的 diagnostic 目录，未纳入 Git。

## 1. 当前问题和边界

上一轮旧处理记录的统计为：

| 指标 | 数量 |
| --- | ---: |
| 旧处理记录 | 519 |
| 旧无光筛查记录 | 417 |
| 旧有效候选 | 102 |
| 当前 canonical summary | 55 |
| 严格逐行差异审计 | 75 |
| `RECURRENCE_EVENT` | 26 |
| `SIDE_SPLIT` | 3 |
| `VALID_HISTORY_COLLAPSED_BY_BOUNDED_V1` | 2 |
| `CANONICAL_MISSING_CURRENT_RECORD` | 42 |
| `IDENTITY_UNRESOLVED` | 2 |

`102 - 55 = 47` 是净行数差，不是 physical AP 的一一对应差异数。本实现不把旧
Excel 的行数直接当数据库行数，也不把旧导出结果直接当 canonical authority。

本轮执行边界：

- schema migration、runtime 写入和受控 backfill 只作用于
  `D:\NetConsoleData-dev\sites\hzl10\db\devices.db`；
- 回填工具默认 dry-run，只有显式 `--apply` 才写入；本轮 Development apply 在
  事务中完成，当前 summary 仍为 55 行；
- 不使用 AP 名、站点名、旧行号、端口顺序或相似度匹配推断身份；
- `D:\NetConsoleData` 只作为越界路径拒绝规则，不读取其文件内容；
- 不重做 `optical_current` / `optical_history` 的 Current + bounded Recent 架构。

Development 实施结果：`ap_optical_treatment_events` 共 113 行，其中 51 行
`OPEN`、62 行 `RESOLVED`；42 条 canonical missing 中 35 条完整回填、7 条部分
回填、0 条未恢复；26 条 recurrence 中 24 条回填、2 条 legacy-only 保留为跳过。
8 条 recurrence 证据落在当前 summary 的权威生命周期内并合并到该 event，另新增
16 条 recurrence event，因此总事件数不是按候选数机械相加。第二次 dry-run 为
零新增、零更新，冲突和 unresolved 均为 0。

## 2. 42 条 canonical missing 来源追踪结论

### 2.1 逐条结论

42 条记录均能通过精确 serial/MAC 和已有持久化映射解析到唯一 AP UUID，当前
canonical treatment 行均为 0 命中，且均能在旧 AP/FIT/交换机证据链中找到异常样本。
按侧别重新约束来源后，结果为：

| 分类 | 数量 | 解释 |
| --- | ---: | --- |
| `RECOVERABLE_FROM_EXISTING_PERSISTED_EVIDENCE` | 35 | 精确身份、异常起点和恢复/关闭边界足够可靠，可由受控工具生成 event 草稿 |
| `PARTIALLY_RECOVERABLE` | 7 | 精确身份和异常发生可确认，但旧记录时间或恢复边界不能完整对齐 |
| `OCCURRENCE_ONLY_RECOVERABLE` | 0 | 本批没有仅靠弱证据才能确认发生的行 |
| `LEGACY_ONLY_EVIDENCE` | 0 | 本批没有只剩旧 Excel、且没有独立持久化证据的行 |
| `NOT_RECOVERABLE` | 0 | 本批没有达到该分类的行 |
| `IDENTITY_UNRESOLVED` | 0 | 本批没有新的身份冲突；上一轮独立的 2 条 unresolved 不在这 42 条中 |
| **合计** | **42** | 分类互斥且完整 |

35 条完整项至少同时具备：唯一持久化 AP identity、精确异常时间命中，以及精确
恢复时间命中或旧记录明确为未关闭。7 条部分项具备异常事件样本和唯一身份，
但缺少异常起点或恢复边界的可靠时间命中。raw log path 的存在性只作为采集线索，
未读取日志内容，因此没有把它单独升级成 `OCCURRENCE_ONLY_RECOVERABLE`。

### 2.2 42 条共同 root cause

```text
CANONICAL_MISSING_ROOT_CAUSE_COUNTS={
  PRE_BOUNDED_V1_HISTORY_NOT_BACKFILLED: 42
}
```

这里的名称表示：旧 builder 能够从旧 history/current/offline/交换机来源投影出
处理记录，但 bounded v1 切换时没有把旧生命周期回放为 canonical treatment row。
它不是“当前 42 条一定已经从文件中删除”的证明，也不是允许直接从旧 Excel
回填的授权。

当前开发库的证据范围为：

- `optical_history`：`2026-08-31T13:43:35` 起的 bounded 有效变化，按资源/侧别
  保留最近 10 条；
- `ap_optical_history`：`2026-07-28T19:11:08` 至 `2026-08-13T17:42:50` 的 AP
  侧历史遥测，可作为旧时间段事件证据，但不是 treatment event ledger；
- `ap_optical_treatment`：55 行，唯一约束为 `UNIQUE(site_id, ap_identity)`，42
  条旧候选没有对应当前行；
- FIT-AP resource/history、switch optical/interface/LLDP history、collect_runs
  和 raw path 提供身份、采集代次、交换机端口和来源 revision 的辅助证据。

### 2.3 身份解析规则

恢复工具必须沿用当前 canonical identity：

1. 有效 `serial_number` 的精确匹配；
2. 已持久化的 canonical `ap_uuid` / identity entity / alias mapping；
3. 规范化 AP MAC 的精确匹配；
4. 对 SWITCH-only 记录，仅允许 `site + switch device + interface`，再结合时间
   范围内 LLDP/AP association 证据确认。

多个候选、身份冲突或只剩 AP 名称时必须返回 `IDENTITY_UNRESOLVED` 或 conflict，
不得选择第一条候选。AP 名、站点、跨 AC 的 APID、端口排列和旧 Excel 行位置都
不是 identity key。

## 3. 26 条 recurrence 追踪结论

### 3.1 数据事实

当前 summary 的 `recurrence_count` 为 55 行全 0、总和 0；当前状态分布为 51
条 `ABNORMAL`（AP 21、BOTH 5、SWITCH 25）和 4 条 `NORMAL/RESOLVED`。

旧审计中的 26 条 `RECURRENCE_EVENT` 经过同一套精确身份和侧别来源规则后：

| 分类 | 数量 |
| --- | ---: |
| `RECOVERABLE_FROM_EXISTING_PERSISTED_EVIDENCE` | 1 |
| `PARTIALLY_RECOVERABLE` | 23 |
| `OCCURRENCE_ONLY_RECOVERABLE` | 0 |
| `NOT_RECOVERABLE`（其中 `LEGACY_ONLY_EVIDENCE=2`） | 2 |
| **合计** | **26** |

按本任务要求的四分类输出，2 条没有独立历史异常证据的旧证据行归入
`RECURRENCE_NOT_RECOVERABLE`；它们的证据属性仍保留为 `LEGACY_ONLY_EVIDENCE`，
不代表可以从旧 Excel 自动回填。

26 条的共同解释为：

```text
RECURRENCE_COUNT_ZERO_ROOT_CAUSE=PRE_BOUNDED_V1_SUMMARY_HAS_NO_REPLAYED_LIFECYCLE
```

当前 `update_ap_optical_treatment()` 的逻辑是：同一 AP 的当前 summary 已存在，
且上一摘要 `treatment_status == RESOLVED` 时，下一次有效异常才把
`recurrence_count` 加一；恢复分支把当前摘要更新为 `RESOLVED`。这段逻辑从
`538db1c3` 引入 bounded v1 Current/History 模型，当前代码和测试都明确保持
“一个 AP 一条 summary”。

旧 builder 则从 AP history、switch history、FIT-AP resource/history、offline
ledger 等来源扫描时间线并生成多条投影记录。bounded v1 收口和旧 builder 退役
之间没有执行历史生命周期 replay/backfill。因此，当前 0 更符合“旧复发没有被
回放到 summary cache”的数据边界，而不是本轮可证明的 `was_resolved` 运行时
判断故障。正式 runtime 改造应在 event history 落地后再由事件表派生
`recurrence_count`，而非继续扩大 summary 的职责。

### 3.2 发生事实和细节的区分

- 26 条 occurrence 在旧审计中均有记录；其中 24 条还能在当前开发库的独立异常
  历史中找到，2 条只保留旧记录与当前 identity/normal-side 线索；因此 canonical
  persisted event occurrence 的保留是 **PARTIAL**，不是“26 条全部从世界上消失”。
- 事件 detail 的保留是 **PARTIAL**：1 条复发可完整关联，23 条可确认发生但
  起止/恢复边界不完整，2 条不能由当前独立异常历史生成 event。
- 当前状态没有因本次审计改变：55 条 summary 仍可读，故 current state
  preservation 为 **YES**。

## 4. Authority 和来源优先级

当前 event backfill/runtime 读取使用以下优先级，优先级高的来源可否定低优先级
的冲突推断；冲突不得静默覆盖：

1. canonical persisted `optical_history`，在其 bounded coverage 内作为有效异常
   生命周期的第一来源；
2. `optical_current` + `ap_optical_treatment`，用于当前状态、身份和 summary
   字段补充；当前值不能反向伪造已经过去的历史变化；
3. `collect_runs`、已持久化 raw evidence 及 source revision，用于确认采集代次、
   原始来源和可复核链路；raw path 存在本身不等于内容已验证；
4. 其它正式 bounded Recent，如 FIT-AP resource Recent、switch module/interface/
   LLDP Current/Recent；只作为明确关联证据；
5. 旧业务导出和 Excel，作为 legacy historical evidence，不能作为数据库 authority，
   不能覆盖前四级来源，也不能绕过 identity resolution。

旧 Excel 只有在后续另行批准的受控导入任务中才可能成为 candidate input；本设计
不授权从 Excel 直接 `INSERT`。

## 5. Implemented schema

### 5.1 事件表

已新增并由 `2026.09.01.ap_optical_treatment_event_history_v1` schema version
管理：

```sql
CREATE TABLE ap_optical_treatment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,
    site_id TEXT NOT NULL,
    ap_identity TEXT NOT NULL,
    ap_uuid TEXT NOT NULL DEFAULT '',
    ap_name TEXT NOT NULL DEFAULT '',
    ap_mac TEXT NOT NULL DEFAULT '',
    ap_mac_normalized TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    ap_id TEXT NOT NULL DEFAULT '',
    station_id TEXT NOT NULL DEFAULT '',
    station_name TEXT NOT NULL DEFAULT '',
    section_name TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT '',
    first_abnormal_side TEXT NOT NULL DEFAULT 'UNKNOWN',
    worst_abnormal_side TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_abnormal_side TEXT NOT NULL DEFAULT 'UNKNOWN',
    switch_device_id TEXT NOT NULL DEFAULT '',
    switch_name TEXT NOT NULL DEFAULT '',
    switch_interface TEXT NOT NULL DEFAULT '',
    issue_type TEXT NOT NULL DEFAULT '',
    initial_severity TEXT NOT NULL DEFAULT '',
    worst_severity TEXT NOT NULL DEFAULT '',
    first_detected_at TEXT NOT NULL DEFAULT '',
    last_abnormal_at TEXT NOT NULL DEFAULT '',
    resolved_at TEXT NOT NULL DEFAULT '',
    first_ap_rx_dbm TEXT NOT NULL DEFAULT '',
    worst_ap_rx_dbm TEXT NOT NULL DEFAULT '',
    recovered_ap_rx_dbm TEXT NOT NULL DEFAULT '',
    first_switch_rx_dbm TEXT NOT NULL DEFAULT '',
    worst_switch_rx_dbm TEXT NOT NULL DEFAULT '',
    recovered_switch_rx_dbm TEXT NOT NULL DEFAULT '',
    first_rx_dbm TEXT NOT NULL DEFAULT '',
    worst_rx_dbm TEXT NOT NULL DEFAULT '',
    recovered_rx_dbm TEXT NOT NULL DEFAULT '',
    event_status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (event_status IN ('OPEN', 'RESOLVED')),
    treatment_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (treatment_status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'IGNORED')),
    remark TEXT NOT NULL DEFAULT '',
    source_revision_first TEXT NOT NULL DEFAULT '',
    source_revision_last TEXT NOT NULL DEFAULT '',
    backfill_key TEXT NOT NULL DEFAULT '',
    backfill_source TEXT NOT NULL DEFAULT '',
    evidence_quality TEXT NOT NULL DEFAULT 'RUNTIME',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    last_observation_fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
```

实际 migration 已按项目已有 additive migration convention 处理 schema version，
并为状态字段增加 CHECK/enum 约束。另有 `backfill_key` 非空唯一索引作为回填幂等
键，以及 `(site_id, ap_identity)` 的非空 `OPEN` partial unique index，数据库层阻止
同一 AP 同时存在多个 OPEN event。字段名可按最终 domain model 微调，但不得重新
加入 `UNIQUE(site_id, ap_identity)`；同一 AP 必须能有 event 1、event 2、event 3。

事件唯一由 `event_uuid` / `id` 管理。`site_id + ap_identity + first_detected_at`
不是唯一约束，只是查询索引和诊断定位条件。

### 5.2 索引

已建立：

```text
INDEX(site_id, ap_identity, first_detected_at)
INDEX(site_id, event_status)
INDEX(site_id, treatment_status)
INDEX(ap_uuid)
INDEX(serial_number)
INDEX(switch_device_id, switch_interface)
UNIQUE(site_id, backfill_key) WHERE trim(backfill_key) <> ''
UNIQUE(site_id, ap_identity) WHERE event_status = 'OPEN'
```

runtime 使用 `last_observation_fingerprint` 去重同一 snapshot；回填使用
`backfill_key` 和 evidence JSON 持久化来源。source revision 不能单独作为 event
identity：

```text
(event_uuid, source_revision, collected_at, side, observation_fingerprint)
```

不要把 `source_revision` 单独当作 event identity；同一 revision 下可能有多个侧别
观测，跨 revision 也可能仍属于同一个生命周期。

## 6. Event lifecycle

### 6.1 事件边界

对每个精确 `site_id + ap_identity`，按来源 revision 和采集时间处理有效观测：

| 输入变化 | 事件动作 |
| --- | --- |
| confirmed NORMAL/RECOVERED -> abnormal | 没有 OPEN event 时创建新的 OPEN event |
| abnormal -> abnormal | 更新同一 OPEN event，不创建新行 |
| AP abnormal -> AP+SWITCH abnormal | 更新同一 event，`worst_abnormal_side=BOTH` |
| warning -> alarm | 更新同一 event，提升 `worst_severity` |
| abnormal -> confirmed NORMAL/RECOVERED | 关闭同一 event，写 `event_status=RESOLVED` 和 `resolved_at` |
| 已 RESOLVED 后再次 abnormal | 创建新的 event；这就是 recurrence |

同一生命周期内 AP 侧和交换机侧不是两条默认 event。两侧只要没有中间的
confirmed NORMAL/RECOVERED，就合并到同一个 event；AP 已恢复后再出现独立交换机
异常，才开始新 event。优先用明确健康状态边界，不使用任意固定分钟数作为事件
切分；对于长期缺采样的策略必须单独命名、记录并测试，不能隐式切断 OPEN event。

### 6.2 状态和无数据

`event_status` 与 `treatment_status` 是两个维度：

- `event_status`：`OPEN` / `RESOLVED`，表达设备异常生命周期；
- `treatment_status`：`PENDING` / `IN_PROGRESS` / `COMPLETED` / `IGNORED`，表达
  人工处理流程，可根据当前正式状态集合兼容。

下面的输入不能创建 event，也不能关闭既有 event：

```text
collection_failed
not_collected
unknown
no_module
EMPTY_CONFIGURED_PORT
```

若上一有效状态为 abnormal，本轮 `collection_failed` 只保持 OPEN，不更新异常
RX 和 severity；`not_collected` 不产生 event。设备连接失败不会被当作光衰恢复，
也不会被当作新的光衰异常。

`stale` 只表示 freshness，不创建 event、不 resolve event。只有新的有效成功采集
且明确业务状态恢复正常时才关闭事件。

### 6.3 同 AP 多事件

一个 AP 的典型序列应落为：

```text
normal -> alarm -> normal       event-1 RESOLVED
normal -> warning -> normal     event-2 RESOLVED
normal -> alarm -> normal       event-3 RESOLVED
```

同时 `ap_optical_treatment` 仍只有一行，指向最新状态，并将 recurrence summary
缓存维护为已解决事件后再次打开的次数。事件表才是历史 source of truth。

## 7. 幂等和 summary projection

### 7.1 幂等规则

对同一 `site_id + ap_identity`：

1. 先用明确 source revision/observation fingerprint 去重同一 snapshot；
2. 存在 OPEN event 且当前是有效异常，更新 OPEN event；
3. 不存在 OPEN event 且当前是有效异常，创建新的 event_uuid；
4. 有 OPEN event 且当前是明确正常，关闭该 event；
5. 没有 OPEN event 且当前是正常/失败/stale，不创建 event。

重复处理相同 snapshot 不能重复创建 event，也不能重复累计 recurrence。revision
用于跳过无变化更新，但不单独决定 event 边界。并发写入时必须由现有 site 写任务
锁/事务和唯一 event UUID 共同保护；冲突应返回结构化 conflict，不选择任意行。

### 7.2 summary 投影

事件生命周期成功更新后，同一事务内刷新 `ap_optical_treatment` 的当前投影：

- summary 仍 `UNIQUE(site_id, ap_identity)`；
- `current_*`、`current_status`、`current_abnormal_side` 取当前有效观测；
- `first_*` / `last_*` 取当前 summary 规定的累计摘要语义；
- `recurrence_count` 保留为查询缓存，优先由事件表的已解决事件和再次打开事件
  派生或由同一生命周期事务同步维护；
- 不允许仅凭 summary 反向生成不存在的历史 event。

## 8. 从现有 55 条 summary 回填

回填工具为 `scripts/backfill_ap_optical_treatment_events.py`，默认 dry-run，
只接受 Development 数据库和已审计的 persisted evidence JSON。它先把 55 条
summary 变成当前状态 event，再按精确 identity、时间和 evidence provenance 处理
42 条 canonical missing 与 26 条 recurrence candidate；不会从旧 Excel 直接写入。

### 8.1 回填规则

- `current_status=ABNORMAL` 且 `first_detected_at` 有可靠来源：生成 OPEN event；
  缺少身份、时间或发生证据时输出 unresolved/conflict；
- `RESOLVED` 且 `first_detected_at` 与 `first_resolved_at/last_resolved_at` 可确认：
  生成 RESOLVED event；部分 evidence 可以确认已经结束但不能精确定位恢复时刻，
  此时保持 `resolved_at` 为空并将质量标记为 PARTIAL；
- `recurrence_count > 0`：必须结合 `optical_history` 和其它按优先级排序的持久化
  evidence 拆分多个 event，不能把 count 机械复制成多行；
- `recurrence_count=0` 不证明没有复发；当前结果已经证明旧复发可能没有回放；
- 42 条 missing 只允许使用达到本实现 authority 顺序的 persisted evidence；
  `LEGACY_ONLY_EVIDENCE`、`IDENTITY_UNRESOLVED` 和 conflict 不自动 INSERT；
- 旧 Excel 只能保留为 candidate/legacy evidence，不能直接成为数据库 authority。

### 8.2 Development 执行结果

| 检查项 | 结果 |
| --- | ---: |
| `ap_optical_treatment` summary | 55 行，apply 前后保持不变 |
| `ap_optical_treatment_events` | 113 行 |
| canonical missing | 35 完整、7 部分、0 未恢复 |
| recurrence | 24 回填、2 legacy-only 跳过 |
| 合并 | 8 条 recurrence 合并到当前 summary 权威 event，16 条生成新 event |
| 第一次 dry-run | `would_create=113`, `would_update=0` |
| apply | 事务成功 |
| 第二次 dry-run | `would_create=0`, `would_update=0` |
| conflicts / unresolved | 0 / 0 |

部分 event 的证据、分类、来源 revision 和回填键写入 `evidence_json`、
`evidence_quality`、`backfill_source`、`backfill_key`。未知侧别不猜测，RX 只写
通用字段；能确认事件已结束但恢复边界不精确时使用 `RESOLVED + resolved_at=''`。

## 9. Dry-run 约束

迁移工具默认为 dry-run，例如：

```text
python scripts/... --site hzl10
```

默认只输出：

```text
would_create
would_update
unresolved
conflicts
```

只有显式 `--apply` 才允许写入；`--apply` 仍需 site 写任务锁、事务、审计日志、
candidate 数量核对和失败可恢复策略。工具不得默认修改数据库，也不得从旧 Excel
直接 INSERT。

## 10. 导出边界

“AP 光衰处理记录”当前从 `ap_optical_treatment_events` 导出，一条历史事件一行。
如仍需要当前视图，另提供“AP 光衰当前处理状态”导出，来源为
`ap_optical_treatment`。不能把一个 AP 的当前 summary 当作完整事件历史，也不能
在导出层根据当前值重新猜测已结束事件。

Development 导出验收通过：事件明细 113 行，单个 AP 可导出多行历史事件，输出含
首次/最差/恢复 RX、event status 和处理状态；事件 status 同步控制记录行样式。

## 11. 测试和验收覆盖

已覆盖以下用例：

1. `normal -> alarm`：创建一个 OPEN event；
2. `alarm -> warning`：更新同一 event，不新增；
3. `AP -> BOTH`：更新同一 event，侧别升级为 BOTH；
4. `alarm -> normal`：关闭同一 event，写恢复时间和恢复 RX；
5. `resolved -> alarm`：创建新的 event，recurrence +1；
6. `collection_failed`：不新增、不 resolve、不更新异常 RX；
7. `not_collected`：不产生 event；
8. 同一 snapshot 重复处理：不产生重复 event、不重复 recurrence；
9. 同一 AP 三次异常/恢复：得到 3 行 event；
10. 同一 AP 的 summary：仍只有 1 行。

同时覆盖身份精确绑定、AP/SWITCH 侧别切换、warning/alarm severity 演进、stale、
采集失败/未采集、source fingerprint 重放、schema quick_check、回填 dry-run/apply
和第二次 dry-run 幂等。

## 12. 当前决策清单

```text
CURRENT_TREATMENT_SUMMARY_MODEL=ONE_ROW_PER_AP_IDENTITY
EVENT_HISTORY_REQUIRED=YES
EVENT_TABLE=ap_optical_treatment_events
CURRENT_SUMMARY_TABLE=ap_optical_treatment
SUMMARY_REPLACED=NO
EVENT_LIFECYCLE=PASS
FAILURE_CREATES_EVENT=NO
FAILURE_RESOLVES_EVENT=NO
STALE_CREATES_EVENT=NO
REPEATED_SNAPSHOT_DUPLICATE_EVENT=NO
EVENT_IDEMPOTENCY=PASS
LEGACY_EXCEL_AS_DATABASE_AUTHORITY=NO
BACKFILL_IMPLEMENTED=YES
SCHEMA_MIGRATION_EXECUTED=YES
EXPORT_AUTHORITY=EVENT_HISTORY
```

最终只推荐方案 B：**Current Summary + Event History 双层模型**。方案 A 继续扩展
one-row summary 无法同时保存同一 AP 的第一次、第二次和第三次真实异常生命周期，
也无法可靠解释当前 `recurrence_count=0` 与旧 26 条 recurrence 的差异。方案 B
保留当前查询和 UI 兼容边界，同时为未来事件处理、统计和历史导出提供明确 authority。
