# MR/MESH AP Identity 生产接管记录

## 1. 状态

本文原先记录 MR/MESH AP Identity shadow 评估。2026-07-31 完成统一
局点索引接管后，shadow-only 结论已失效；当前生产规则以
[AP Identity](AP_IDENTITY.md) 和代码为准。

统一链路为：

```text
基础资料 + AC FIT-AP/Radio + 历史兼容数据
                    ↓
devices.db AP Identity 实体、MAC 别名、H3C 前缀、冲突
                    ↓
ApIdentityQueryService
                    ↓
离线 MESH / Online MR / Vehicle MR / Wireless / 搜索 / 报告
```

## 2. 生产边界

`peer_mac`、`peer_radio_mac`、Radio MAC、BSSID 和 BBSSID 仍是空口
观测，不会写回为物理 AP MAC。统一查询通过实际 Radio/BSSID、AP MAC
或 H3C 36 位前缀找到物理 AP，并返回命中规则和来源。

无 AC 时，基础资料 AP MAC 可以独立生成 H3C 前缀索引。MESH 导入、
历史重算、RSSI、主链路、切换事件、图表和报告不得要求 AC 绑定，也
不得触发 AC 网络访问。

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

1. AC 实际 Radio/BSSID/BBSSID；
2. AC FIT-AP AP MAC；
3. AC AP MAC 的 H3C 衍生；
4. 基础资料 AP MAC 的 H3C 衍生；
5. 基础资料 AP MAC；
6. legacy exact；
7. 名称兼容。

同一优先级命中多个物理 AP 时返回 `ambiguous`。较低优先级候选不会
推翻已经唯一命中的高优先级结果。名称和位置不能静默消除 MAC 歧义。

## 5. 原始数据与派生数据

原始 MESH 日志、raw line、文件偏移、采集会话和 source file ID 始终
是证据源，统一索引不会改写它们。detail DB 中的 mapping/cache、
Online MR parsed DB 和报告字段是可重算的派生结果。

普通解析和查询只读取统一索引。来源变化后由基础资料写入、AC 刷新、
Backend 首次启动或局点包 staging 导入负责重建；不能把“刷新 AC”作为
MESH 匹配的人工前置步骤。

## 6. 验收基线

生产接管至少覆盖：

- 无 AC、仅基础资料的 AP0208 H3C PeerMac 匹配；
- 空 FIT-AP 表和缺少 `ac_device_uuid` 时保持可匹配；
- AC 实际 Radio/BSSID 覆盖基础资料衍生结果；
- AC 暂时消失后基础资料匹配继续有效；
- 相同 MAC 合并为一个物理 AP；
- AC/Base 冲突使用 AC 并产生非阻断数据质量告警；
- Radio MAC 搜索反查物理 AP；
- legacy exact 不生成 H3C 前缀；
- MESH、Vehicle 和 Wireless 查询不修改数据库、不访问网络；
- 匹配结果可进入页面和报告，且不会触发光衰采集。

相关回归主要位于 `tests/test_ap_identity_index.py`、
`tests/test_mesh_log_analysis.py`、`tests/test_vehicle_mr_online.py`、
`tests/test_wireless_scan.py` 和各 Web 查询测试。
