# AP Identity

## 1. 当前定位

`src/netconsole/services/ap_identity/` 是局点级 AP 身份、MAC 别名和
H3C Radio 衍生索引的生产实现。它统一读取当前局点的基础资料、
AC/FIT-AP/Radio 数据和历史兼容缓存，将物理 AP、AP 基础 MAC、
Radio/BSSID/BBSSID、位置和来源证据分开保存。

生产消费者分阶段接管。当前已完成的生产路径是：

- MR 原始 MESH distinct Peer 的批量匹配、持久化投影和 identity-only remap；
- 地面无人值守实时与历史 WMESH Peer 的批量匹配和 revision 缓存；
- 车载 MR 实时采样、Online MR 历史 parsed DB 与无线扫描的批量匹配和 revision 投影；
- AC/FIT-AP 与轨旁 AP 搜索的统一查询入口；
- 轨旁 AP 业务快照、筛选、分页和导出的统一批量投影。

AC Mesh-Link、基础资料的直接 Identity JOIN、部分报告读取以及设备/LLDP
topology binding 等遗留入口仍在审计白名单内，不能视为已经完成统一。
新增消费者不得复制这些遗留实现。

普通查询只读取 `devices.db` 中已生成的统一索引，不连接 AC，不执行
SSH、SNMP 或采集，不要求 `ac_device_uuid`，也不在请求期间重建索引。
光衰更新、AC 深度采集和远程配置仍由 AC 业务服务控制，继续要求有效
AC 绑定。

统一范围只覆盖“观测 MAC 或物理 AP 查询条件 -> 物理 AP 身份”的解析段。
采集、筛选、告警、主备链、拓扑、光衰、图表和报告规则仍由各业务领域负责。
统一 Identity 基础设施进入生产不等于 AP Identity 已全面接管，也不授权
Identity Service 写回来源主数据。

轨旁 AP 基础资料统一事务提交后，Application Service 只调用一次
`ensure_index`：来源 revision 未变化时不写索引，变化时在事务提交后重建。
基础资料 GET、轨旁 AP 业务查询和逐行 MAC 解析只固定并读取当前索引健康
状态；不得把 `ensure/rebuild` 放进 GET。LLDP 生产绑定只接受完整规范化邻居
MAC/Chassis MAC，IP、系统名、AP 名称和相似度仅进入诊断字段。

## 2. 数据来源

身份来源分为：

1. `ac_runtime`：当前 AC FIT-AP、显式 Radio MAC、BSSID 和 BBSSID；
2. `base_data`：轨道交通基础资料中的 AP 名称、MAC、站点、区间、
   点位、方向和里程；
3. `legacy_cache`：`ap_entities`、`ac_fit_ap_optical` 和
   `trackside_ap_view_cache` 等历史兼容数据。

基础资料是无 AC 场景的独立身份基线，不是 FIT-AP 的附属补充。历史
兼容数据只提供最低优先级的精确 MAC 别名，不生成 H3C 前缀，也不能
覆盖当前 AC 或基础资料。

### 2.1 模型分层

同一个物理 AP 在不同来源中存在多种标识，必须按语义分层：

| 层 | 典型字段 | 长期边界 |
| --- | --- | --- |
| 物理 AP identity | `ap_uuid`、AP MAC、序列号、AP 名称、AC 原生 `apid/ap_id` | `ap_uuid` 是局点数据库内已解析实体；表内 `id`、AC 原生 APID 与 `ap_uuid` 不得混用 |
| Radio/BSS identity | Radio ID、Radio MAC、BSSID、BBSSID | 是 AP 子实体或精确别名，不能写回为物理 AP MAC |
| observation | Peer MAC、Peer Radio MAC、Peer Name、源文件/会话 | 保存原始观测和解析证据；相同值不表示语义相同 |
| location | 业务站点、区间、点位、里程、方向 | 位置证据不单独确定物理 AP；区间存在时站点允许为空 |
| topology | 交换机 `device_uuid + interface`、LLDP 邻居 | 表达时间相关连接关系，不是 AP identity；端口移动不能改变物理 AP 身份 |
| telemetry/status | 光衰、在线状态、采集时间 | 由领域规则解释，不参与创建 Identity 实体 |

