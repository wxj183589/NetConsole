# MR/Mesh AP Identity Resolver Shadow 评估

## 1. 背景

本评估对应 AP identity 阶段 5，并记录阶段 5.1 的第一批只读 shadow 接入。阶段 5 梳理 MR/Mesh、Online MR 和 Vehicle MR 当前如何表达、匹配和导出 AP/Peer/Radio 信息；阶段 5.1 只在三个旧 Job result 后附加诊断。

阶段 5.1 新增纯 Python `services/mr_mesh_identity_shadow.py`，并在 `mesh_log_import`、`online_mr_parse`、`vehicle_mr_mapping_load` 的旧结果完成后附加 `identity_shadow`。解析规则、Repository SQL、数据库 schema、页面字段或导出字段没有修改；现有 raw log、mapping/cache、主链路/备份链路、短时建链、乒乓、RSSI 和繁忙度规则仍是唯一生产结果。

关键结论：

- `peer_mac` 是 MESH 日志中的链路对端观测，不天然等于 AP MAC。
- `peer_radio_mac`、`radio_mac`、BSSID/BBSSID 属于射频或空口观测，不得直接折叠为 AP MAC。
- 离线 MESH、Online MR 离线解析、Online MR 实时页面和 Vehicle MR 没有完全共用同一条 lookup。
- 当前 AP 映射结果已经参与同 AP 双 Radio、短时建链和乒乓判断；阶段 5.1 只能旁路比较，不能替换这些字段。
- Mesh 链路明细已按既有要求移除“归属来源”和“Peer Radio MAC”；其他 Online MR 报告仍存在重复 MAC 展示风险。

## 2. 当前 MR/Mesh 数据来源

| 数据来源 | 当前入口 | 类型 | 当前用途与边界 |
| --- | --- | --- | --- |
| 离线 MR 原始 MESH 日志 | `MeshLogParser.parse_file()` | 原始观测 | 解析 Radio、LinkState、PeerMac、建链时间、时长、RSSI、CPU、内存和 Tx/Rx Busy；raw 文件归档并保留源行/偏移 |
| `mesh_link_raw.log` | `display clock` + `display wlan mesh-link` | 原始观测、链路状态 | Online MR 主链路/备链采样，生成 `main_link_samples`；兼容标准 MESH 行和带 Peer Name/BSSID 的表格 |
| `terminal_monitor_raw.log` | `terminal monitor` 的 `WMESH/5/MESH_ACTIVELINK_SWITCH` | 切换观测 | 生成主动链路切换日志；不替代周期 MESH 采样 |
| `switch_history_latest.log` | `display wlan mesh-link switch-history` | 切换历史 | 提供 from/to Peer、切换原因、In/Out RSSI、ActiveTime |
| `ap_radio_statistics_raw.log` | `display ar5drv <radio> statistics` | Radio 统计 | 提供帧、重试、错误、丢弃计数，不提供 AP identity |
| `channel_busy_raw.log` | `display ar5drv <radio> channelbusy` | Radio/信道状态 | 提供信道、频宽、Ctl/Tx/Rx Busy，不提供 AP identity |
| `wireless_status_raw.log` | `display ar5drv <radio> client all rssi/status` | 客户端/射频观测 | 保留 RSSI/status 原始输出；当前不是离线 MESH AP 主映射来源 |
| FIT-AP 资源 | `AcRepository.list_all_fit_ap_resources_with_metadata()` | AP Candidate | 为 Peer/BSSID resolver 提供 AP 名称、AP MAC、站点、序列号及显式 Radio 字段 |
| AP 扩展信息 | `TracksideApBssidResolver._extension_identity_rows()` | 补充 Candidate/位置 | FIT-AP 未覆盖时追加 extension；同 MAC或无 MAC 同名时避免重复追加 |
| 轨旁/光衰/实体/视图缓存 | `load_trackside_ap_lookup()` | Vehicle MR 旧 lookup | Vehicle MR 直接合并 FIT-AP、光衰、metadata、`ap_entities` 和 `trackside_ap_view_cache`；该路径与 Mesh resolver 不同 |
| 车载 MR 映射 | `VehicleMrTrainMapping` | 车端身份 | 把 Peer Name 映射到列车号和 TC1/TC2，不是轨旁 AP identity |
| 离线解析结果 | 每个 MR detail DB 的 `mesh_links`、mapping/cache、active 派生表 | 历史派生数据 | 页面、质量分析、图表和导出读取；`source_file_id` 是隔离边界 |
| Online MR 解析结果 | `parsed/online_diagnosis.sqlite` | 会话派生数据 | 保存主链路、切换、Busy、Radio、接口、Ping、iPerf 和融合结果 |
| 导出运行缓存 | `runtime/cache/export_jobs` | 任务运行文件 | 只保存 Export Job 运行材料；未发现独立的 AP identity 导出缓存，导出直接读取 detail DB/parsed DB |

