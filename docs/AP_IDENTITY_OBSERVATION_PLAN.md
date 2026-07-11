# AP Identity 真实局点只读观测方案

## 1. 背景

AP identity 阶段 2～6.1 已在 AC 扩展信息、AC 光衰、轨旁 AP、MR/Mesh 和两个导出入口接入只读 shadow/diagnostics。这些附加结果用于比较旧逻辑、统一 resolver 和导出字段完整性，不接管生产匹配，也不改变页面、数据库、workbook、报告 SQL 或业务结论。

阶段 7 只定义真实局点观测方法、脱敏汇总格式、保守准入阈值和运行手册。本文不是生产强制规则，不授权删除字段、修改 resolver 优先级或自动修复数据。

## 2. 观测目标

真实局点观测需要回答：

1. 各只读接入点是否稳定返回 `available=true`。
2. 旧逻辑与新 resolver 的 identity 是否一致，歧义和未解析集中在哪些作用域。
3. Peer、AP、Radio、BSSID 等不同语义字段出现相同值的比例，而不是据此推断字段可删除。
4. AC scope、最低 RSSI、备链上下文等诊断输入是否完整。
5. 脱敏汇总能否在不保存 raw log、数据库、xlsx 或现场明文的情况下复现判断。
6. 后续是否仅允许进入只读展示评估；任何受控修复或生产接管仍需单独立项和批准。

## 3. 已接入的只读观测点

| 观测对象 | 数据来源与触发方式 | 附加结果 | 数据库/workbook | 页面影响 | 安全采样与敏感字段 |
| --- | --- | --- | --- | --- | --- |
| AC FIT-AP 与 AP 扩展 | 站点 FIT-AP 候选 + 扩展行；`fit_ap_extension_preview/commit`、`ac_ap_extensions_refresh`、`ac_ap_extension_save` | `identity_shadow`；含 matched/unresolved/ambiguous、old/new key、evidence、items | shadow 自身不写库、不进 workbook；preview 不写库，commit/save/refresh 的旧业务是否写库保持原语义 | 页面当前不消费 shadow | 优先采 preview；commit/save 只能在本来就获批的业务操作中观察。items 中的 AP MAC、名称、AC UUID、candidate key、evidence 必须丢弃或脱敏 |
| AC 光衰 | 既有 FIT-AP 资源与光衰结果；`ac_fit_ap_optical_refresh` 的 load/collect、all/single | `identity_shadow`；另含 AP/交换机侧、离线、interface-only 计数 | shadow 不写库、不进 workbook；load 读取现有快照，collect 仍按旧流程采集并写历史/结果 | 页面不消费 shadow，光衰显示仍由旧结果决定 | 首选 load；collect 只在批准的测试窗口执行。AP/接口、设备名、站点和 MAC 需要脱敏 |
| 轨旁 AP | 旧轨旁聚合 rows、FIT-AP 候选、LLDP/光衰/topology；`ac_trackside_business_refresh`，详情为既有 detail lookup | 聚合 `identity_shadow`，详情 `detail_identity_shadow`；含 interface/LLDP/optical fallback | shadow 不写库、不进 workbook；底层刷新继续使用旧数据路径 | 页面不消费 shadow，不改变行、双击和详情选择 | 可采聚合结果；详情只做代表性抽样。接口、LLDP neighbor、AP/设备/站点/区间/里程均敏感 |
| MR/Mesh | 离线旧 mapping/cache、Online parsed DB、Vehicle mapping + FIT-AP/AP 实体候选；`mesh_log_import`、`online_mr_parse`、`vehicle_mr_mapping_load` | `identity_shadow`；含 Peer/AP/Radio 重复、Radio/BSSID-only、name-only | shadow 不写库；离线导入和 Online parse 的旧流程会写各自 raw/parsed 输出，mapping load 只读 | 页面不消费 shadow，ACTIVE/STANDBY、短链、乒乓等仍由旧逻辑决定 | 必须使用日志/会话副本；不保存 items。Peer/AP/Radio/BSSID、MR 名称、源路径和时间均需脱敏 |
| Mesh 链路明细导出 | `ExportJob(job_type="mesh_link_detail")` 已查询的 link rows | `finished.result.export_identity_diagnostics` | diagnostics 不写库、不进入 workbook；原导出仍生成 xlsx | 页面只处理原完成状态，不展示 diagnostics | 可在测试导出中采聚合字段；不得保存 xlsx、源文件名或 samples 明文 |
| Online MR 兼容详细报告 | `OnlineMrAnalysisReportExporter.export()` 的既有详细 rows；该服务不是当前页面默认报告入口 | `exporter.result_metadata.export_identity_diagnostics` | diagnostics 不写库、不进入 workbook；原 exporter 仍写 xlsx 并返回 `Path` | 当前页面不调用、不展示 | 仅测试/开发环境运行；删除临时 xlsx。Peer/AP/Peer Radio/BSSID 和会话路径必须脱敏 |