`CanonicalApIdentity`、`CanonicalApRadioIdentity`、`CanonicalApLocation` 和
`ApObservation` 是适配器、shadow 和兼容解析使用的纯 Python 模型；生产索引
实体与 Query 契约位于 `models/ap_identity_index.py`、`index_builder.py` 和
`query_service.py`。`CanonicalApProfile` 只应理解为查询聚合/ViewModel 边界，
不得新建第二张 AP 宽表或平行主数据 Repository。

基础资料、AC 运行资源和历史缓存是索引写入来源；MESH、Ground、Online MR、
Vehicle MR、Wireless、页面和导出是只读消费者，只能写各自可重算的观测或
派生投影。只有 AC 资源 Repository 的既有写入流程可以创建新的 `ap_uuid`。

## 3. MAC 规范

统一索引使用 `normalize_mac_key()`，接受常见格式并输出 12 位小写
无分隔符：

```text
4873-97cc-e9af
48:73:97:cc:e9:af
48-73-97-cc-e9-af
4873.97cc.e9af
487397cce9af
```

统一索引 key 均为：

```text
487397cce9af
```

用户可见的新 AP Identity 输出通过 `format_mac()` 使用小写 H3C 格式：

```text
4873-97cc-e9af
```

`normalize_mac()` 继续输出旧冒号格式，供已有领域契约兼容。新索引、
比较和查询代码必须显式使用 `normalize_mac_key()`。AP 名称即使外观
像 MAC，也不会自动写入物理 `ap_mac`。

H3C Radio 衍生只接受明确厂商为 `H3C`、格式合法且末位为 `0` 的物理
AP MAC。Radio 1 保持前 11 个十六进制字符并将末位改为 `F`；Radio 2
将倒数第二位加一并将末位改为 `F`。已经以 `F` 结尾的 Radio 观测值、
厂商不明或非 H3C 的 MAC 都不得再次衍生。索引构建阶段生成的是完整
48 位 Radio alias，查询仍做规范化后的完整等值匹配，不恢复
`h3c_radio_block_36` 等前缀规则。

FIT-AP 离线不改变物理身份。AC 资源写入会在本次 address 输出缺少该 AP
时保留已有合法 `ap_mac` 和稳定 `ap_uuid`，同时允许 `ap_ip` 清空、Radio
状态变为 `Down`。离线状态、空 IP 或 Radio Down 都不会排除 Identity entity
或删除完整 R1/R2 derived alias。名称只可在同一 AC 的 FIT-AP 刷新中作为
唯一连续性证据，不进入索引实体合并、`resolve_peer_mac()` 或 MESH 生产匹配。

## 4. 实体合并与冲突

索引构建器只按稳定 AP UUID、完整规范化 AP MAC 或唯一序列号合并来源。
AP 名称和点位码不再作为物理实体合并依据；同名但 MAC 不同的记录必须
保留为不同物理 AP。有效身份优先使用 AC 运行数据；AC 不存在或暂时
没有该 AP 时，基础资料实体继续有效。

AC 与基础资料 MAC 或名称不一致时：

- 有效 AP 名称、AP MAC 和实际 Radio/BSSID 使用 AC 数据；
- 基础资料原值保留在实体和冲突记录中；
- 写入 `AP_IDENTITY_AC_BASE_CONFLICT` 数据质量告警；
- MESH、搜索、页面和报告继续返回 AC 匹配结果，不因冲突变成
  `unresolved`；
- 同层存在多个不同物理 AP 候选时仍返回 `ambiguous`，不静默选择第一条。

## 5. 匹配优先级

物理 AP 查询使用 `resolve_ap_mac()`；`resolve_mac()` 仅作为现有调用点的兼容
别名。两者只查询完整 48 位精确别名，按层短路：

1. AC 实际 Radio MAC；
2. AC 实际 BSSID；
3. AC 实际 BBSSID；
4. AC FIT-AP 物理 MAC 生成的 H3C R1/R2 完整精确 Radio alias；
5. 基础资料物理 MAC 生成的 H3C R1/R2 完整精确 Radio alias；
6. AC FIT-AP AP MAC；
7. 基础资料 AP MAC；
8. 历史兼容 MAC。

MESH Peer 使用独立的 `resolve_peer_mac()`。Peer 是 Radio/BSSID 观测，
生产匹配只允许前三类 AC 实际精确值或完整 H3C R1/R2 精确 alias；
即使 Peer 恰好命中 AP 基础 MAC，也不能据此认定它代表物理 AP。