原始日志始终是证据源。后续 shadow 不得改写、裁剪或用 identity 结果替代 raw line、raw file、offset 和 source file 信息。

## 3. 当前 AP / Peer / Radio 字段语义

| 字段 | 当前语义 | 主要来源 | 不能做的推断 |
| --- | --- | --- | --- |
| `peer_name` | 日志中的对端名称，可为空、重名或变更 | Online MESH 表、switch-history、terminal monitor | 不能无作用域地认定为唯一 AP |
| `peer_mac` / `peer_mac_normalized` | 当前 MESH 链路对端 MAC 观测 | 离线 MESH 行、Online MESH 表 | 不一定是 AP 基础 MAC，也不保证是物理 AP 唯一键 |
| `peer_radio_mac` | resolver 认为 Peer 观测命中了 Radio/BSSID 时记录的射频 MAC | `MeshPeerMappingService` / resolve cache | 不一定等于 AP MAC；即使等于 `peer_mac` 也只是同一观测的重复表达 |
| `peer_ap_mac` / `ap_mac` | 旧 resolver 匹配后的候选 AP 基础 MAC | FIT-AP、extension、Vehicle MR 多表 lookup | 只有带 match rule/唯一候选时才能解释 Peer 对应关系 |
| `peer_ap_name` / `ap_name` | 匹配后的 AP 展示名称 | FIT-AP、extension、旧缓存 | 名称可能重名、改名或跨站/跨 AC 重复 |
| `radio` | 日志采集侧 Radio 维度 | MESH 行或采集命令 | 不能与 `peer_radio_id` 混为一谈 |
| `peer_radio_id` / `peer_radio` | 对端 AP 射频编号/标签 | 显式 Radio/BSSID 或 H3C 派生匹配 | 不能替代 AP identity；同 AP 的 Radio 1/2 必须保持可区分 |
| `radio_mac` | Candidate 或 resolver 输出的 Radio MAC | FIT-AP/extension 字段或派生规则 | 不能直接回写为 AP MAC |
| `bssid` / `bbssid` | Online MESH/无线空口观测 | `display wlan mesh-link` 表格等 | 不能强行等同 AP MAC；只能作为 Radio/BSSID evidence |
| station/section | 位置与归属上下文 | FIT-AP、extension、光衰、轨旁缓存 | section 可以存在而 station 为空；位置不能作为无条件唯一身份 |

当前解析器允许 Peer Name 可选，因此能够表达“无 Peer Name、只有 Peer MAC/BSSID”的 V5/V7 混合样例。是否能匹配取决于后续 resolver 候选，而不是 parser 自动制造名称。

## 4. 当前 AP 匹配与 lookup 流程

### 4.1 离线 MR/Mesh

```text
原始 meshlog
  -> MeshLogParser（保留 PeerMac/Radio/LinkState/raw）
  -> mesh_links
  -> MeshPeerMappingService
  -> TracksideApBssidResolver
  -> FIT-AP + AP extension Candidate
  -> mesh_peer_mapping / mesh_peer_resolve_cache
  -> 回填 mesh_links
  -> Active/质量/切换派生分析
```

旧 resolver 的顺序是：显式 Radio MAC/BSSID → H3C Radio 1/2 派生 → AP MAC 精确 → Peer Name 精确。多候选返回 `multi_match`，不静默选择第一条。

