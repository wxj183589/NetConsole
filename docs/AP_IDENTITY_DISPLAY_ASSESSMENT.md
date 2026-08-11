# AP Identity 观察结果只读展示方案评估

> 冻结说明：本文的字段允许列表和脱敏边界仍可作为设计证据；其中 Qt Job/Dialog/Manager 候选属于已结束的历史评估，不是活动路径。当前宿主结论见 [AP Identity Job 宿主评估（冻结历史）](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md)。

## 1. 背景

AP Identity 阶段 2～6.1 已在 AC 扩展、AC 光衰、轨旁 AP、MR/Mesh 和两个导出入口附加只读 `identity_shadow` 或 `export_identity_diagnostics`。阶段 7 已定义真实局点观测、脱敏汇总、保守阈值和运行手册，但尚未执行真实局点采样。

阶段 8 只评估维护人员或高级诊断用户将来如何查看脱敏聚合。本文不授权实现 UI、启用 feature flag、保存诊断结果、修改 workbook 或让 resolver 接管生产路径。所有展示结论均为“待真实局点观测验证”。

当前已有 Vue 全局任务中心抽屉和完整页面，但 AP Identity 摘要尚未接线。“任务详情”仍是优先候选，不能为了展示新增第二套任务持久化或在多个业务页面同时接入。

## 2. 非目标

本阶段不执行以下工作：

- 不实现 UI、报告、feature flag 或权限代码。
- 不修改 `identity_shadow`、`detail_identity_shadow`、`export_identity_diagnostics` 的生产结构或默认生成行为。
- 不新增数据库字段、诊断表、缓存、sidecar 或云端上传。
- 不修改 Repository SQL、resolver、parser、mapping/cache、光衰、轨旁或 MR/Mesh 业务规则。
- 不删除、合并、改名导出字段，不修改报告 SQL、Sheet、表头、行值、样式或返回类型。
- 不把 shadow 指标解释为生产正确性、设备健康或业务失败结论。
- 不展示或保存真实局点数据、完整 Job result、原始 warning/error、items、samples 或 evidence。
- 不进入自动修复、生产接管或 AP 统一模型替换。

## 3. 可展示与禁止展示的数据边界

### 3.1 允许列表

阶段 8.1 只能从原始结果复制下列聚合字段。来源不支持的字段必须为 `null`，不能用 `0` 冒充已计算：

```text
available
total
matched
unresolved
ambiguous
identity_changed
identity_unchanged
name_only_matches
mac_like_names
missing_ac_scope
duplicate_mac_field_records
peer_mac_equals_peer_radio_mac
peer_mac_equals_ap_mac
radio_or_bssid_only_records
interface_only_records
lldp_only_records
optical_fallback_records
missing_min_rssi_rows
missing_backup_link_rows
```

AC 光衰可额外展示 `ap_side_records`、`switch_side_records`、`offline_records`；导出 diagnostics 可额外展示 `missing_ap_mac_rows`、`missing_peer_mac_rows`、`has_mapping_source_field`、`has_peer_radio_mac_field`。这些字段仍只是数据完整性计数。

每个指标最多派生以下显示值：

- 数量。
- 在同一次、同一对象的 `total` 上计算的百分比。
- 阶段 7 定义的风险等级。
- 是否阻断未来接管；不等于阻断当前业务。
- 从固定 action code 映射的建议动作，例如“继续观测”“复核 AC 作用域”“检查输入字段”。

### 3.2 绝对禁止展示

以下字段即使已经存在于 Job result，也不得传入 ViewModel 或 UI：

```text
items
samples
evidence
warnings 原文
error 原文
traceback
old/new candidate key
old identity key
record_ref / row_ref / extension_ref / optical_ref
AP / Peer / Radio MAC 明文
BSSID / BBSSID 明文
IP 明文
设备、MR、AC、站点、区间、线路名称明文
里程和精确时间
原始日志、数据库、session、xlsx 路径
账号、密码、community、密钥或命令回显
```

阶段 8.1 默认不展示样例。后续如确需样例，必须单独立项、单独开关，只允许 campaign HMAC/token、稳定 reason code 和无业务定位能力的相对索引；不能复用生产 `samples` 或 `items`。

### 3.3 转换边界

展示层不能直接绑定原始 result 字典。必须先经过严格允许列表转换：

