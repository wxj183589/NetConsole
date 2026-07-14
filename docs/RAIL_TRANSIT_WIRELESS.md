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

## 5C-5 只读边界

Web 入口为 `/ac-management/mesh-links`，Feature key 为 `web.ac_mesh_links`。数据源为当前局点：

```text
files/rail_transit/online_mr/parsed/vehicle_mr_online.sqlite
```

Query Service 使用 SQLite `mode=ro` 和 `PRAGMA query_only=ON`，不实例化会初始化 schema 的 `VehicleMrOnlineStore`。页面只读取已落盘快照，不连接 AC、不执行命令、不创建任务，也不修改 `devices.db`、`tasks.db`、快照或 raw。

快照新鲜度规则：

| 年龄 | 数据状态 | MR 状态规则 |
| --- | --- | --- |
| 不超过 30 秒 | `fresh` | 活动链路为在线；缺失/断开为离线 |
| 31～300 秒 | `recent` | 只显示历史/近期状态，不宣称当前在线 |
| 超过 300 秒 | `stale` | 标记数据过期，不宣称当前在线 |

只有 `fresh` 且链路状态属于活动状态时，才计入当前在线和活动链路。缺失字段显示“无数据”，不得从无关字段推测。

现有 AC Mesh-Link 采集器只持久化结构化快照，没有保存对应原始回显。首版 `/raw-tail` 因此返回 `available=false` 和明确说明；不得改用车载侧 Online MR 日志冒充 AC 原始输出。后续若要保存 raw，应在采集任务中另行设计受控文件契约。

## GET-only API

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
```

没有 POST、PUT、PATCH 或 DELETE，也没有采集、刷新设备、启动、停止或任意命令接口。
