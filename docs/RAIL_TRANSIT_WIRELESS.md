# 轨道交通无线业务模型

## 业务主线

NetConsole 的轨道交通无线能力不采用企业 WLAN 的“AP—客户端”模型。正式业务链路为：

```text
轨旁 FIT-AP 资源
  -> AC Mesh-Link 快照
  -> Online MR 现场采集与轻量预览
  -> Mesh 原始日志离线分析与正式报告
```

- FIT-AP 资源负责 AP 上线、离线、未认证、Mesh Radio 1/2、LLDP、接入端口、光衰和站点/区间资料；
- AC Mesh-Link 负责表达“车载 MR ↔ 轨旁 FIT-AP”的当前链路关系；
- Online MR 和 Agent 负责采集、fping/iPerf 联动及现场预览；
- 离线 Mesh 分析负责切换、RSSI、空口、短时建链、乒乓和正式报告。

轨道交通 FIT-AP 和 Mesh-Link Web 契约不提供客户端数量、终端数量或基于客户端数的筛选、汇总与判断。

## AC Mesh-Link 数据方向

现有 Qt 采集器在 AC 上执行 `display clock` 和 `display wlan mesh-link ap`，并复用 `H3CComwareV9VehicleMrMeshLinkParser`。一行 AC 输出的语义是：

```text
本地 AP/Local MAC = 轨旁 FIT-AP 及其 Mesh Radio
Peer Name/Peer MAC = 车载 MR
```

Web 对外 DTO 从车载 MR 视角命名为 `peer_ap_*`，但匹配事实仍来自 AC 输出中的本地 AP 字段。匹配顺序为：

1. Local MAC 精确匹配 FIT-AP 基础 MAC 或明确的 Mesh Radio BSSID；
2. Local AP Name 精确匹配 AP 名称；
3. 规范化名称唯一匹配；
4. 无匹配或多匹配时保留原始名称/MAC并返回 warning，不选择第一条、不猜测。

MR 先按 Peer Name 与设备管理名称精确匹配，再按唯一的列车号和 CT/CW 端匹配。AP 扩展信息只补充站点、区间、里程、方向、在线状态和光衰，不修改原始 Mesh-Link 事实。

## 5C-5 查询与 5C-5A 受控刷新边界

Web 入口为 `/ac-management/mesh-links`，Feature key 为 `web.ac_mesh_links`。数据源为当前局点：

```text
files/rail_transit/online_mr/parsed/vehicle_mr_online.sqlite
```

Query Service 使用 SQLite `mode=ro` 和 `PRAGMA query_only=ON`，不实例化会初始化 schema 的 `VehicleMrOnlineStore`。阶段 5C-5A 的唯一写入口只创建 `ac_mesh_link_refresh` Task；设备连接、固定白名单命令、raw 和快照写入均在 Worker 中完成。凭据不进入请求、Task payload、事件、metadata 或 raw。

快照新鲜度规则：

| 年龄 | 数据状态 | MR 状态规则 |
| --- | --- | --- |
| 不超过 30 秒 | `fresh` | 活动链路为在线；缺失/断开为离线 |
| 31～300 秒 | `recent` | 只显示历史/近期状态，不宣称当前在线 |
| 超过 300 秒 | `stale` | 标记数据过期，不宣称当前在线 |

只有 `fresh` 且链路状态属于活动状态时，才计入当前在线和活动链路。缺失字段显示“无数据”，不得从无关字段推测。

旧 AC Mesh-Link 快照没有对应原始回显时，`/raw-tail` 继续返回 `available=false`，不得改用车载侧 Online MR 日志冒充。5C-5A 新任务把完整 UTF-8 回显保存到 `files/rail_transit/ac_mesh_link/snapshots/<session_id>/raw/`，API 只返回局点内相对引用。失败 raw 转入受控 failure 目录，失败任务不覆盖最新成功快照。

Peer Name 缺失但 Peer MAC 存在时保留该链路，并仅在 Peer MAC 唯一匹配设备管理记录时关联车载 MR。只有明确 `Total 0` 或等价无链路提示才可生成空快照；仅有表头、空回显、命令错误和解析失败不等同于全部 MR 离线。

## API

```text
GET /api/ac-management/mesh-links/summary
GET /api/ac-management/mesh-links/current
GET /api/ac-management/mesh-links/mrs
GET /api/ac-management/mesh-links/offline-mrs
GET /api/ac-management/mesh-links/unmatched
GET /api/ac-management/mesh-links/mrs/{mr_id}
GET /api/ac-management/mesh-links/snapshots
GET /api/ac-management/mesh-links/snapshots/{snapshot_id}
GET /api/ac-management/mesh-links/raw-tail
POST /api/ac-management/mesh-links/refresh
```

`refresh` 是唯一 POST，仅接受 AC 标识和是否包含切换历史的布尔值。没有 PUT、PATCH、DELETE、任意命令、自动周期采集或 AC 配置操作。