任何表中“shadow 不写库”只描述附加诊断本身，不代表触发它的旧业务流程没有正常写入。观测不得为了获得指标额外执行 commit、save、配置命令、SNMP SET 或其他危险动作。

## 4. 真实局点运行步骤

### 4.1 前置条件

1. 使用包含阶段 6.1 检查点的受控构建，记录 commit、应用版本和观测人员。
2. 选择一个已授权局点，标记为 PIS 或信号系统；信号系统的红/蓝网分开记录，PIS 不强制套用红/蓝网字段。
3. 优先复制站点数据库、MR 会话和必要输入到隔离测试环境。主应用数据库、raw log 和导出目录先备份，并验证恢复路径。
4. 观测输出目录必须位于仓库外、受访问控制的位置，例如 `<observation-output>/<campaign-id>/`；目录名不得含客户、线路或站点真名。
5. 生成本次 campaign 专用 HMAC 密钥并保存在密码管理器中，密钥不得写入仓库、summary 或日志。
6. 当前 UI 不展示这些附加字段。只能从受控测试 harness、调试器中的 finished result 或 exporter `result_metadata` 提取聚合字段；不得把完整 result JSON 当作观测工件保存。

### 4.2 推荐执行顺序

| 步骤 | 操作 | 必选性 | 安全说明 |
| --- | --- | --- | --- |
| 1 | 记录局点 token、系统类型、AC 数量、采样窗口和基线 commit | 必选 | 不记录真实名称/IP |
| 2 | 备份数据库、会话目录和导出目录，并完成一次恢复检查 | 必选 | 备份留在受控环境，不进入仓库 |
| 3 | 使用现有 FIT-AP 快照；确需刷新时执行正常 AC FIT-AP 只读采集 | 条件必选 | 不为观测执行配置类命令；保留原始 H3C 回显但不复制进观测工件 |
| 4 | 执行 AP 扩展 preview，采集 `identity_shadow` 聚合 | 必选 | commit 不是观测要求；只有业务本来批准时才允许继续 commit |
| 5 | 执行光衰 load；确需新鲜数据时在测试窗口执行 collect | 必选 | load 优先；collect 的正常历史写入与观测无关 |
| 6 | 执行轨旁 AP 业务刷新，采聚合 shadow；详情选少量代表行 | 必选（有轨旁数据时） | 不改变 lookup、双击定位或拓扑结果 |
| 7 | 将一个离线 MR/Mesh 日志副本导入测试局点 | 必选（有 MR/Mesh 时） | 导入会写测试副本的 raw/parsed 目录；原日志不进入 summary |
| 8 | 对一个已复制的 Online MR 会话执行 parse | 必选（有 Online MR 时） | 不启动新的长连接采集，不改 parser 规则 |
| 9 | 执行 Vehicle MR mapping load | 必选（有 Vehicle MR 时） | 只读 load；不为观测保存或导入 mapping |
| 10 | 导出 Mesh 链路明细，提取 finished result 中的 diagnostics | 必选（有离线 Mesh 时） | xlsx 输出到临时受控目录，提取后删除 |
| 11 | 运行 Online MR 兼容详细 exporter 并读取 `result_metadata` | 可选，且仅测试/开发环境 | 当前页面不调用；临时 xlsx 提取后删除 |
| 12 | 只提取聚合指标，统一字段名并计算 rate | 必选 | `items`、`samples`、evidence 和 warning 明文默认全部丢弃 |
| 13 | 执行脱敏复核和双人检查，生成 `summary.redacted.json` | 必选 | 任何敏感值命中即作废并重新生成 |
| 14 | 记录准入判断，删除临时完整 result、xlsx 和调试输出 | 必选 | 保留受控业务备份，不保留观测中间明文 |