```text
Job / Export result metadata
  -> Diagnostics Summary ViewModel
  -> 字段允许列表、类型检查、null 语义、比例计算
  -> 风险与 action code 映射
  -> 只读 UI
```

转换遇到未知字段时丢弃。生产 result 中已知的 `items/samples/evidence/warnings/error` 容器必须无日志丢弃，因为它们当前默认存在；仅当本应符合脱敏 summary schema 的输入仍把敏感值塞入允许字段，或过滤后已无法形成安全摘要时，才记录本地稳定 code 并将状态置为 `redacted`。不得把原始值写日志，ViewModel 不持有原始 result 引用。

## 4. 当前 shadow / diagnostics 结果清单

### 4.1 AC FIT-AP 与 AP 扩展 `identity_shadow`

- 数据来源：AP 扩展行与现有 FIT-AP 资源只读候选。
- 生产接入：`fit_ap_extension_preview`、`fit_ap_extension_commit`、`ac_ap_extensions_refresh`、`ac_ap_extension_save` 的旧结果完成前后附加 `identity_shadow`；旧写入路径不依赖它。
- 默认返回：相关 Job 成功时默认附加；异常降级为 `available=false`。
- 原始字段：聚合含 `total/matched/unresolved/ambiguous/identity_unchanged/identity_changed/name_only_matches/mac_like_names/missing_ac_scope/available`，另有高敏 `warnings/items/evidence/old/new key`。
- 可展示：上述聚合计数、比例、风险和固定建议动作。
- 禁止展示：`items` 及其中 extension ref、旧/新 key、evidence、warning、MAC、名称和 AC 作用域明文。
- 建议位置：P0 维护模式的 Job 详情或统一诊断摘要；不放 AC 扩展主表。
- 粒度：单次 Job、单一 AC/局点 token 的聚合；不展示单行。
- feature flag：必须。
- 是否允许导出：阶段 8.1 不允许。

### 4.2 AC 光衰 `identity_shadow`

- 数据来源：既有光衰 rows、FIT-AP 资源和 AC 作用域；load/collect、all/single 都使用旧光衰结果。
- 生产接入：`ac_fit_ap_optical_refresh` Job result 默认附加；shadow 失败不改变光衰 finished/failed。
- 默认返回：成功结果默认附加。
- 原始字段：通用 identity 聚合，加 `ap_side_records/switch_side_records/interface_only_records/offline_records`，另有高敏 `items/evidence/warnings`。
- 可展示：安全聚合、比例、`interface_only_records` 等数据来源结构计数。
- 禁止展示：接口名、AP/交换机名称、MAC、光衰单行、阈值判定明细、old/new key 和原始 warning。
- 建议位置：P0 Job 详情；P2 光衰页面只允许一个默认隐藏的聚合入口，不改异常表格。
- 粒度：单次全量或单 AP Job 聚合；单 AP 场景也不能显示身份明文。
- feature flag：必须。
- 是否允许导出：阶段 8.1 不允许，不能进入光衰 workbook。

### 4.3 轨旁 AP `identity_shadow`

- 数据来源：旧轨旁业务 rows、FIT-AP 候选、接口、LLDP、光衰和 topology context。
- 生产接入：主 snapshot/兼容 Job 附加 `identity_shadow`；详情旧 matches 后附加 `detail_identity_shadow`。轨旁导出服务的 snapshot 内部也能生成 shadow，但现有 workbook 不消费它。
- 默认返回：聚合/详情相关结果默认附加，异常为 `available=false`。
- 原始字段：通用 identity 聚合，加 `interface_only_records/lldp_only_records/optical_fallback_records`，以及高敏 row/item、AP UUID/MAC/name、evidence、warning。
- 可展示：聚合计数、比例、风险和固定 action code。
- 禁止展示：详情 items、交换机接口、LLDP neighbor、AP/设备/站点/区间/里程、候选 key 和 warning 明文。
- 建议位置：P0 Job 详情；P2 轨旁页面只显示默认隐藏的聚合状态，不新增主表列或改变双击详情。
- 粒度：单次 snapshot 聚合；`detail_identity_shadow` 在 8.1 不展示。
- feature flag：必须。
- 是否允许导出：不允许；现有轨旁 workbook 必须保持不变。

### 4.4 MR/Mesh `identity_shadow`

