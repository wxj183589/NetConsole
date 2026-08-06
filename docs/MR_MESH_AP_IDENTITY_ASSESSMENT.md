# MR/MESH AP Identity 生产接管记录

## 1. 状态

本文原先记录 MR/MESH AP Identity shadow 评估。2026-07-31 完成统一
局点索引接管后，shadow-only 结论已失效；当前生产规则以
[AP Identity](AP_IDENTITY.md) 和代码为准。

统一链路为：

```text
基础资料 + AC FIT-AP/Radio + 历史兼容数据
                    ↓
devices.db AP Identity 实体、精确 MAC/Radio 别名、冲突
                    ↓
ApIdentityQueryService
                    ↓
离线 MESH / Online MR / Vehicle MR / Wireless / 搜索 / 报告
```

## 2. 生产边界

`peer_mac`、`peer_radio_mac`、Radio MAC、BSSID 和 BBSSID 仍是空口
观测，不会写回为物理 AP MAC。MESH Peer 查询只通过实际 Radio、
BSSID/BBSSID 或公共 H3C R1/R2 函数生成的完整 48 位精确 alias 找到
物理 AP，并返回命中规则和来源。

基础资料 AP MAC 可以在索引构建时生成完整 R1/R2 alias，但生产查询
不读取 `ap_identity_h3c_prefixes`，也不按名称、位置、站点或 AP 基础
MAC回退。MESH 导入、历史重算、RSSI、主链路、切换事件、图表和报告
不得要求 AC 绑定，也不得触发 AC 网络访问。

AC 存在时，实际 Radio/BSSID 和 FIT-AP 数据优先。AC 与基础资料冲突
不会阻断分析；有效身份使用 AC，基础资料原值和冲突记录继续保留。

## 3. 已接管入口

- `MeshPeerMappingService` 和 `TracksideApBssidResolver` 生产路径；
- 离线 MR/MESH 解析、mapping/cache 回填和位置快照；
- Online MR 与 Vehicle MR AP 解析；
- Wireless Scan 的 BSSID 到物理 AP 映射；
- AC Mesh-Link、列车在线及相关筛选；
- 基础资料、AC/FIT-AP、轨旁 AP 业务的 MAC 反查；
- MESH 页面、分析结果和报告所消费的 AP 名称、MAC 与位置。

历史 resolver 的 list 构造方式只保留精确匹配测试兼容，不再自行生成
H3C Radio MAC。`ap_entities`、`ac_fit_ap_optical` 和
`trackside_ap_view_cache` 只作为最低优先级精确兼容源。

## 4. 匹配和歧义

匹配优先级固定为：

1. AC 实际 Radio MAC；
2. AC 实际 BSSID；
3. AC 实际 BBSSID；
4. H3C R1/R2 完整精确衍生 alias；
5. 没有候选时返回 `unresolved`。

同一优先级命中多个物理 AP 时返回 `ambiguous`。`peer_name` 只保留
展示和诊断用途，不能把 `unresolved` 变成 `matched`。AP 基础 MAC、
36/40 位前缀、MAC 范围、位置和站点均不能参与 MESH Peer 生产回退。

## 5. 原始数据与派生数据

原始 MESH 日志、raw line、文件偏移、采集会话和 source file ID 始终
是证据源，统一索引不会改写它们。detail DB 中的 mapping/cache、
Online MR parsed DB 和报告字段是可重算的派生结果。

页面、图表、主链路、链路 DTO 和导出分别携带原始 Peer、解析 AP 名称、
物理 AP MAC及身份状态/来源/规则/置信度/原因。没有精确证据时仅保留
原始 Peer，解析身份和位置字段为空。

普通解析和查询只读取统一索引。来源变化后由基础资料写入、AC 刷新、
Backend 首次启动或局点包 staging 导入负责重建；不能把“刷新 AC”作为
MESH 匹配的人工前置步骤。

## 6. 验收基线

生产接管至少覆盖：