不得要求现场执行 SNMP SET、固化 AP、保存配置、开启远程登入或其他配置命令。若旧业务本身需要网络采集，继续使用既有命令、权限、取消和 raw log 规则；观测不增加命令。

## 5. 指标口径

### 5.1 统一规则

- Shadow 原生 `total` 和 export diagnostics 原生 `total_rows` 统一为 `total`。
- 不同接入点没有的指标写 JSON `null`，不得用 `0` 冒充“已计算且为零”。
- `total=0` 时所有 rate 为 `null`；该次运行只能验证接入可用性，不能作为质量样本。
- `available=false` 时保留 `available`、`total` 和脱敏 warning code，其余 rate 不参与跨运行平均。
- 所有 rate 使用 `metric / total * 100%`，先按单次运行、单一观测对象计算，再汇总；不得把不同语义对象的分子分母直接相加。
- `identity_unchanged + identity_changed` 不必等于 `total`，因为 unresolved/ambiguous 或没有旧 identity 的记录可能不属于两者。

### 5.2 指标定义与初始阈值

| 指标 | 含义与来源 | 计算方式 | 初始可接受阈值 | 后续准入含义 |
| --- | --- | --- | --- | --- |
| `available` | 本次 shadow/diagnostics 是否成功；所有接入点都有 | 原生布尔值 | 必须为 `true` 才是有效质量样本 | `false` 阻断受控修复/接管；只读展示必须明确显示不可用 |
| `total` | 本次被观察记录数 | 原生 `total` 或 `total_rows` | 大于 0 才能计算 rate | 只表示样本量，不单独决定准入 |
| `matched` | 新 resolver 得到唯一候选；各 identity shadow | 原生计数 | 仅观察，不以高 matched 率单独授权接管 | 诊断提示 |
| `unresolved` | 新 resolver 无法解析；各 identity shadow | 原生计数；`unresolved_rate=unresolved/total` | `unresolved_rate <= 5%` | 大于 5% 阻断接管，继续补候选/作用域 |
| `ambiguous` | 新 resolver 有多个候选；各 identity shadow | `ambiguous/total` | `ambiguous_rate <= 1%` | 大于 1% 阻断接管，禁止静默选第一条 |
| `identity_unchanged` | 旧逻辑与新 resolver 指向同一 identity | 原生计数及 rate | 观察趋势；不能抵消 changed | 诊断提示 |
| `identity_changed` | 旧/新结果或候选不一致 | 原生计数 | 必须为 `0` | 任意一条即禁止接管/自动修复，只允许诊断 |
| `name_only_matches` | 仅依赖名称的旧或新匹配 | 原生计数；`name_only_rate=name_only_matches/total` | `<= 10%` | 大于 10% 禁止把名称作为主路径 |
| `mac_like_names` | AP/Peer 名称本身是 MAC-like | shadow 原生；export 的 `ap_name_mac_like_rows` 映射到此字段 | 允许观察，目标是可解释且不自动改名 | 诊断提示；不得自动覆盖名称 |
| `missing_ac_scope` | observation 缺少 AC 作用域 | 原生计数；`missing_ac_scope_rate=missing_ac_scope/total` | `<= 5%` | 大于 5% 禁止跨 AC 自动匹配 |
| `duplicate_mac_field_records` | 同一记录多个不同语义 MAC 字段值相同 | MR/Mesh 原生；export 使用 `duplicate_peer_radio_mac_rows` 映射 | 必须记录；字段删除准入要求为 `0` | 任何大于 0 只说明重复风险，禁止自动删列 |
| `peer_mac_equals_peer_radio_mac` | Peer observation 与 Peer Radio 值相同 | MR/Mesh 原生；export 使用带 `_rows` 的同名计数 | 只观察，不设业务错误阈值 | 大于 0 禁止据值相同折叠语义 |
| `peer_mac_equals_ap_mac` | Peer observation 与映射 AP MAC 相同 | MR/Mesh 原生；export 使用带 `_rows` 的同名计数 | 只观察，不设业务错误阈值 | 大于 0 禁止自动把 Peer 当 AP identity |
| `radio_or_bssid_only_records` | 只有 Radio/BSSID 证据，没有安全 AP identity | MR/Mesh 原生；export 的 `radio_or_bssid_only_rows` 映射 | 只观察；这些记录不得自动绑定 AP | 对相关记录阻断接管，不必阻断其他有明确证据记录 |
| `interface_only_records` | 只有交换机接口/topology 证据 | 光衰、轨旁 shadow | 原生计数 | 允许存在 | 诊断提示；接口不得变成 AP identity |
| `lldp_only_records` | 只有 LLDP peer observation | 轨旁 shadow | 原生计数 | 允许存在 | 诊断提示；不得据此创建 AP |
| `optical_fallback_records` | 旧轨旁逻辑使用光衰 fallback | 轨旁 shadow | 原生计数 | 与同局点基线一致 | 增长需人工复核，但不修改光衰规则 |
| `missing_min_rssi_rows` | formatter 输入缺少最低 RSSI 上下文 | export diagnostics | 原生计数，另记录相对基线 delta | 不得高于同入口、同筛选基线 | 增加时禁止修改 RSSI 相关导出 |
| `missing_backup_link_rows` | formatter 输入缺少备链上下文 | export diagnostics | 原生计数，另记录相对基线 delta | 不得高于同入口、同筛选基线 | 增加时禁止修改备链相关逻辑 |