- 数据来源：离线旧 mapping/cache、Online parsed DB、Vehicle mapping，以及 FIT-AP、`ap_entities`、AP 扩展候选快照。
- 生产接入：`mesh_log_import`、`online_mr_parse`、`vehicle_mr_mapping_load` 的旧 result 后默认附加。
- 默认返回：相关 Job 成功时默认附加，异常为 `available=false`。
- 原始字段：通用 identity 聚合，加 `peer_mac_equals_peer_radio_mac/peer_mac_equals_ap_mac/radio_or_bssid_only_records/duplicate_mac_field_records`，另有高敏 Peer/AP/Radio/BSSID、record ref、items/evidence/warnings。
- 可展示：聚合计数、比例、风险和固定建议动作。
- 禁止展示：任何 Peer/AP/Radio/BSSID 明文、MR 名称、文件/session、旧 mapping、items、evidence 和 warning。
- 建议位置：P0 Job 详情或统一诊断摘要；P2 MR/Mesh 页面不新增主表、图表、事件或导出列。
- 粒度：单个导入/解析/mapping load Job 聚合，不跨不同数据源直接相加。
- feature flag：必须。
- 是否允许导出：阶段 8.1 不允许。

### 4.5 Mesh 链路明细 `export_identity_diagnostics`

- 数据来源：`mesh_link_detail` Export Process 已查询并送入旧 formatter 的行。
- 生产接入：成功 finished result 的 `export_identity_diagnostics` metadata；diagnostics 不进入 workbook。
- 默认返回：导出成功时默认附加，初始化或汇总失败为 `available=false`，原导出仍成功。
- 原始字段：`total_rows`、重复 MAC、MAC-like name、Radio/BSSID-only、缺失 AP/Peer MAC、缺失 min RSSI/备链和字段存在性；另有 `samples/warnings/error/export_type`。
- 可展示：把 `total_rows` 映射为 `total`，展示安全计数、比例和字段存在性。
- 禁止展示：`samples`、record ref、warning/error 明文、源行、路径和任何 MAC/name。
- 建议位置：P0 Export Job 详情；P1 导出完成后的可选诊断摘要。
- 粒度：单次导出聚合。
- feature flag：必须，与普通导出开关分离。
- 是否允许导出：8.1 不额外导出 diagnostics；原 workbook 保持不变。

### 4.6 Online MR 兼容报告 `export_identity_diagnostics`

- 数据来源：`OnlineMrAnalysisReportExporter` 既有链路明细位置数组和原表头。
- 生产接入：`exporter.result_metadata.export_identity_diagnostics`；`export()` 仍返回原 `Path`。该兼容服务不是当前 Online MR 页面默认报告入口。
- 默认返回：调用该兼容 exporter 时默认生成 metadata；不是当前页面所有报告都具备的字段。
- 原始字段：与导出 diagnostics 相同，含高敏 `samples/warnings/error`。
- 可展示：只允许列表聚合，并明确标记来源为 `online_mr_compat_detail`。
- 禁止展示：原 rows、三个同源 MAC 列、samples、warning/error、session/SQLite/xlsx 路径。
- 建议位置：只有兼容 exporter 的维护诊断详情；不能让当前页面误显示为默认报告诊断。
- 粒度：单次兼容报告聚合。
- feature flag：必须。
- 是否允许导出：8.1 不新增 Sheet、首页摘要或独立文件。

## 5. UI 展示入口候选