离线 detail DB 的 mapping/cache 以规范化 `peer_mac` 为主键。`peer_ap_name`、`peer_ap_mac`、站点和 Radio 被回填到 `mesh_links`，但 section、belong type/source 没有完整进入 `mesh_links` 映射列；仅有区间、无站点的数据可能在离线链路明细中退化为空。

### 4.2 Online MR 离线解析

`OnlineMrDiagnosisParser` 从 raw 目录重建 `online_diagnosis.sqlite`：

1. `mesh_link_raw.log` 解析后使用 `MeshPeerMappingService.resolve(peer_mac, peer_name)` 补充名称、站点、区间和归属字段。
2. `switch_history_latest.log` 和 `terminal_monitor_raw.log` 使用 `ApRadioMappingService`；它包装同一个 `MeshPeerMappingService`，但 endpoint fallback 顺序和输出结构不同。
3. 主链路、切换日志、Busy、Radio、接口、Ping 和 iPerf 最后进入同一会话时间轴。

### 4.3 Online MR 实时页面

实时页面还维护两套页面缓存：

- MAC/BSSID 通过 `ApRadioMappingService.resolve_peer_mac()`。
- 非 MAC Peer Name 通过异步加载 FIT-AP/extension rows 后按 casefold 名称缓存。

实时事件、历史表格和图表可能在页面层再次补充站点/区间。因此 Online MR 的实时显示与离线重解析虽然复用部分 resolver，但不是单一、完全相同的匹配链路。

### 4.4 Vehicle MR

Vehicle MR 先按 `VehicleMrTrainMapping` 或 Peer Name 规则识别列车及 TC1/TC2，再用本地 `AP name/local MAC -> MatchedAp` lookup 判断车端当前关联的轨旁 AP。

该 lookup 直接合并 FIT-AP、光衰、AP metadata、`ap_entities` 和 `trackside_ap_view_cache`，并使用名称、MAC、H3C Radio 派生 fallback。它不复用 `ApIdentityResolver`，也不与离线 Mesh mapping cache 共用实现。当前 loader 还会用光衰站点回填 FIT-AP 站点，因此阶段 5.1 的只读 Candidate loader 不能直接调用这条带写入副作用的函数。

## 5. Online MR 与离线 MR/Mesh 差异

| 项目 | 离线 MR/Mesh | Online MR | Vehicle MR |
| --- | --- | --- | --- |
| 原始来源 | 归档 meshlog | 会话 raw 文件、terminal monitor、switch-history | AC `display wlan mesh-link` 周期输出 |
| 基础 parser | `MeshLogParser` | `online_mr_parser` + `OnlineMrDiagnosisParser` | `H3CComwareV9VehicleMrMeshLinkParser` |
| AP lookup | `MeshPeerMappingService` | parser/service + 页面缓存多路径 | `load_trackside_ap_lookup()` + `match_ap()` |
| Candidate | FIT-AP + extension | FIT-AP + extension | FIT-AP + 光衰 + metadata + entity + 轨旁 cache |
| 主链路基点 | 同 source file、Radio、采样时刻恰好一个 ACTIVE | `main_link_samples` 中 ACTIVE；切换日志另行融合 | 选在线状态且同 Peer 最强 RSSI，再匹配 local AP |
| 区间无站点 | resolver 可返回 section，但 detail DB 持久化不完整 | `main_link_samples` 可保留 section | 旧 lookup 主要返回 station，缺站点时多为“未知站点” |
| 历史隔离 | `source_file_id` + detail DB | `session_id` + raw file/offset | Vehicle store session/snapshot |

结论：只能设计共用的 shadow adapter 输入模型，不能假设三条生产链路已经统一。

## 6. 主链路、备份链路和链路顺序对 AP identity 的依赖