以上阈值是阶段 7 的保守观察门槛，不是应用内强制规则。PIS 与信号系统分别汇总：PIS 不因缺少红/蓝网字段直接判失败；信号系统按红/蓝网、AC 和线路作用域分桶，不能跨域平均掩盖歧义。

## 6. 脱敏规则

### 6.1 强制规则

1. AP MAC、Peer MAC、Radio MAC、BSSID、BBSSID 优先使用 campaign 专用密钥执行 HMAC-SHA-256，输出 `mac#` 加前 16 个十六进制字符。密钥不进入工件。仅在隔离现场副本中允许保留后 4 位，准备提交或共享时必须改用 HMAC。
2. IPv4 只允许保留批准的网段粒度或 HMAC；IPv6 最多保留 `/64` 或 HMAC。默认汇总格式不包含 IP。
3. 设备、站点、区间、线路、MR、AC 名称使用独立 token，如 `Device-AC-001`、`Site-001`、`Section-003`、`Line-X`。token 映射表单独加密保管，不进入 summary。
4. 原始日志路径、数据库路径、session path 和导出路径不得包含客户/线路真名；汇总只保留对象类型和不可逆 source fingerprint。
5. raw log、SQLite、xlsx、完整 Job JSON、完整 finished result、截图和 token 映射表不得提交仓库。
6. `identity_shadow.items`、evidence、candidate key、old key 默认不保存。warnings 只保存稳定 code 和数量，不保存原始 message。
7. diagnostics samples 最多 20 条；正式脱敏 summary 默认 `samples_included=false`。确需样例时只保留 `row_index`、脱敏 `record_ref` 和 reason code。
8. warning、error、traceback 中不得出现账号、密码、community、SNMPv3 密钥、私钥、隧道地址或命令完整回显。
9. 时间默认降到日期或小时桶；若精确时间可关联现场事件，应改为相对时间或 HMAC。
10. 脱敏后由第二人检查 MAC/IP/路径/客户名正则和自由文本，发现任何命中即作废工件。

### 6.2 脱敏示例

