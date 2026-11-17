# SQL Phase 3 AC / FIT-AP / Mesh-Link / ARP 审计报告

日期：2026-11-18
基线：`173fa46548eff5e0b9a65d75088bc09bf3cb0eda`
分支：`codex-A/sql-phase3-ac-mesh-arp-20261118`

## 审计矩阵

| 模块       | 查询入口                                   | 审计结论             | N+1 证据                                                                              | Site/实时性结论                                   |
|------------|--------------------------------------------|----------------------|---------------------------------------------------------------------------------------|---------------------------------------------------|
| AC/FIT-AP  | `list_ap_details_for_macs`、列表页详情补充 | 已完成优化           | radio/details 逐 AP 连接已改为批量读取                                                | 仍按 AC/AP 复合身份过滤，动态 optical/LLDP 未缓存 |
| AC/FIT-AP  | 全量详情、导出                             | 已完成优化           | 全量 radio/details 读取改为一批或受 SQLite 参数上限约束的分批                         | 保留原 AC 归属和导出字段                          |
| Mesh-Link  | `_link_rows`、当前 Link/MR 列表            | 已完成优化           | identity batch 的 canonical/vehicle MAC key 对齐，消除逐 Link `resolve_peer_mac` 回退 | 精确 Local/Peer 匹配和 freshness 不变             |
| Mesh-Link  | `_history_links`                           | 已完成优化           | 页面内 snapshot/link 先批量加载，再复用同一解析上下文                                 | 历史分页、时间范围和 `historical` 状态不变        |
| Ground ARP | `build_identity_observation_projection`    | 已审计，既有批量实现 | MR/IP/最新完整 collection 在一个只读连接内读取                                        | 保留完整/部分/失败快照和冲突语义                  |

## 关键审计项

- 写入方未改变；本轮只改读取路径和测试/画像脚本。
- Repository 没有反向依赖 Service；批量 radio API 仍位于 `AcRepository`。
- 未引入全局缓存；Mesh AP index 继续使用已有 revision/path signature，动态链路和 ARP 仍按请求读取。
- 未修改 Schema、索引、ARP 写入语义、H3C Radio MAC 推导、Site 隔离规则或公开 Repository 旧接口。
- `EXPLAIN QUERY PLAN` 显示 AC/FIT-AP 和 ARP 使用现有复合索引；Mesh snapshot link 仍为表扫描，本轮没有未经必要性证明而新增索引。

## 审计状态

`PASS_SQL_PHASE3`