两条查询都不再使用 36/40 位或 OUI 前缀、名称、MAC-like 名称、位置、
站点或“唯一候选”推测。没有完整精确证据时返回 `unresolved`；同一
优先级精确 alias 指向多个实体时返回 `ambiguous`。同一完整 alias 由
实际值和衍生值共同指向同一物理实体时可正常匹配；不同物理实体重复
占用该 alias 时不得按名称、站点或来源优先级静默消歧。

高数据量消费者使用 `resolve_peer_macs()` 或 `resolve_ap_macs()`。批量入口先
规范化并去重，在同一个只读事务中读取 index state、source revision 和 alias，
返回以 12 位紧凑 MAC 为键的结果。单批健康检查只执行一次，每个
`ApIdentityMatch` 携带同一 `identity_revision`；不得再按原始事实逐行查询。

批量入口返回 `ApIdentityBatchResult`。它实现只读 `Mapping[str,
ApIdentityMatch]`，现有按 key、`values()` 或 `dict.update()` 消费方式保持兼容，
同时提供以下批次元数据：

- `revision`：本批固定的 Identity revision；
- `index_status`：`ready`、`identity_index_missing`、
  `identity_index_stale` 或未访问数据库时的 `not_checked`；
- `requested_count`：原始输入数量；
- `normalized_count`：可规范化输入数量，包含重复格式；
- `distinct_count`：规范化去重后的查询数量；
- `matched_count`、`unresolved_count`、`ambiguous_count`：有效 distinct
  查询的结果统计；
- `invalid_count`：无法规范化的输入数量；
- `matches`：以紧凑 MAC 为键的结果映射。

空输入或全无效输入不访问 SQLite，`index_status=not_checked`。批量查询中的
无效值只进入统计，不伪造结果 key；歧义仍保留为 `ambiguous`，不得选择第一条。

## 6. 持久化结构

统一索引位于每个局点的 `devices.db`：

- `ap_identity_entities`：物理 AP 的有效身份和各来源原值；
- `ap_identity_mac_aliases`：AP、Radio、BSSID 和兼容 MAC 别名；
- `ap_identity_h3c_prefixes`：保留的历史诊断数据，生产查询不读取；
- `ap_identity_conflicts`：AC/Base 不一致及可审计上下文；
- `ap_identity_index_state`：revision、构建原因、来源计数和时间。

当前主数据库 schema 版本以 `src/netconsole/core/database.py` 的
`CURRENT_SCHEMA_VERSION` 为唯一事实源；本次文档复核时为
`2026.08.07.ap_topology_resolver`。初始化是增量且
幂等的，不删除现有 AP、日志、规划或缓存数据。

## 7. 索引刷新边界

索引只在明确写事件后刷新：

- 基础资料导入应用、回滚、保存、删除或清空；
- AC FIT-AP 刷新、删除、metadata 导入或保存；
- AC/FIT-AP 或轨旁 AP 光衰任务成功写入身份来源；取消前已经提交部分
  光衰结果时，仅在检测到 revision 变化后补建；
- 局点包在 staging 数据库发布前完成初始化和重建。

查询服务不得调用 `ensure_index()` 或 `rebuild_index()`。这保证搜索、
MESH 分析、历史报告和页面刷新都是只读操作，数据库指纹在普通 GET
请求期间保持不变。

Backend 启动只保留缺失或过期索引的兼容性收口；`_initialize_active_site_database()`
在数据库初始化/历史行规范化完成后调用一次 `ensure_index("backend_startup")`，
确保启动期间可能提升的 source revision 与只读索引一致。正常来源写入不会依赖
启动时机，也不会把启动修复当作来源写入的替代路径。

来源 revision 监听 `ap_extension_points`、FIT-AP 当前资源、
Radio/LLDP 历史、FIT-AP metadata、兼容 AP entity/光衰/轨旁缓存，以及
被 FIT-AP 资源引用 AC 的 `devices.device_uuid/device_vendor`。无关交换机、
未被 FIT-AP 引用的设备和 `device_facts` 更新不提升 revision，普通设备
状态采集不会把 AP Identity 误标为 stale。写任务完成全部来源持久化后
按批次只构建一次，禁止在每台 AP、每条 Radio/LLDP 或 GET 中重建。