1. LinkState 来自原始日志，`ACTIVE` 与 `STANDBY/BACKUP` 规范化后仍保留原字段。
2. 离线质量分析按 `source_file_id + radio + sample_time` 分组；恰好一个 ACTIVE 才作为主链路，同采样组其余 STANDBY 才参与备份链路和最佳备链 RSSI。
3. 主链路区段先按原始 Peer key 连段，再从匹配结果补充 `peer_ap_mac/name/site/radio` 和 `physical_ap_key`。
4. 同 AP 双 Radio、短时建链和乒乓判断会读取 `physical_ap_key`。当前优先级是 AP MAC → AP name → Peer Radio MAC → Peer MAC；AP name 当前没有可靠的站点/AC 作用域。
5. 主链路持续时长由采样窗口与采样间隔计算，日志上报时长单独保留；二者不能互相替换。
6. RSSI/min RSSI 只从有效数值样本统计；缺失样本应继续显示 N/A，shadow 不得补造数值。
7. Tx/Rx Busy 区分 MR 侧和 Peer 侧；报告中的总 Busy 使用既有取值规则，identity 不参与计算。
8. 短时建链阈值继续使用“配置切换时间 - 容差”，不能恢复固定秒数判断。
9. AP_A → AP_B → AP_A 只有中间 AP 驻留明显短于配置切换时间才是乒乓异常；超过切换时间的普通回切不算乒乓。
10. 同一物理 AP 的 Radio 1/2 往返只标记同 AP 射频切换，不计 AP 乒乓。

因此阶段 5.1 的 shadow 输出不得覆盖 `peer_ap_*`、`physical_ap_key`、Active/Standby、segment、switch、short-link 或 pingpong 字段。

## 7. 导出字段与重复 MAC 风险

### 7.1 当前受保护行为

- Mesh 链路明细导出当前保留 Peer MAC、对端 AP MAC、对端 AP 名称、归属站点/区间/类型和对端射频口。
- 按既有要求，链路明细不再导出“归属来源”和“Peer Radio MAC”；对应 golden tests 已锁定表头。
- 导出进程直接从 `MeshMrRepository.iter_link_details()` 和主链路建链顺序查询读取，不经过页面表格，也没有独立 identity export cache。

### 7.2 已发现但本阶段不修复的风险

- Online MR 分析报告的“MESH链路明细”SQL 当前把同一个 `peer_mac` 同时写入 PeerMac、AP MAC、Peer Radio MAC 三列，存在确定的重复展示风险。
- Online MR 主链路报告仍包含“归属来源”，与 Mesh 链路明细的既有字段策略不同；不能在 identity 评估中顺手统一表头。
- 离线 mapping cache 会把命中 Radio 时的 `peer_radio_mac` 设为原始 Peer MAC，因此任何同时展示两列的消费者都必须先判断是否相同。
- “全无备份链路”历史上可能由采样分组、source file 隔离或 STANDBY RSSI 缺失造成；当前代码和测试已按同 `source_file_id/radio/time` 统计，shadow 不能改变分组。
- 大量最低 RSSI 无值可能来自原始 RSSI 缺失、无法解析或区段没有有效样本；当前统计跳过空值并显示 N/A，shadow 只能报告缺失率。

阶段 5.1 只允许输出 `duplicate_mac_fields`、`missing_rssi_count`、`missing_backup_context_count` 等诊断，不改 workbook、CSV、报告 SQL或页面列。

## 8. 字段和标识冲突

1. `mesh_peer_mapping` 和 resolve cache 按 Peer MAC 单键保存，没有 AC/站点作用域；同观测在多 Candidate 局点可能 ambiguous。
2. Peer Name 和 AP Name 的 casefold cache没有 AC 作用域；同名会被覆盖或产生不稳定候选。
3. 离线 `physical_ap_key` 当前在有 AP Name 时先返回 name key，站点组合分支不能形成实际约束；同名跨站可能被视为同一物理 AP。
4. Vehicle MR 多表合并 key 是 AP MAC或 AP Name，名称记录和 MAC记录可能形成两个聚合对象，字典写入又可能覆盖同名 key。
5. section-only 数据能在 resolver/Online parsed result 中表达，但离线 Mesh 主链路映射持久化和 Vehicle MR 展示并不完整一致。
6. `peer_mac == peer_radio_mac` 是常见的派生结果，不表示同时获得了两个独立 identity 证据。
7. BSSID、Radio MAC 和 Peer MAC 的 H3C 派生规则用于旧匹配，但不能写入通用 `ApIdentityResolver` 的隐式优先级。
8. 无 Peer Name 的日志只能依赖 MAC/BSSID evidence；不得为了填充展示字段把 MAC复制成 AP Name并视为匹配成功。