```json
{
  "ap_mac": "mac#8f2a91c4c9e1b307",
  "peer_mac_suffix": "ee:ff",
  "site": "Site-001",
  "section": "Section-003",
  "line": "Line-X",
  "device": "Device-AC-001"
}
```

示例值是虚构格式，不代表真实局点。可提交/共享的标准工件应使用 `ap_mac` 的 HMAC 形式，不建议保留 suffix。

## 7. 采样范围

### 7.1 试运行样本

- 选择 1 个授权局点，至少覆盖 1 台 AC、AP 扩展 preview、光衰 load 和对应轨旁聚合；存在 MR/Mesh 时再覆盖 1 个离线日志、1 个 Online 会话和 1 次 Vehicle mapping load。
- 每个适用观测对象至少执行 3 次，其中至少 2 个不同时间窗口；相同输入的重复运行用于验证可复现性，不作为 3 份独立业务样本。
- 小型局点采全量；大局点按 AC、站点/区间、在线/离线和数据来源分层采样，不按“只挑正常记录”抽样。
- Mesh/Online detail 建议每个入口至少 1,000 行；不足时全量并标记 `sample_limited=true`。

### 7.2 进入只读展示评估前的证据充分性

- 至少 2 个代表性局点或 1 个局点连续 3 个工作日，且六类对象中所有适用对象都有有效样本。
- AC/扩展、光衰、轨旁每类累计至少 100 条 identity observation；实际规模不足 100 时使用全量并显式标记小样本。
- MR/Mesh 至少 3 个独立日志/会话；导出 diagnostics 每个适用入口累计至少 3,000 行。
- PIS 与信号系统不能合并成一个合格率。若只覆盖一种系统，结论只适用于该系统。
- 任何阈值达标都不授权生产 resolver 接管，只决定是否有资格评估“如何只读展示”。

## 8. 准入阈值与决策门

### 8.1 只读展示评估准入

允许进入阶段 8 的必要条件：

1. 汇总格式通过脱敏复核，`raw_included=false`、`workbook_included=false`、`samples_included=false`。
2. 所有适用对象均能区分 `available=false`、`total=0` 和真实零计数。
3. 指标采集不改变旧 result、页面、数据库、workbook 或任务终态。
4. 至少完成试运行样本；证据不足时可进入 UI/报告展示方案评估，但只能标注“数据不足”，不能设计接管或自动修复。
5. 展示方案必须默认关闭、只读、可整体禁用，并使用脱敏聚合，不展示 items/evidence/raw warning。

### 8.2 受控修复或生产接管准入

阶段 7 不批准任何受控修复或生产接管。未来如单独立项，至少同时满足：

- `identity_changed == 0`。
- `ambiguous_rate <= 1%`、`unresolved_rate <= 5%`、`name_only_rate <= 10%`、`missing_ac_scope_rate <= 5%`。
- 任何 `duplicate_mac_field_records > 0` 都不能成为自动删除字段的依据。
- `missing_min_rssi_rows` 和 `missing_backup_link_rows` 相对同筛选基线不增加。
- Radio/BSSID-only、interface-only、LLDP-only 和 optical fallback 记录继续使用旧业务路径，不自动补 AP identity。
- 通过独立设计评审、现场回放、回滚演练和用户明确批准。

## 9. 风险分级

| 等级 | 条件 | 处理 |
| --- | --- | --- |
| R0 阻断 | 敏感数据泄漏、业务结果/workbook/SQL漂移、`identity_changed>0`、diagnostics 改变终态 | 立即停止观测，作废工件，恢复旧输出并审计原因 |
| R1 高风险 | `available=false`、ambiguous/unresolved/missing scope 超阈值、基线 RSSI/备链缺失增加 | 不得接管；补数据、作用域或采样后重跑 |
| R2 观察 | duplicate MAC、MAC-like name、Radio/BSSID-only、interface/LLDP/optical fallback | 保留聚合诊断，不自动改字段或 identity |
| R3 信息 | matched/unchanged 稳定、计数与基线一致 | 可作为只读展示评估证据，仍不授权修复 |

## 10. 回滚和禁用策略