`source_revision=0` 是“当前来源 revision 合法为零”，不是缺失或过期。
只有索引状态不存在/索引 revision 无效时返回 `identity_index_missing`，
索引记录的来源 revision 与当前来源 revision 不等时返回
`identity_index_stale`。索引 diagnostics 同时保存拓扑投影版本；版本低于
当前 resolver 时返回 `identity_topology_projection_stale`，由 MESH 来源重建等
受控写任务重建索引后再投影，普通 GET 不执行补写。来源写任务在独立短事务内构建并原子替换实体、
alias、冲突和状态；构建失败保留旧索引，不在普通 GET 中执行重建、
checkpoint 或其他补写。

## 8. 消费端契约

匹配结果保留以下关键证据：

- 查询 MAC 与统一显示值；
- `matched/unresolved/ambiguous`；
- 有效 AP 名称、MAC、站点、区间、点位和里程；
- 命中别名类型、来源、规则、置信度和 Radio ID；
- AC AP MAC、基础资料 AP MAC、基础资料记录 ID；
- 冲突状态和 `AP_IDENTITY_AC_BASE_CONFLICT`。
- 本次查询快照的 `identity_revision`。

搜索 Radio/BSSID 或完整 H3C R1/R2 衍生 alias 时，结果返回对应物理
AP，并区分“查询/命中 MAC”和“有效 AP MAC”。业务 DTO 可以按现有
领域契约裁剪，但不得重新实现 H3C 推导或维护第二套 MAC 索引。

MESH DTO、页面和导出必须同时保留原始 Peer、规范化 Peer Radio 观测与
解析出的 AP 身份。`unresolved/ambiguous` 时原始 Peer 继续显示，AP
名称、物理 AP MAC、站点、区间和里程保持空值，并携带状态、规则、
来源、置信度和原因。

Online MR 离线解析同样批量消费 `resolve_peer_macs()`：主链路和切换事件
保留原始 Peer Radio MAC，并把有效 AP 名称、物理 AP MAC、站点和区间
投影到 `parsed/online_diagnosis.sqlite`。本机 BSSID 不作为 Peer 缺失时的
替代查询证据；空切换端点标记为 `empty`，不计入 `unresolved/invalid`。
主链路信息、链路明细、切换历史和实时切换 DTO 只能读取这套投影，不得
各自实现 MAC 推导或位置关联。

LLDP 历史或当前事实可能记录同一 AP 连接过多台交换机。多台交换机均指向
同一个非空 `station_id`/站点时，位置投影保留该站点并附加
`topology_lldp_multiple_switches`；只有站点证据相互冲突时才按歧义处理，
不得因为正常换机历史清空已确认站点。

例如离线物理 AP `bc5a-3457-b5e0` 的合法 H3C Radio 2 alias
`bc5a-3457-b5ff` 仍通过完整 MAC 等值解析。来源 revision 改变后继续复用
现有 identity-only remap：更新 distinct Peer 的身份投影，不重新解析或
修改 raw MESH 日志。

未匹配原因按事实区分为 `invalid_peer_mac`、`identity_index_missing`、
`identity_index_stale`、`identity_topology_projection_stale`、`exact_alias_not_collected`、
`exact_alias_not_found`、`duplicate_exact_alias`、
`physical_ap_missing` 和 `station_topology_missing`，页面和报告不得把这些
原因重新折叠成无法诊断的单一“未关联”。

地面无人值守不再读取基础资料和 AC 明细后自行建立 AP/Radio/Alias 字典。
历史页先对当前页观测 MAC 去重并批量解析；实时 Receiver 只缓存统一查询结果，
Identity revision 变化后清空缓存并在下一批解析。实时事件的既有
`parsed_details` 保存 entity、revision、状态、来源和原因；历史 NDJSON 保持
只读，只在返回投影中补充当前身份。

### 8.1 消费者状态

下表描述的是身份解析段，不代表对应领域的全部业务已经迁入 Identity：

