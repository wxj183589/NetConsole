# AP Identity

## 1. 当前定位

`src/netconsole/services/ap_identity/` 是局点级 AP 身份、MAC 别名和
H3C Radio 衍生索引的生产实现。它统一读取当前局点的基础资料、
AC/FIT-AP/Radio 数据和历史兼容缓存，将物理 AP、AP 基础 MAC、
Radio/BSSID/BBSSID、位置和来源证据分开保存。

生产消费者按 [AP Identity 消费者审计](AP_IDENTITY_CONSUMER_AUDIT.md)
分阶段接管。当前已完成的生产路径是：

- MR 原始 MESH distinct Peer 的批量匹配、持久化投影和 identity-only remap；
- 地面无人值守实时与历史 WMESH Peer 的批量匹配和 revision 缓存；
- AC/FIT-AP 与轨旁 AP 搜索的统一查询入口；
- 部分 Online MR、Vehicle MR、无线扫描和轨旁业务单值查询。

AC Mesh-Link、车载 MR 历史分析及基础资料的直接 Identity JOIN 等遗留入口
仍在审计白名单内，不能视为已经完成统一。新增消费者不得复制这些遗留实现。

普通查询只读取 `devices.db` 中已生成的统一索引，不连接 AC，不执行
SSH、SNMP 或采集，不要求 `ac_device_uuid`，也不在请求期间重建索引。
光衰更新、AC 深度采集和远程配置仍由 AC 业务服务控制，继续要求有效
AC 绑定。

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

当前 schema 版本为 `2026.08.01.ap_identity_and_trackside_ap_location`。初始化是增量且
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

Backend 启动只保留缺失或过期索引的兼容性收口；正常来源写入不会依赖
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
`identity_index_stale`。来源写任务在独立短事务内构建并原子替换实体、
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

例如离线物理 AP `bc5a-3457-b5e0` 的合法 H3C Radio 2 alias
`bc5a-3457-b5ff` 仍通过完整 MAC 等值解析。来源 revision 改变后继续复用
现有 identity-only remap：更新 distinct Peer 的身份投影，不重新解析或
修改 raw MESH 日志。

未匹配原因按事实区分为 `invalid_peer_mac`、`identity_index_missing`、
`identity_index_stale`、`exact_alias_not_collected`、
`exact_alias_not_found`、`duplicate_exact_alias`、
`physical_ap_missing` 和 `station_topology_missing`，页面和报告不得把这些
原因重新折叠成无法诊断的单一“未关联”。

地面无人值守不再读取基础资料和 AC 明细后自行建立 AP/Radio/Alias 字典。
历史页先对当前页观测 MAC 去重并批量解析；实时 Receiver 只缓存统一查询结果，
Identity revision 变化后清空缓存并在下一批解析。实时事件的既有
`parsed_details` 保存 entity、revision、状态、来源和原因；历史 NDJSON 保持
只读，只在返回投影中补充当前身份。

## 9. 兼容与回滚边界

旧 `CanonicalApIdentity`/resolver 数据类和部分适配器仍保留给历史
诊断及精确兼容调用。生产 MESH、Vehicle、Wireless 和搜索入口不得
回退到各模块自行维护的 H3C 映射。

回滚统一索引接管时必须同时回滚消费者、写事件刷新和数据库 schema
消费者；不得仅删除索引表而保留生产查询引用。原始 MESH 日志、AC
资源、基础资料、历史缓存和正式报告都不是索引派生物，禁止随索引
回滚删除。
