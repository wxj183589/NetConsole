# AP Identity 消费者审计

## 结论

统一范围是“观测 MAC 或物理 AP 查询条件 -> 物理 AP 身份”的解析段，采集、
筛选、告警、图表和报告规则仍由各业务模块负责。射频观测必须使用
`resolve_peer_mac()` / `resolve_peer_macs()`；物理 AP 查询必须使用
`resolve_ap_mac()` / `resolve_ap_macs()` / `search_aps()`，不得把物理 AP MAC
直接当作 Peer Radio 证据。

本轮完成统一批量契约、MESH 批量映射和地面无人值守旁路收口。其余直接
查询 Identity 表、旧 Resolver 或逐行解析入口保留为显式后续项，不能据此
宣称全部消费者已经完成接管。

## 消费者矩阵

| 模块 | 入口文件 | 输入 MAC 类型 | 当前 Resolver | 是否自建 alias | 是否直接查 Identity 表 | 是否持久化 revision | 是否支持 remap | 整改状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MESH 原始日志分析 | `src/netconsole/services/mesh_peer_mapping_service.py` | Peer / Radio MAC | `resolve_peer_macs(ap_role="trackside")` | 否 | 否 | 是，source/detail 保存批次 revision | 是，identity-only remap | 已完成；distinct Peer 单批解析并集合式写回 |
| 地面无人值守实时 Syslog | `src/netconsole/services/ground_unattended/ap_resolver.py`、`syslog_runtime.py` | WMESH Peer / Radio MAC | `resolve_peer_macs(ap_role="trackside")` | 否 | 否 | 是，写入 `parsed_details` | revision 变化后下一批更新缓存 | 已完成；移除 Base/AC/Alias 私有索引 |
| 地面无人值守历史查询 | `src/netconsole/services/ground_unattended/application_service.py` | 历史 Peer / Radio MAC | 页面 distinct 批量预加载 | 否 | 否 | 返回投影携带 revision，原始 NDJSON 不改写 | 读取时重投影 | 已完成；保持历史原始事实只读 |
| 无线扫描 / BSSID 工具 | `src/netconsole/services/network_tools/trackside_bssid_resolver.py` | BSSID | `resolve_peer_mac()` | 否 | 否 | 否 | 否 | 部分统一；待改正式批量接口和 revision |
| AC Mesh-Link | `src/netconsole/services/ac/mesh_link_query_service.py` | Peer Radio MAC | Query Service 单值 + 本地候选索引 | 是 | 是 | 否 | 否 | 待收口；删除直接 JOIN 和私有 `by_mac` |
| 车载 MR 实时收集 | `src/netconsole/services/vehicle_mr_online.py` | 当前 Peer / BSSID / AP MAC | Query Service 单值 + 遗留 H3C helper | 是 | 间接缓存键 | 未完整固定 | 否 | 待收口；按采样批次解析新 MAC |
| 车载 MR 历史分析 | `src/netconsole/services/rail_transit/online_mr_diagnosis_parser.py` | 历史 Peer / Radio MAC | `ApRadioMappingService` | 是 | 否 | 否 | 否 | 待收口；改 distinct 批量解析和身份投影 |
| 轨旁 AP 基础资料与搜索 | `src/netconsole/services/rail_transit/base_data_query_service.py` | AP / Radio / LLDP MAC、名称 | `search_aps()` + `resolve_mac()` | 否 | 是 | 部分返回 entity | 不适用 | 部分统一；物理查询改名并移除直接 JOIN |
| 轨旁 AP 业务 | `src/netconsole/services/rail_transit/trackside_ap_business_query_service.py` | 物理 AP / LLDP MAC | `search_aps()` + `resolve_mac()` | 否 | 否 | 否 | 不适用 | 部分统一；改 `resolve_ap_mac(s)` 并固定 revision |
| MESH 页面与报告 | `src/netconsole/services/rail_transit/mesh_analysis_query_service.py`、报告服务 | 已持久化 entity 投影 | 读取 MESH 持久化投影 | 否 | 只直读 index revision 判断陈旧 | 是 | 触发 MESH remap | 保留；revision 读取后续下沉 Query Service |
| FIT-AP / AC 搜索 | `src/netconsole/services/ac/query_service.py` | AP MAC / 名称 | `search_aps()` | 否 | 否 | 否 | 不适用 | 已使用统一搜索；详情按 entity 接口继续收敛 |

## 批量契约

`ApIdentityQueryService` 正式提供：

```python
resolve_peer_macs(macs, ap_role="trackside")
resolve_ap_macs(macs)
```

输入先规范化并去重，返回以 12 位紧凑 MAC 为键的 `ApIdentityMatch`。同一批
在一个只读事务中读取 index state、source revision 和 alias 行；健康检查只做
一次，SQL 次数随 distinct MAC 分块数量增长，不随原始事实行数增长。每个结果
携带本批 `identity_revision`，`matched/unresolved/ambiguous` 均不丢失。

## 门禁与后续顺序

`tests/test_ap_identity_consumer_architecture.py` 禁止 Ground 再次建立私有 MAC
索引或导入 H3C 推导，并禁止白名单外业务 Service 直接引用 Identity 表或旧
`ApRadioMappingService`。当前白名单就是上表的待整改清单；每完成一个消费者
收口，必须同步删除对应白名单项。

后续顺序保持为：车载 MR 实时 -> 车载 MR 历史 -> 无线扫描 -> AC Mesh-Link ->
轨旁 AP 物理查询与报告 revision 下沉。每次接管都要保留原始 MAC、批次 revision、
歧义状态和可回滚的单模块边界。