| 消费者 | 当前身份入口 | revision / remap | 状态与边界 |
| --- | --- | --- | --- |
| 离线 MESH | distinct Peer 使用 `resolve_peer_macs(ap_role="trackside")` | detail/source 保存批次 revision；支持 identity-only remap | 已接管；不改 raw、主备链、RSSI、Busy 或切换规则 |
| Ground 实时/历史 | Current AP 使用 `resolve_current_ap_macs()`；Peer 使用批量受限查询 | 实时缓存随 revision 失效；历史只读重投影 | 已接管身份解析段；历史 NDJSON 不回写 |
| Vehicle MR 实时 | 每次采样固定一批 `resolve_peer_macs()` 结果 | snapshot/link 保存 revision、index status 和计数 | 已接管；采集命令与原始链路字段不变 |
| Online MR 历史 | parser/remap 读取 distinct Peer 后单批解析 | metadata 和派生表保存 revision；remap 不读 raw | 已接管；主链、明细和切换 DTO 只读统一投影 |
| Wireless Scan | `TracksideApBssidResolver.resolve_many()` | run/result 保存 revision、status 和统计 | 已接管；原始 BSSID 保留 |
| 轨旁 AP 业务/导出 | 页面提交阶段单批 `resolve_ap_macs(ap_role="trackside")` | 页面快照、staging、Task result 和 Artifact 固定 revision | 已接管投影；Export Worker 不重新查询 Identity，拓扑/光衰仍归轨旁领域 |
| FIT-AP/AC 与基础资料搜索 | `search_aps()`、实体查询及兼容入口 | 只读当前索引 | 部分统一；领域资源与写入仍归 AC/Base Data |
| AC Mesh-Link | 统一单值 Query 与本地候选/直接表读取并存 | 尚未统一持久化 | 显式兼容白名单；不得复制私有 `by_mac` 或直接 JOIN 到新消费者 |
| 基础资料关联、部分报告读取 | 统一搜索/Query 与直接 Identity JOIN 并存 | 各领域不完全一致 | 继续收敛；不得宣称全面接管 |
| 设备/LLDP topology binding | 领域索引和部分 Identity 表读取 | 尚无统一 revision 契约 | Identity 只解析身份，拓扑关系继续由设备/轨旁领域拥有 |

架构门 `tests/test_ap_identity_consumer_architecture.py` 禁止新的消费者建立私有
H3C/MAC 索引、调用旧 Radio Resolver 或直接访问 Identity 表。现有直接表访问
只允许测试中的显式白名单；白名单是待收敛债务，不是新实现范例。

### 8.2 诊断、展示与脱敏

`identity_shadow`、`detail_identity_shadow` 和 `export_identity_diagnostics`
是生产结果旁路诊断。诊断失败必须返回安全的 `unavailable/failed` 状态，不能
改变原 Job/Export 的 `finished/failed/cancelled`、业务成功提示、页面结果、
workbook、Repository 写入或 resolver 决策。

`src/netconsole/models/diagnostics_summary.py` 是诊断摘要的永久允许列表模型。
当前可复制的通用聚合字段为：

```text
available, total, matched, unresolved, ambiguous,
identity_changed, identity_unchanged, name_only_matches, mac_like_names,
missing_ac_scope, duplicate_mac_field_records,
peer_mac_equals_peer_radio_mac, peer_mac_equals_ap_mac,
radio_or_bssid_only_records, interface_only_records, lldp_only_records,
optical_fallback_records, missing_min_rssi_rows, missing_backup_link_rows
```

来源不支持的指标必须保持缺失/`null`，不得用 `0` 冒充已计算；`total=0` 与
`not_collected` 必须区分。比例只在同一次、同一对象的 `total` 上计算，PIS、
信号系统、不同 AC、不同 Job 类型不能直接合并平均。

以下内容不得进入 ViewModel、可见 UI、普通日志或默认报告：`items`、`samples`、
`evidence`、warning/error/traceback 原文、old/new candidate key、明文 AP/Peer/
Radio/BSSID/BBSSID、IP、设备/线路/站点/区间/MR/AC 名称、里程、精确时间、
原始日志/数据库/session/xlsx 路径、凭据或命令回显。展示层必须复制允许字段并
立即丢弃原始 result 引用；未知字段一律丢弃，不提供“查看原始 JSON”入口。

逻辑开关 `ap_identity_diagnostics_enabled` 与
`ap_identity_diagnostics_ui_enabled` 均缺省关闭；samples 开关即使开启也不授权
暴露明细。当前 AP Identity 摘要尚未接入全局任务中心或具名 Vue 页面；后续
可见展示必须单一宿主、internal-only、默认关闭，不新增第二套任务持久化。
Qt Job/Dialog/Manager 已退出活动架构，不得恢复。

诊断状态 `not_collected`、`disabled`、`unavailable`、`insufficient_fields`、
`failed`、`redacted` 和 `not_supported` 都只描述诊断区域。`unresolved` 不等于
业务失败，`ambiguous` 不允许静默选第一条，`identity_changed` 只阻断未来
接管评估，不覆盖当前生产结果。

### 8.3 真实局点观测与接管门