| 候选入口 | 适合指标 | 必须排除 | 默认/flag | 普通用户与现场价值 | 误解与实现风险 | 回滚 |
| --- | --- | --- | --- | --- | --- | --- |
| Job Center 任务详情 | 单次 Job 的 available、total、比例、风险、固定建议 | items/samples/evidence/warning/error、业务明细 | 默认隐藏；全局和 UI flag 同时开启；维护权限 | 不影响普通用户；最适合定位某次任务 | 当前没有独立 Job Center 详情 UI，需要先明确宿主和事件生命周期；不能因此新增任务持久化 | 移除详情区消费者，Job result 不变 |
| 系统设置/诊断中心 AP Identity 页 | 多次脱敏 summary 的只读比较 | 原 result、站点/设备定位值 | 默认隐藏、internal-only | 适合高级维护；不适合普通现场操作 | 当前没有通用诊断中心；新增页面、数据来源和生命周期范围较大 | feature flag 隐藏并删除页面注册 |
| AC 管理只读摘要 | AC 扩展聚合 | AP 行、候选、MAC/name | P2、默认隐藏 | 局部排障直观 | 容易被理解为 AC/AP 健康结论，且需改业务页 | 删除局部入口 |
| 光衰页面只读摘要 | 光衰 identity 来源结构计数 | 光衰阈值/异常明细与 identity item | P2、默认隐藏 | 可解释 interface-only | 容易与光衰异常规则混淆 | 删除局部入口 |
| 轨旁 AP 页面只读摘要 | interface/LLDP/optical fallback 聚合 | 主表列、详情 shadow、站点/区间 | P2、默认隐藏 | 高级排障有限 | 容易影响用户对旧 lookup 的信任，不得改变双击行为 | 删除局部入口 |
| MR/Mesh 分析页只读摘要 | duplicate/name-only/scope 聚合 | Peer/AP/Radio/BSSID、图表事件 | P2、默认隐藏 | 可解释字段风险 | 易被误当链路质量、主备链或 RSSI 结论 | 删除局部入口 |
| 导出完成可选摘要 | 单次 export diagnostics 聚合 | samples/error/path 和 workbook 内容 | P1、默认隐藏、独立 export-summary flag | 不打开 workbook 即可看到数据完整性 | 必须区分导出成功与 diagnostics unavailable；不能改变完成终态 | 移除完成提示附加区 |

优先级结论：

1. P0 仍是 Job 详情或统一诊断宿主，仅显示单次聚合。
2. 当前没有现成 P0 宿主，阶段 8.1 不应同时改造多个业务页面来规避该缺口。
3. P1 可在未来对 Export result 提供可选摘要，但不改 workbook。
4. P2 业务页入口推迟；主表新增列明确不建议。

## 6. 报告展示入口候选

| 候选 | 结论 | 默认策略 | 主要风险 | 回滚 |
| --- | --- | --- | --- | --- |
| 独立诊断摘要 JSON | 暂不实施；只有通过阶段 7 脱敏复核后才可评估 | 关闭，不自动生成 | 文件泄漏、路径/自由文本混入、被误当正式报告 | 关闭开关并删除生成器 |
| 独立诊断摘要 XLSX | 不进入 8.1 | 关闭 | 新 workbook 契约、WPS/Excel 兼容、敏感字段和用户工作流膨胀 | 不实现 |
| 导出完成 metadata | 保留现状，作为未来 ViewModel 的优先输入 | metadata 可生成但不默认展示 | UI 直接透传 samples/error | 取消 UI 消费，原导出不变 |
| 原报告末尾增加“诊断摘要”Sheet | 不建议 | 禁止 | 改变 Sheet 集、golden tests 和用户已有自动化 | 不实现 |
| 报告首页增加风险摘要 | 不建议 | 禁止 | 把诊断风险误当业务结论，改变首页语义 | 不实现 |

阶段 8.1 推荐不改 workbook、不新增默认 sidecar，只消费现有 Job/Export result metadata 的聚合字段。未来如需报告展示，必须单独开关并生成独立只读摘要，原业务 Sheet、表头、SQL 和返回类型仍保持不变。

## 7. 脱敏聚合展示格式

ViewModel 使用统一 schema；以下数值仅为虚构格式示例，不代表真实局点：

```json
{
  "schema_version": 1,
  "source_type": "mesh_link_detail_export",
  "status": "insufficient_fields",
  "available": false,
  "total": 1000,
  "metrics": {
    "matched": null,
    "unresolved": null,
    "ambiguous": null,
    "identity_changed": null,
    "duplicate_mac_field_records": 12,
    "missing_min_rssi_rows": 1000,
    "missing_backup_link_rows": 1000
  },
  "rates": {
    "duplicate_mac_field_rate": 1.2
  },
  "risk": {
    "level": "R2",
    "blocks_future_takeover": true,
    "blocks_current_business": false
  },
  "action_codes": ["CONTINUE_OBSERVATION", "REVIEW_INPUT_FIELDS"],
  "privacy": {
    "contains_raw": false,
    "contains_samples": false,
    "contains_identifiers": false
  }
}
```

规则：