## 9. AP identity 工具可接入点

| 候选接入点 | 输入字段 | Candidate 来源 | 建议 shadow 输出 | 生产影响 | 主要风险、回滚与测试 |
| --- | --- | --- | --- | --- | --- |
| 离线 MR/Mesh 导入完成后（已接入） | distinct Peer MAC、旧 mapping、可选 Peer Name、Radio、source file | FIT-AP + entity + extension，只读快照 | matched/unresolved/ambiguous、old/new candidate、Radio evidence、缺作用域 | 无；只附加 Job result | resolver 异常返回 unavailable；删除字段回滚；锁定旧 mapping、derived rows 和分析结论 |
| Mesh 链路明细导出前 | 实际导出 rows 的 Peer/AP/Radio字段 | 已有 mapping + Candidate 快照 | duplicate MAC、字段冲突、缺失 identity/RSSI 统计 | 无；不改导出列和值 | 大数据扫描成本；仅采样/汇总并失败隔离；golden XLSX 必须完全一致 |
| Online MR 解析完成后（已接入） | `main_link_samples` 的 distinct Peer Name/MAC/BSSID、session/source | FIT-AP + entity + extension，只读快照 | old/new identity、name-only、BSSID-only、section-only、缺失率 | 无；仅附加 parse Job result | parsed DB 以只读 URI 打开，不写新列；旧 summary、图表、切换表保持一致 |
| Vehicle MR mapping load 后（已接入） | 原 `mappings` 中 TC1/TC2 Peer Name | FIT-AP + entity + extension只读快照 | name-only、missing scope、unresolved/ambiguous | 无；只附加 load Job result | 不调用带站点回填的 loader；车端Peer Name明确标记为低置信 observation |
| 单 AP 动态图表数据加载后 | anchor link、Peer/AP/Radio字段、`source_file_id` | 当前 detail DB mapping + Candidate 快照 | Peer/Radio语义、跨文件冲突、重复 MAC | 无；图表 payload外附诊断 | `anchor_link_id` 非全局唯一；必须以 detail DB + source file隔离，tooltip payload不变 |

不建议把第一批 shadow 放进 UI page、export formatter 或 parser 行级循环。优先在现有 Job/Service 已完成生产结果之后做一次批量、可失败隔离的诊断。

## 10. 不建议立即替换的范围

- `MeshLogParser`、Online MR parser、terminal monitor/switch-history parser。
- `MeshPeerMappingService`、`TracksideApBssidResolver` 和 Vehicle MR 旧 lookup。
- `mesh_peer_mapping`、resolve cache、`mesh_links`、`online_diagnosis.sqlite` schema。
- ACTIVE/STANDBY、主链路建链顺序、备份链路、RSSI/min RSSI 和 Busy 计算。
- 同 AP 双 Radio、短时建链、乒乓、普通回切和 source-file 隔离规则。
- Mesh 链路明细、分析报告、Online MR 报告和页面表头/字段。
- Online MR 采集命令、raw 文件命名、终端日志和 Job/Worker 协议。

发现的重复列、作用域缺失、section 丢失、name cache 覆盖或 Vehicle loader 写入副作用，本阶段只记录。

## 11. 阶段 5.1 只读 shadow 接入

### 11.1 适配器边界

当前新增纯 Python `services/mr_mesh_identity_shadow.py`：

```text
MrMeshIdentityShadowService
  - build_observation_from_mesh_link(row)
  - build_observation_from_online_mr_summary(row)
  - build_observation_from_vehicle_mr_mapping(row)
  - compare_old_mapping(observation, old_mapping, candidates)
  - inspect_export_field_conflicts(rows)
  - summarize(items)
```