真实局点观测优先使用授权数据的隔离副本，只提取脱敏聚合，不保存完整 Job
result、raw log、SQLite、xlsx、截图、token 映射或 `items/samples/evidence`。
MAC/IP 使用 campaign 专用 HMAC-SHA-256，设备、线路、站点、区间、MR 和 AC
使用独立 token；路径不得含现场名称。HMAC 密钥和 token 映射单独受控保存，
任何可共享工件需再次检查 MAC/IP/路径/客户名和自由文本。

观测指标不能跨语义对象拼接分子分母。初始保守门槛仅用于判断是否允许评审
新的生产接管或可见展示，不是应用业务规则：

- `identity_changed == 0`；
- `ambiguous_rate <= 1%`；
- `unresolved_rate <= 5%`；
- `name_only_rate <= 10%`；
- `missing_ac_scope_rate <= 5%`；
- `missing_min_rssi_rows` 与 `missing_backup_link_rows` 不高于同入口、同筛选基线。

资料覆盖不足时，`unresolved/ambiguous` 可以是正确结果。验收必须以“具备唯一、
合法、可派生精确 Alias 证据的 Peer 是否全部正确匹配”为口径，不能要求
`matched_count == distinct_peer_count`，更不能用名称、前缀、站点或记录顺序
强行提高匹配率。新增生产消费者必须完成旧/新结果对照、真实观测、单模块
回滚和消费者测试；证据不足时结论固定为不接管。

### 8.4 导出字段边界

导出是 Identity 的只读消费者，不是身份来源。原始 Peer MAC、Peer Radio MAC、
BSSID/BBSSID、物理 AP MAC、AP 名称、Radio、位置、匹配规则和身份来源即使值
相同，也可能表达不同层级，不能按值相同机械删除、合并、改名或回写。
OmniPeek 的物理/R1/R2 MAC 是目标格式要求，也不属于重复列。

`ExportIdentityDiagnostics` 只能旁路统计重复值、MAC-like 名称、Radio/BSSID-only、
作用域、最低 RSSI 或备链上下文缺失。它不修改 formatter、报告 SQL、Sheet、
表头、行值、ACTIVE/STANDBY、主备链、RSSI、Busy、短链或乒乓结论；输入字段
不足时返回 `available=false`，不能为补齐诊断扩大查询。默认不生成 sidecar，
diagnostics 失败不使原导出失败。

导出回归使用结构化逻辑 golden，检查 Sheet、表头、关键行值、数据类型、筛选、
冻结窗格、样式、列宽、取消和临时文件清理；不使用不稳定的 XLSX 二进制哈希。

## 9. 兼容与回滚边界

旧 `CanonicalApIdentity`/resolver 数据类和部分适配器仍保留给历史
诊断及精确兼容调用。生产 MESH、Vehicle、Wireless 和搜索入口不得
回退到各模块自行维护的 H3C 映射。

回滚统一索引接管时必须同时回滚消费者、写事件刷新和数据库 schema
消费者；不得仅删除索引表而保留生产查询引用。原始 MESH 日志、AC
资源、基础资料、历史缓存和正式报告都不是索引派生物，禁止随索引
回滚删除。

## 10. 维护与验证

修改 schema、来源优先级、MAC 规范化、精确 Alias、revision、批量快照、
消费者投影、diagnostics 或导出身份字段时，至少核对：

- 精确、无解、多候选、跨 AC 重复、同名不同 MAC、MAC-like 名称；
- AP MAC、Radio/BSSID/BBSSID、Peer、Current AP 的不同查询语义；
- AC/Base 冲突、无 AC 基础资料、legacy exact 不派生、H3C R1/R2 完整别名；
- `identity_index_missing/stale` 与 topology projection stale；
- 同批 revision、批量统计、空/全无效输入不访问 SQLite；
- MESH、Ground、Online/Vehicle MR、Wireless、Trackside、AC/Base 和报告消费者；
- shadow/diagnostics 异常不阻塞，删除附加字段可回滚；
- raw 事实、workbook、任务终态和数据库指纹不因只读查询改变。

本领域由 Change Impact Registry 判为 L3。实现修改前必须执行 Consumer Audit，
使用 `tests/test_ap_identity_consumer_architecture.py` 和受影响消费者契约作为
定向门；合并到最终 `main` 组合后按 Registry 重新运行消费者套件。真实设备、
真实局点、Electron GUI、正式报告和长时间运行缺口必须单独报告。