- `total=0` 与 `not_collected` 分开；前者表示执行过但没有记录。
- rate 只在同一个 summary 内用 `metric / total` 计算，`total=0` 时为 `null`。
- PIS 与信号系统、不同 AC、不同 Job 类型不能直接合并平均。
- UI 文案来自稳定 status/action code，不使用原始 warning/error 自由文本。
- `blocks_future_takeover` 只约束未来接管；当前 Job、导出和业务状态始终由旧路径决定。

## 8. Feature flag 与全局禁用策略

本阶段只定义逻辑开关，不写入代码。建议配置名：

```text
ap_identity_diagnostics_enabled = false
ap_identity_diagnostics_ui_enabled = false
ap_identity_diagnostics_export_summary_enabled = false
ap_identity_diagnostics_samples_enabled = false
```

若阶段 8.1 接入现有集中式 feature registry，实际 feature id 应遵守仓库的点分层级命名，并映射到上述策略；所有项必须 `default_visible=false`、`default_enabled=false`、`default_client_package=false`、`internal_only=true`。

策略：

1. `ap_identity_diagnostics_enabled` 是展示消费的全局 kill switch；关闭后所有 UI/报告摘要立即不可见，但不改变现有 shadow/diagnostics 生成和业务结果。
2. UI 和 export summary 必须同时依赖全局开关与各自子开关。
3. `samples_enabled` 在整个 8.1 固定为 false；不能通过普通 feature 页面开启。
4. 权限不足、配置缺失、真实局点观测未达准入条件时，即使开关值为 true 也不展示。
5. 展示异常只改变诊断区域状态，不改变 Job/Export finished、failed、cancelled。
6. 禁用时不订阅额外异步任务，不缓存 result，不写数据库，不生成文件。
7. 全局 kill switch 的回滚不停止生产任务，不删除业务数据，也不改变旧页面。

建议判定：

```text
display_allowed =
  global_enabled
  and surface_enabled
  and maintenance_permission
  and observation_gate_passed
  and summary_schema_supported
```

任一条件不满足时显示宿主自身的稳定空状态或完全隐藏入口，不回退为原始 JSON。

## 9. 不可用状态和错误展示

| 状态 | 含义 | 用户可见文案 | 是否业务失败 | 操作 | 是否可忽略 |
| --- | --- | --- | --- | --- | --- |
| `not_collected` | 当前任务/来源没有诊断 metadata | 尚未采集诊断摘要 | 否 | 在批准的观测流程中重跑 | 普通业务可忽略 |
| `disabled` | 全局或 surface flag 关闭 | AP Identity 诊断展示未启用 | 否 | 维护人员按审批开启 | 可忽略 |
| `unavailable` | 原结果 `available=false` | 诊断不可用，原业务结果未受影响 | 否 | 检查稳定 code、补采样 | 业务可忽略，评估不可忽略 |
| `insufficient_fields` | 输入没有足够安全字段或字段存在性不足 | 诊断字段不足，无法形成结论 | 否 | 检查输入契约，不修改业务 SQL 补字段 | 业务可忽略 |
| `failed` | ViewModel 转换或展示自身失败 | 诊断摘要加载失败，原任务状态不变 | 否 | 关闭展示并记录无敏感信息的稳定 code | 业务可忽略 |
| `redacted` | 脱敏 summary 契约被敏感值污染，或过滤后无法形成安全摘要 | 诊断摘要已隐藏敏感内容 | 否 | 丢弃原始引用，复核脱敏边界 | 不应继续展示详情 |
| `not_supported` | 来源类型或 schema version 尚未映射 | 当前任务类型暂不支持诊断摘要 | 否 | 等待受控适配 | 可忽略 |

必须明确：

- `identity_shadow unavailable` 不代表 AP、光衰、轨旁或 MR/Mesh 业务失败。
- `export_identity_diagnostics unavailable` 不代表导出失败。
- `unresolved` 是 resolver 未得到唯一候选的计数，不等于现有业务错误。
- `ambiguous` 是风险提示，不允许自动选第一条，也不是自动业务失败。
- `identity_changed` 只阻断未来接管评估，不能覆盖旧生产结果。

## 10. 权限与安全边界

