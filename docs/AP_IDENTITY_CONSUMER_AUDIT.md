# AP Identity 消费者审计

## 结论

统一范围是“观测 MAC 或物理 AP 查询条件 -> 物理 AP 身份”的解析段，采集、
筛选、告警、图表和报告规则仍由各业务模块负责。射频观测必须使用
`resolve_peer_mac()` / `resolve_peer_macs()`；物理 AP 查询必须使用
`resolve_ap_mac()` / `resolve_ap_macs()` / `search_aps()`，不得把物理 AP MAC
直接当作 Peer Radio 证据。

第一阶段状态已经明确冻结：

- AP Identity 批量查询、统计元数据和固定 revision 快照基础设施已完成；
- MESH distinct Peer 批量映射和 identity-only remap 已统一；
- Ground unattended 实时与历史 Peer 解析已统一。

其余直接查询 Identity 表、旧 Resolver 或逐行解析入口保留为显式后续项，
不能据此宣称全部消费者已经完成接管。

## 消费者矩阵

| 模块 | 当前入口 | 输入 MAC 语义 | 统一 Query 使用 | 私有 alias | 直查 Identity 表 | revision 持久化 | identity-only remap | 风险 | 阶段 / 建议批次 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MESH 原始日志分析 | `src/netconsole/services/mesh_peer_mapping_service.py` | Peer / Radio MAC | `resolve_peer_macs(ap_role="trackside")` | 否 | 否 | 是，source/detail 保存批次 revision | 是 | 中 | 第一阶段 / 已完成 | distinct Peer 单批解析并集合式写回 |
| 地面无人值守实时 Syslog | `src/netconsole/services/ground_unattended/ap_resolver.py`、`syslog_runtime.py` | WMESH Peer / Radio MAC | `resolve_peer_macs(ap_role="trackside")` | 否 | 否 | 是，写入 `parsed_details` | revision 变化后下一批更新缓存 | 高 | 第一阶段 / 已完成 | 已移除 Base/AC/Alias 私有索引 |
| 地面无人值守历史查询 | `src/netconsole/services/ground_unattended/application_service.py` | 历史 Peer / Radio MAC | distinct 批量预加载 | 否 | 否 | 返回投影携带 revision，原始 NDJSON 不改写 | 读取时重投影 | 中 | 第一阶段 / 已完成 | 保持历史原始事实只读 |
| 车载 MR 实时收集 | `src/netconsole/services/vehicle_mr_online.py` | 当前 Peer / BSSID / AP MAC | 单值 Query + 遗留 H3C helper | 是 | 间接缓存键 | 未完整固定 | 否 | 高 | 第二阶段 / P0 | 按采样批次解析新 distinct MAC |
| 车载 MR 历史分析 | `src/netconsole/services/rail_transit/online_mr_diagnosis_parser.py` | 历史 Peer / Radio MAC | 否，使用 `ApRadioMappingService` | 是 | 否 | 否 | 否 | 高 | 第二阶段 / P0 | 改 distinct 批量解析和身份投影 |
| 无线扫描 / BSSID 工具 | `src/netconsole/services/network_tools/trackside_bssid_resolver.py` | BSSID / Radio 观测 | 单值 `resolve_peer_mac()` | 否 | 否 | 否 | 否 | 高 | 第二阶段 / P0 | 改正式批量接口并固定 revision |
| AC Mesh-Link | `src/netconsole/services/ac/mesh_link_query_service.py` | Peer Radio MAC | 单值 Query + 本地候选索引 | 是 | 是 | 否 | 否 | 中 | 第二阶段 / P1 | 删除直接 JOIN 和私有 `by_mac` |
| 轨旁 AP 基础资料与搜索 | `src/netconsole/services/rail_transit/base_data_query_service.py` | 物理 AP / Radio / LLDP MAC、名称 | `search_aps()` + 兼容 `resolve_mac()` | 否 | 是 | 部分返回 entity | 不适用 | 中 | 第二阶段 / P1 | 改显式 `resolve_ap_mac(s)` 并移除直接 JOIN |
| 轨旁 AP 业务 | `src/netconsole/services/rail_transit/trackside_ap_business_query_service.py` | 物理 AP / LLDP MAC | `search_aps()` + 兼容 `resolve_mac()` | 否 | 否 | 否 | 不适用 | 中 | 第二阶段 / P1 | 物理查询显式化并固定 revision |
| 报告与导出读取路径 | `src/netconsole/services/rail_transit/mesh_analysis_query_service.py`、MESH/Online MR/轨旁报告服务 | 已持久化 identity 投影及 AP/Peer 展示字段 | 主要读取持久化投影 | 否 | 部分读取 index revision | MESH 已保存，其余不统一 | MESH 可触发 remap | 中 | 第二阶段 / P1 | 下沉 revision 判断，保持 workbook 契约不变 |
| 设备管理与 LLDP topology binding | 设备事实、LLDP 与轨旁绑定服务 | 物理设备 / Chassis / 邻居 MAC | 未统一 | 存在领域索引 | 部分 | 否 | 不适用 | 中 | 第二阶段 / P2 | 只统一身份解析段，拓扑关系仍由本领域负责 |
| FIT-AP / AC 搜索 | `src/netconsole/services/ac/query_service.py` | AP MAC / 名称 | `search_aps()` | 否 | 否 | 否 | 不适用 | 低 | 已有入口 / 持续收敛 | 已使用统一搜索；详情按 entity 接口继续收敛 |

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

返回对象为 `ApIdentityBatchResult`，同时提供 `revision`、`index_status`、
`requested_count`、`normalized_count`、`distinct_count`、三类结果计数、
`invalid_count` 和 `matches`。空输入或全无效输入不查询 SQLite；同一 MAC 的
不同格式计入 normalized 数量但只形成一个 distinct 查询。

## 门禁与后续顺序

`tests/test_ap_identity_consumer_architecture.py` 禁止 Ground 再次建立私有 MAC
索引或导入 H3C 推导，并禁止白名单外业务 Service 直接引用 Identity 表或旧
`ApRadioMappingService`。当前白名单就是上表的待整改清单；每完成一个消费者
收口，必须同步删除对应白名单项。

第二阶段建议使用独立分支 `codex/ap-identity-consumer-consolidation-phase2`，
不在第一阶段已合并分支继续开发。优先顺序为：P0 车载 MR 实时、车载 MR 历史、
无线扫描；P1 AC Mesh-Link、轨旁 AP 业务与搜索、报告和导出读取路径；P2 设备
管理与 LLDP topology binding。每次接管都要保留原始 MAC、批次 revision、
歧义状态和可回滚的单模块边界。