- 阶段 7 只有文档，没有运行时开关、数据库迁移或生产代码，删除文档增量即可回滚本阶段。
- 当前 shadow/diagnostics 未被 UI 消费。停止观测时，只需停止提取附加字段，继续使用旧 result、旧 workbook 和旧页面即可。
- 任何运行异常都应丢弃观测 summary，不得删除原数据库、raw log 或业务导出；使用步骤 2 的备份恢复测试副本。
- 临时 result/xlsx/调试输出在生成脱敏 summary 后删除；HMAC 密钥和 token 映射按现场安全制度销毁或归档。
- 若阶段 8 新增只读展示，必须使用独立 feature flag，默认关闭；关闭后不得影响 Job、Export Process、旧 UI 或业务结果。
- 禁止把“隐藏 diagnostics 展示”误当作禁用生产业务；旧 resolver、mapping、光衰、轨旁和 MR/Mesh 路径始终是回滚基线。

## 11. 观测结果模板

统一汇总只保存聚合和判断，不保存完整 shadow result：

```json
{
  "schema_version": 1,
  "campaign_id": "campaign-2026-001",
  "source_commit": "<commit>",
  "environment": "isolated-test-copy",
  "system_type": "PIS",
  "site_token": "Site-001",
  "period": "2026-07",
  "privacy": {
    "redaction": "hmac-sha256-campaign-key-v1",
    "raw_included": false,
    "database_included": false,
    "workbook_included": false,
    "samples_included": false,
    "warning_messages_included": false
  },
  "runs": [
    {
      "run_id": "run-001",
      "object_type": "mesh_link_detail_export",
      "trigger": "mesh_link_detail",
      "available": true,
      "total": 1000,
      "metrics": {
        "matched": null,
        "unresolved": null,
        "ambiguous": null,
        "identity_unchanged": null,
        "identity_changed": null,
        "name_only_matches": null,
        "mac_like_names": 3,
        "missing_ac_scope": null,
        "duplicate_mac_field_records": 120,
        "peer_mac_equals_peer_radio_mac": 120,
        "peer_mac_equals_ap_mac": 10,
        "radio_or_bssid_only_records": 0,
        "interface_only_records": null,
        "lldp_only_records": null,
        "optical_fallback_records": null,
        "missing_min_rssi_rows": 1000,
        "missing_backup_link_rows": 1000
      },
      "rates": {
        "ambiguous_rate": null,
        "unresolved_rate": null,
        "name_only_rate": null,
        "missing_ac_scope_rate": null
      },
      "warning_codes": ["DUPLICATE_PEER_RADIO_MAC"],
      "sample_limited": false
    }
  ],
  "decision": {
    "evidence_sufficient": false,
    "controlled_display_assessment": "hold",
    "controlled_repair": "blocked",
    "reasons": ["INSUFFICIENT_SITES", "DUPLICATE_MAC_FIELDS_PRESENT"]
  }
}
```

模板中的数字是虚构示例。`null` 表示该观测对象不提供该指标，不能转换为零。summary 文件不得直接提交仓库；如需在评审中引用，只提交再次检查后的统计摘录。

## 12. 后续决策路径

```text
完成脱敏观测
  ↓
数据泄漏或业务漂移？ ── 是 → 作废工件、停止、回滚
  ↓ 否
样本和接入可用性充分？ ── 否 → 继续只读采样
  ↓ 是
进入阶段 8：只读展示评估
  ↓
仅展示聚合、默认关闭、可禁用
  ↓
任何自动修复/生产接管需求
  ↓
单独立项、重新评审、用户明确批准
```

阶段 8 已完成观察结果只读展示方案评估，见 [AP_IDENTITY_DISPLAY_ASSESSMENT.md](AP_IDENTITY_DISPLAY_ASSESSMENT.md)。阶段 8.1 已实现默认关闭的纯 Python 聚合 ViewModel 和逻辑开关，但尚未执行真实局点采样，也未接入 Qt 宿主、报告或持久化。后续可见展示仍须通过本方案准入；不得修改生产数据、导出字段、报告 SQL、resolver、mapping 或业务判断。