- 普通用户和客户构建默认没有诊断入口。
- 仅维护/开发模式、internal-only feature 和显式授权同时满足时，才允许查看聚合。
- 不显示明文 MAC/IP/设备/站点/区间/线路/路径，不显示 items/samples/evidence/warning/error。
- 诊断结果不上传云端、不发送网络请求、不写入遥测。
- 不保存到仓库、数据库、常规日志、剪贴板历史或默认报告。
- 不进入普通导出；未来独立摘要也必须显式开启、输出到受控目录并再次脱敏。
- 不提供“查看原始 JSON”“展开 evidence”“复制完整 result”等逃逸入口。
- UI 关闭、页面切换和 kill switch 禁用时不得留下 timer、订阅或 result 强引用。
- 所有安全拒绝只记录稳定 code 和来源类型，不记录原始值。

## 11. 阶段 8.1 只读展示最小实现设计

### 11.1 前置条件

可见展示必须等待阶段 7 至少完成试运行样本、脱敏复核和 summary schema 验证。当前尚无真实局点采样，因此阶段 8.1 可以评审/实现纯允许列表 ViewModel 与默认关闭开关，但不能默认启用、不能交付现场展示结论。

此外必须先确定单一宿主：

- 若新增真正的 Job Center 任务详情，应单独评估全局任务事件和生命周期，不为 AP Identity 顺带新增任务数据库。
- 若选择诊断中心，应单独注册 internal-only 页面，并定义只消费当前内存 metadata 的方式。
- 在宿主未确定前，不允许同时改 AC、光衰、轨旁、MR/Mesh 多个业务页面。

### 11.2 最小范围

1. 新增纯 Python `DiagnosticsSummaryViewModel`，只接受普通 mapping，复制允许列表字段并立即丢弃原始引用。
2. 只消费 Job/Export result metadata，不读 Repository、数据库、raw log、xlsx 或网络。
3. 新增全局和 UI 默认关闭、internal-only feature；samples feature 保持不可启用。
4. 只在一个经批准的 P0 宿主显示只读聚合，不接业务主表。
5. 不改 workbook、导出字段、报告 SQL、resolver、parser、Job result metadata 或任务终态。
6. 不持久化、不上传、不自动刷新、不启动新后台任务。

建议文件范围，具体路径在实现前以当前宿主为准：

```text
src/netconsole/services/ap_identity/diagnostics_summary.py
src/netconsole/core/feature_registry.py
src/netconsole/models/diagnostics_summary.py
apps/desktop_renderer/src/components/<approved-ap-identity-summary>.vue  # 仅在后续明确批准后
tests/test_ap_identity_diagnostics_summary.py
tests/test_ap_identity_diagnostics_display.py
```

只有确定现有 Job 详情宿主后，才允许对该单一宿主文件做最小接线；不得用阶段 8.1 顺带创建完整 Job Center、修改所有业务页或新增诊断持久化。

### 11.3 主要风险

- 原始 result 直接绑定 UI，导致 items/samples/evidence 泄漏。
- `available=false` 或 `unresolved` 被映射为业务失败。
- 为了显示缺失指标而扩大 SQL、parser 或 formatter。
- 新增页面后权限/feature flag 默认值错误，普通用户可见。
- 保存最近结果导致跨局点、跨任务或敏感数据残留。
- 当前没有统一 Job 详情，接线范围失控。

### 11.4 回滚

- 关闭全局 kill switch，入口和消费者立即隐藏。
- 删除 ViewModel、只读 dialog 和单一宿主接线。
- 不需要数据库迁移、数据回填或 workbook 恢复。
- 原 Job/Export result、旧页面和业务路径始终是回滚基线。

## 12. 测试策略

阶段 8.1 若实施，至少覆盖：

1. 所有 feature flag 默认关闭，客户构建和普通权限不可见。
2. 全局 kill switch 覆盖 UI/export 子开关。
3. 只复制允许列表；未知字段、items、samples、evidence、warning/error、MAC/IP/name/path 全部不进入 ViewModel。
4. 中英文状态和 action code 文案完整，不拼接原始 warning。
5. `null`、`0`、缺失字段、`total=0`、unsupported schema 语义不混淆。
6. `not_collected/disabled/unavailable/insufficient_fields/failed/redacted/not_supported` 状态完整。
7. diagnostics unavailable 不改变原 Job/Export 状态和用户成功提示。
8. `unresolved/ambiguous/identity_changed` 只影响风险提示，不改生产结果。
9. ViewModel 不修改输入 mapping，不保留原始 result 引用。
10. 禁用或权限不足时不构建 dialog、不订阅异步事件。
11. UI 关闭、切换和销毁后无 timer、订阅或跨局点结果残留。
12. 原 workbook Sheet、表头、关键行、样式、筛选、冻结和返回类型 golden 完全不变。
13. Job result metadata 原结构和值完全不变，展示只读消费副本。
14. 静态检查 UI 不导入 Repository/parser，不写数据库/文件，不访问网络。