适配器只接收普通 Mapping/Sequence，不导入 UI、Repository、Worker、数据库、网络连接或 parser，不计算链路质量。

### 11.2 当前接入顺序

1. `mesh_log_import` 完成旧 mapping/cache和派生重建后，读取现有 distinct mapping/cache并附加聚合 `identity_shadow`，不持久化。
2. `online_mr_parse` 返回旧 summary后，以只读模式读取已生成的 `main_link_samples` distinct observation并附加 shadow，不改 parsed DB。
3. `vehicle_mr_mapping_load` 返回旧 mappings后，只使用映射行和安全 Candidate快照做低置信名称诊断，不调用站点回填写 lookup。
4. Candidate快照只读取 FIT-AP、`ap_entities` 和AP扩展信息；H3C 4-4-4 MAC只在shadow适配边界规范化。
5. 单 AP图表仍未接入；阶段 6.1 已在 Mesh 链路明细和 Online MR 兼容详细报告接入只读 diagnostics，但未修改 formatter、SQL、表头、行值或业务规则。

建议输出：

```text
available
total
matched
unresolved
ambiguous
identity_unchanged
identity_changed
name_only_matches
peer_mac_only
bssid_only
radio_only
missing_scope
section_only
duplicate_mac_fields
missing_rssi_count
warnings
items
```

shadow 失败统一 `available=false`，旧任务继续原 finished/failed/cancelled 终态。任何 shadow 字段都不得被页面、导出或分析规则消费。

## 12. 测试策略

阶段 5.1 至少需要：

1. 同一份离线日志删除 shadow 后，`mesh_links`、mapping/cache、active points/segments、switch、quality和报告结果完全一致。
2. Online MR parse summary、`online_diagnosis.sqlite` 表结构和全部旧行完全一致。
3. V5 无 Peer Name、V7 Peer Name、Peer MAC、BSSID、显式 Radio MAC、H3C Radio 1/2、非法/空 MAC。
4. 同名跨 AC/站点、同 MAC 多候选、extension-only、section-only和无 FIT-AP Candidate。
5. `source_file_id`、session、detail DB隔离；不得用 `anchor_link_id` 跨库匹配。
6. 同 AP Radio 1/2 的 old/new physical AP 对比，但旧短链/乒乓结论必须不变。
7. ACTIVE/STANDBY上下文、全无备链风险、RSSI/min RSSI缺失率只诊断不修复。
8. Peer MAC与Peer Radio MAC相同/不同；所有旧导出表头和值保持 golden一致。
9. shadow异常、空 Candidate、大数据取消；旧任务只产生一个终态。
10. 静态确认 adapter不导入 UI/Repository/Worker，生产 parser和导出 formatter不导入 shadow。

## 13. 回滚策略

- 阶段 5 文档检查点已单独提交。
- 阶段 5.1 不新增 schema、不写 shadow cache；删除三个 Job result附加字段和纯 adapter即可回滚。
- 旧 parser、mapping/cache、Vehicle lookup、derived analysis和导出 formatter必须始终保留为生产路径。
- shadow unavailable、unresolved、ambiguous或 identity changed只记录诊断，不阻断导入、解析、采集、图表或导出。
- 阶段 6 导出入口、字段差异和只读 diagnostics 设计见 [EXPORT_FIELD_DEDUP_ASSESSMENT.md](EXPORT_FIELD_DEDUP_ASSESSMENT.md)。
- 阶段 6.1 P0 只返回有限聚合计数和样例引用；失败为 `available=false`，默认不写 sidecar，原始 H3C raw log、parser 输出、mapping/cache 和 workbook 保持不变。
- 阶段 7 真实局点 MR/Mesh 观测只使用日志/会话副本，提取聚合后丢弃 items、evidence、warning 明文和临时 xlsx；统一口径、脱敏和阈值见 [AP_IDENTITY_OBSERVATION_PLAN.md](AP_IDENTITY_OBSERVATION_PLAN.md)。
- 在真实局点 shadow证明候选稳定、作用域充分且旧/new结论可解释之前，不进入生产 resolver接管或导出字段删除、改名、合并阶段。
