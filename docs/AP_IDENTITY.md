# AP Identity

## 1. 当前定位

`src/netconsole/services/ap_identity/` 是局点级 AP 身份、MAC 别名和
H3C Radio 衍生索引的生产实现。它统一读取当前局点的基础资料、
AC/FIT-AP/Radio 数据和历史兼容缓存，将物理 AP、AP 基础 MAC、
Radio/BSSID/BBSSID、位置和来源证据分开保存。

2026-07-31 起，以下生产查询统一通过 `ApIdentityQueryService`：

- MR 原始 MESH PeerMac 匹配和解析结果回填；
- Online MR、Vehicle MR 和列车在线相关 AP 匹配；
- 无线扫描、BSSID 分析和轨旁信号位置快照；
- 基础资料、AC/FIT-AP 和轨旁 AP 业务的 MAC 搜索；
- AC Mesh-Link 查询和 AP Identity 数据质量问题。

普通查询只读取 `devices.db` 中已生成的统一索引，不连接 AC，不执行
SSH、SNMP 或采集，不要求 `ac_device_uuid`，也不在请求期间重建索引。
光衰更新、AC 深度采集和远程配置仍由 AC 业务服务控制，继续要求有效
AC 绑定。

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

## 4. 实体合并与冲突

索引构建器按 AP UUID、相同 MAC、序列号和唯一名称合并来源。有效身份
优先使用 AC 运行数据；AC 不存在或暂时没有该 AP 时，基础资料实体继续
有效。

AC 与基础资料 MAC 或名称不一致时：

- 有效 AP 名称、AP MAC 和实际 Radio/BSSID 使用 AC 数据；
- 基础资料原值保留在实体和冲突记录中；
- 写入 `AP_IDENTITY_AC_BASE_CONFLICT` 数据质量告警；
- MESH、搜索、页面和报告继续返回 AC 匹配结果，不因冲突变成
  `unresolved`；
- 同层存在多个不同物理 AP 候选时仍返回 `ambiguous`，不静默选择第一条。

## 5. 匹配优先级

`ApIdentityQueryService.resolve_mac()` 按层短路，只有当前层没有候选时
才进入下一层：

1. AC 实际 Radio MAC；
2. AC 实际 BSSID；
3. AC 实际 BBSSID；
4. AC FIT-AP AP MAC；
5. AC AP MAC 的 H3C 36 位前缀衍生；
6. 基础资料 AP MAC 的 H3C 36 位前缀衍生；
7. 基础资料 AP MAC 精确匹配；
8. 历史兼容 MAC 精确匹配；
9. AP 名称兼容匹配。

名称仅是最后兼容路径。位置、站点、区间和里程用于结果展示和诊断，
不用于在同层多实体之间强行消歧。

真实无 AC 示例：

```text
基础资料 AP MAC: 4873-97cc-e0e0
MESH PeerMac:    4873-97cc-e9af
匹配规则:        h3c_radio_block_36
来源:            base_data
```

AC 后续提供同一 Radio MAC 时，结果改用
`actual_radio_mac_exact`、`actual_bssid_exact` 或
`actual_bbssid_exact`，有效 AP 身份使用 AC 数据。

## 6. 持久化结构

统一索引位于每个局点的 `devices.db`：

- `ap_identity_entities`：物理 AP 的有效身份和各来源原值；
- `ap_identity_mac_aliases`：AP、Radio、BSSID 和兼容 MAC 别名；
- `ap_identity_h3c_prefixes`：AC 与基础资料 AP MAC 的 36 位前缀；
- `ap_identity_conflicts`：AC/Base 不一致及可审计上下文；
- `ap_identity_index_state`：revision、构建原因、来源计数和时间。

当前 schema 版本为 `2026.07.31.ap_identity_index_v1`。初始化是增量且
幂等的，不删除现有 AP、日志、规划或缓存数据。

## 7. 索引刷新边界

索引只在明确写事件后刷新：

- Backend 启动发现来源存在且 index revision 为 0；
- 基础资料导入应用、回滚、保存、删除或清空；
- AC FIT-AP 刷新、删除、metadata 导入或保存；
- 局点包在 staging 数据库发布前完成初始化和重建。

查询服务不得调用 `ensure_index()` 或 `rebuild_index()`。这保证搜索、
MESH 分析、历史报告和页面刷新都是只读操作，数据库指纹在普通 GET
请求期间保持不变。

## 8. 消费端契约

匹配结果保留以下关键证据：

- 查询 MAC 与统一显示值；
- `matched/unresolved/ambiguous`；
- 有效 AP 名称、MAC、站点、区间、点位和里程；
- 命中别名类型、来源、规则、置信度和 Radio ID；
- AC AP MAC、基础资料 AP MAC、基础资料记录 ID；
- 冲突状态和 `AP_IDENTITY_AC_BASE_CONFLICT`。

搜索 Radio/BSSID 或 H3C 衍生 MAC 时，结果返回对应物理 AP，并区分
“查询/命中 MAC”和“有效 AP MAC”。业务 DTO 可以按现有领域契约裁剪，
但不得重新实现 H3C 推导或维护第二套 MAC 索引。

## 9. 兼容与回滚边界

旧 `CanonicalApIdentity`/resolver 数据类和部分适配器仍保留给历史
诊断及精确兼容调用。生产 MESH、Vehicle、Wireless 和搜索入口不得
回退到各模块自行维护的 H3C 映射。

回滚统一索引接管时必须同时回滚消费者、写事件刷新和数据库 schema
消费者；不得仅删除索引表而保留生产查询引用。原始 MESH 日志、AC
资源、基础资料、历史缓存和正式报告都不是索引派生物，禁止随索引
回滚删除。