## 13. 回滚策略

阶段 8 只有文档，删除本轮文档增量即可回滚。阶段 8.1 若实施，优先通过全局 kill switch 禁用，再删除单一展示宿主和 ViewModel；不回退或重写 shadow/diagnostics 生产代码，不修改业务数据库和导出文件。

任何展示故障都必须降级为“诊断不可用，原业务结果未受影响”。禁止在回滚时删除原始业务数据、改变 Job 终态或重新运行设备命令。

## 14. 阶段 9 之后的禁止事项

阶段编号推进不自动解除以下限制：

- 未经真实局点观测、独立评审和用户明确批准，不得让 resolver 接管生产结果。
- 不得根据重复率自动删除、合并、改名 Peer/AP/Radio/BSSID 字段。
- 不得把展示阈值变成应用内强制业务规则。
- 不得自动修复 AP identity、候选、作用域、mapping/cache 或导出数据。
- 不得把诊断写入主数据库、默认 workbook、普通日志或云端。
- 不得默认开放 samples/items/evidence 或明文身份字段。
- 不得为补齐展示指标修改 parser、Repository SQL、报告 SQL、业务页面字段或采集命令。

阶段 8 的结论是：展示方案可继续细化，但可见阶段 8.1 必须以真实局点观测达标、单一宿主明确、默认关闭和严格允许列表为准入条件。

## 15. 阶段 8.1 当前实现

阶段 8.1 的历史 ViewModel 已随 Qt UI 删除；允许列表结构现由 `src/netconsole/models/diagnostics_summary.py` 承担，导出适配位于 `src/netconsole/services/export_identity_diagnostics.py`。实现边界如下：

- 全局开关 `ap_identity_diagnostics_enabled` 与 UI 开关 `ap_identity_diagnostics_ui_enabled` 必须同时显式为真；缺失或关闭时状态固定为 `disabled`，默认不展示。
- `ap_identity_diagnostics_samples_enabled` 仅保留后续策略名称；当前即使显式开启也不读取或暴露 `items/samples/evidence/warnings/error`。
- ViewModel 只复制本文允许的聚合计数，并归一化有限的 export 字段别名；未知字段与 MAC、IP、名称、候选、路径等定位信息不进入模型。
- 风险等级仅生成只读建议和 `blocks_takeover` 提示，不修改输入 mapping，不改变 Job/Export 终态，也不触发 resolver、Repository、文件或网络操作。
- 异常、字段不足、schema 不支持和诊断不可用均降级为安全状态，不向调用方抛出诊断异常。

当前已有全局任务中心，但 AP Identity 摘要仍未接线，也未新增具名页面或第二套任务持久化。可见 UI 接线继续受真实局点准入、单宿主批准和默认关闭约束。

## 16. 阶段 8.2 Job 详情宿主评审结论

阶段 8.2 已完成当前 Job/Export UI 宿主、七类任务结果流和六类候选入口的只读评审，详见 [AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md)。

当前全局任务中心已经提供详情启动点，但 AP Identity owner capability 与安全摘要接线尚未批准，因此阶段 8.3 可见 UI 实现状态仍为 `hold`；不得改多个业务页面或保存完整 result 绕过该缺口。

## 17. 2026-07-11 同步复核

当前代码仍要求 `ap_identity_diagnostics_enabled` 与 `ap_identity_diagnostics_ui_enabled` 同时显式为 true；缺失按 false。`ap_identity_diagnostics_samples_enabled` 不授权 ViewModel 暴露 samples。允许来源键仍为 `identity_shadow`、`detail_identity_shadow`、`export_identity_diagnostics`，原始 items/samples/evidence/warnings/error/traceback、身份明文和路径继续被拒绝。

风险排序仍为：`identity_changed > 0` 为 critical；ambiguous 或 duplicate 为 high；unresolved、missing scope、name-only 为 medium；其余 low。critical/high/medium 只提供 `blocks_takeover` 的保守建议，不改变原 Job/Export 终态或业务成功提示。由于统一宿主仍不存在，本评估结论不升级为可见产品能力。