- 无 AC、仅基础资料且公共 R1/R2 函数生成完整 alias 时的精确匹配；
- 空 FIT-AP 表和缺少 `ac_device_uuid` 时保持可匹配；
- AC 实际 Radio/BSSID 覆盖基础资料衍生结果；
- AC 暂时消失后基础资料匹配继续有效；
- 相同 MAC 合并为一个物理 AP；
- 同名不同 MAC 不合并；
- AC/Base 冲突使用 AC 并产生非阻断数据质量告警；
- Radio MAC 搜索反查物理 AP；
- `642f-c778-ef5f` 在只有 `64:2f:c7:78:ed:a0 / AP2011` 且无完整
  Radio alias 时必须返回 `unresolved`；
- `peer_name` 相同仍不得回退匹配；
- legacy exact 不生成 H3C alias；
- MESH、Vehicle 和 Wireless 查询不修改数据库、不访问网络；
- 匹配结果可进入页面和报告，且不会触发光衰采集。

相关回归主要位于 `tests/test_ap_identity_index.py`、
`tests/test_mesh_log_analysis.py`、`tests/test_vehicle_mr_online.py`、
`tests/test_wireless_scan.py` 和各 Web 查询测试。

## 7. 绍兴 1 号线资料不完整时的验收口径

绍兴 1 号线当前没有 FIT-AP 资源，轨旁 AP 基础资料也不完整。日志中的
Peer Radio MAC 可能在基础资料中找不到对应 AP，基础资料 AP 也可能缺少
合法物理 MAC，或因重复 MAC、格式异常、Alias 冲突而无法唯一派生身份。

因此，绍兴的 `unresolved` 和 `ambiguous` 不应被当作解析失败：

- 基础资料存在唯一合法物理 MAC 且 Alias 唯一时，必须 `matched`，并投影 AP、站点、区间、里程和方向；
- 基础资料无对应 AP、物理 MAC 缺失/非法时，必须保持 `unresolved`，并给出 `base_ap_not_found`、`base_ap_mac_missing` 或等价原因；
- Alias 指向多个 AP 时必须保持 `ambiguous`，输出候选，不得按名称、站点、MAC 前缀或记录顺序消歧；
- 同一日志允许同时存在 `matched`、`unresolved` 和 `ambiguous`，部分未匹配是当前资料条件下的正常结果。

核心指标定义为：

```text
eligible_match_count = 基础资料中存在唯一、合法、可派生 Alias 的 Peer 数
eligible_matched_count = 上述范围内实际匹配成功数
```

绍兴验收要求 `eligible_matched_count == eligible_match_count`，并要求可匹配范围内的异常漏匹配数为 0；不要求 `matched_count == distinct_peer_count`。

## 8. 三局点真实数据回归记录

回归使用现有局点数据库、MESH parsed 数据和原始日志，保留原始日志 SHA-256 作为证据索引；查询过程只读，不修改现场数据。选定会话的 Peer Radio MAC 统计如下：

| 局点 | Peer 总数 | 可唯一匹配数 | 实际匹配数 | 正常未匹配数 | 异常漏匹配数 | Ambiguous | 有站点数 | 主要来源 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 宁波 12 号线 | 1581 | 1581 | 1581 | 0 | 0 | 0 | 1568 | LLDP/FIT-AP |
| 宁波 6 号线 | 51 | 51 | 51 | 0 | 0 | 0 | 51 | LLDP + Base 补充 |
| 绍兴 1 号线 | 454 | 290 | 290 | 164 | 0 | 0 | 290 | Base Data |

绍兴 1 号线的 164 条 `unresolved` 属于基础资料覆盖不足的正常结果；本次硬门槛是证据充分的 290 条全部匹配，不能通过模糊匹配把 454 条强行变成 matched。

三份原始日志证据 SHA-256：

- 宁波 12 号线：`ef4046a9335c0e57810ef0d1553266931ecf0c9f406e8ca407077e0596ee7d6c`
- 宁波 6 号线：`019580a5e8dbe9c7467296d7506d0a70f558c36c21ddc9ab86feb18dcd1707ae`
- 绍兴 1 号线：`efc17fff68aeec62b5aec080cded00ea8ab9b661812566566d8835f8f614dde7`

端到端只读回归覆盖主链建链顺序、链路明细、RSSI、Channel Busy、速率、计数器、切换事件、动态曲线和 AP 统计。大窗口图表继续遵守 16 MiB 响应上限，采用真实时间窗口验证，不放宽安全限制。
