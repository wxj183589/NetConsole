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
- 地面无人值守在独立页面复用 AC/基础资料与 Online MR 生命周期，维护自己的运行、全车长 Ping、每日覆盖和归档状态，不改变人工页面 Session Store；
- 离线 Mesh 分析负责切换、RSSI、空口、短时建链、乒乓和正式报告。

轨道交通 FIT-AP 和 Mesh-Link Web 契约不提供客户端数量、终端数量或基于客户端数的筛选、汇总与判断。

## 轨旁 AP 接入交换机

轨旁 AP 业务通过 `TracksideSwitchAdapter` 隔离厂商差异，H3C 保留原有采集路径，ZTE ZXR10 使用独立只读 Adapter。ZTE 普通详情采集固定使用版本、接口、DOM、LLDP Brief 和 LLDP Entry 五条命令；不进入配置模式，不提供配置采集、配置下发、文件管理、CLI Ping 或 ZTE AC 能力。

ZTE C89E-4 V1.9.0 的固定五条命令已在 11 台现场设备上完成只读验证，证据状态为 `REAL_DEVICE_VERIFIED`；接口综合状态、介质语义和 LLDP Brief/Entry 均已按脱敏 fixture 回归。5960X-ES V2 及指定端口详情仍只基于 V2.00.20.03 文档样例，保持 `DOCUMENT_SAMPLE_ONLY`，不能描述为已完成全系列实机兼容。

厂商采样任务生成 `zte-adapter-sample-<device>-<timestamp>.zip`，固定包含 manifest、逐命令状态、版本/接口/DOM/LLDP raw 和会话元数据。Artifact 进入 `WebArtifactStore` 完整性校验，不保存 SSH 密码、enable 密码、Token、私钥或其他明文凭据。

第一阶段不会根据文档样例生成 AP 绑定。即使输入模拟的两端数据，ZTE 行也固定返回 `NOT_VERIFIED / REAL_DEVICE_SAMPLE_REQUIRED`，页面显示“尚未接入真实节点，无法计算光衰”；H3C 既有 LLDP/AP 关联和双向光衰规则不变。完整边界和阶段二清单见 [ZTE 轨旁交换机 Adapter](ZTE_TRACKSIDE_SWITCH_ADAPTER.md)。

## 5C-9 无线综合看板

Web 入口 `/rail-transit/wireless-dashboard` 通过薄聚合 Query Service 复用基础资料、AC/FIT-AP、Mesh-Link、在线列车通信、Online MR、Job Center、Agent Controller 缓存和 Mesh 离线分析。它只展示既有状态、告警、时效与详情跳转，不连接设备、不创建 Task、不控制 Agent、不修改数据库或 raw，也不新增任何无线质量阈值。详细契约见 [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md)。

## 车内通信检测

Web 入口 `/rail-transit/train-communication` 是 TC1/TC2 固定六节点拓扑状态页，只展示 MR、交换机、服务器、节点链路、VRRP 和跨 TC 通信。状态由 Python Service 返回；缺少明确关联或检测结果时分别显示“未配置”和“未检测”，不按名称、地址或前端规则猜测。

“开始检测”只复用现有车内通信诊断 Task，不启动 Online MR、持续 fping/iPerf 或轨旁采集。列车在线与 Mesh-Link 状态只作为辅助上下文，不限制用户按点表选择列车和启动检测；当前轨旁 AP、RSSI 和两侧收光由“列车在线情况”承载。详细契约见 [车内通信检测](TRAIN_COMMUNICATION_MONITORING.md)。

## 5C-8 Mesh 原始日志分析结果 Web 化

Web 入口 `/rail-transit/mesh-analysis` 只读展示既有离线 Mesh 结构化结果：来源会话、主/备链路、主链路区间、切换事件、RSSI、既有空口指标、短时建链、乒乓切换、AP 统计以及已生成报告。Feature key 为 `web.mesh_analysis`，详细契约见 [Mesh 分析 Web 页面](MESH_ANALYSIS_WEB.md)。

Query Service 直接以 SQLite `mode=ro + query_only` 打开来源对应的 `parsed/*.mesh.sqlite`，不会实例化会初始化或升级 schema 的旧 Repository。短时建链、同 AP 双射频和乒乓判断继续复用当前正式纯分析函数及来源参数快照；前端不重算主备、切换或异常。RSSI 空值保持 `null`，已有数值 `0` 不被擅自改写。

既有报告和原始来源通过不可逆 `artifact_id/source_id` 访问，不接受路径参数、不返回本机绝对路径。来源或报告缺失时明确显示，不自动重解析、不生成报告、不修改 raw、分析数据库或 Session metadata。

## 5C-6 基础资料边界

Web 入口 `/rail-transit/base-data` 复用当前局点 `devices.db`，不新增基础资料数据库。轨旁 AP 点位来自 `ap_extension_points`，列车和车载 MR 来自 `devices / device_groups`；FIT-AP、光衰、Mesh-Link 和 Online MR 只作为关联运行态，不写回基础资料。

`ap_extension_points` 同时保存 AP 点位和站点标题、设计起点等位置辅助行。因此 AP 列表只纳入具有正式名称、有效 MAC 或有效点位编号的记录；站点和区间仍从全部位置行派生。正式名称为空时可显示点位编号，但不得将点位编号伪装成正式 AP 名称。详细契约见 [轨道交通基础资料](RAIL_TRANSIT_BASE_DATA.md)。

车载 MR 名称继续保留设备表原文。`MR-CT` 固定表示 `CT / 1车厢端`，`MR-CW` 固定表示 `CW / 6车厢端`；这两个物理安装端位不表示当前行驶方向的头端或尾端。AP 和 MR 的 MAC 各自在本领域查重，不互相合并。

阶段 5C-6A 将正式资料、导入来源和 AC/Mesh-Link/Online MR 运行态分层。运行态只补充展示，不自动覆盖 AP 名称、MAC、站点、区间、里程或 MR 静态身份。合并预览只做精确匹配；冲突必须人工处理，当前 Web 不提供正式写入入口。

## AC Mesh-Link 数据方向

现有 AC Mesh-Link Application Service 在 AC 上执行 `display clock` 和 `display wlan mesh-link ap`，并复用 `H3CComwareV9VehicleMrMeshLinkParser`。一行 AC 输出的语义是：

```text
本地 AP/Local MAC = 轨旁 FIT-AP 及其 Mesh Radio
Peer Name/Peer MAC = 车载 MR
```

Web 对外 DTO 从车载 MR 视角命名为 `peer_ap_*`，但匹配事实仍来自 AC 输出中的本地 AP 字段。匹配顺序为：

1. Local MAC 精确匹配 FIT-AP 基础 MAC 或明确的 Mesh Radio BSSID；
2. Local AP Name 精确匹配 AP 名称；
3. 规范化名称唯一匹配；
4. 无匹配或多匹配时保留原始名称/MAC并返回 warning，不选择第一条、不猜测。

MR 先按 Peer Name 与设备管理名称精确匹配，再按唯一的列车号和 CT/CW 端匹配。AP 扩展信息只补充站点、区间、里程、方向和两侧收光，不修改原始 Mesh-Link 事实。公开 Mesh-Link 记录不再返回链路状态、信道、带宽、AP 在线状态和光衰状态旧字段；快照中的原始链路状态仅作内部新鲜度/在线计算事实，不构成兼容契约。

## 列车在线统一查询与受控刷新边界

唯一用户入口为 `/rail-transit/train-online`，页面和底层 Mesh-Link API 共用 Feature `web.rail_train_online`；旧 `web.ac_mesh_links` 页面 Feature 已删除。数据源仍为当前局点：

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

只有 `fresh` 且链路状态属于活动状态时，才计入当前在线和活动链路。列车页由 `VehicleMrOnlineQueryService` 组合现有 `AcMeshLinkQueryService`，每列车一行返回 CT/CW 两个物理端位；Vue 不重新匹配 AP/MR，也不判断双端、单端、离线或过期。缺失字段返回 `null` 并显示“—”。

公开列车状态固定为 `BOTH_ONLINE / ONE_SIDE_ONLINE / BOTH_OFFLINE / STALE / UNKNOWN`。端点状态固定为 `ONLINE / OFFLINE / STALE / UNKNOWN`，匹配状态固定为 `EXACT / NAME_NORMALIZED / MAC_MATCHED / UNMATCHED / UNKNOWN`。Canonical AP Identity 仍只用于 shadow/diagnostics，本轮没有接管生产匹配。

旧 AC Mesh-Link 快照没有对应原始回显时，`/raw-tail` 继续返回 `available=false`，不得改用车载侧 Online MR 日志冒充。5C-5A 新任务把完整 UTF-8 回显保存到 `files/rail_transit/ac_mesh_link/snapshots/<session_id>/raw/`，API 只返回局点内相对引用。失败 raw 转入受控 failure 目录，失败任务不覆盖最新成功快照。

Peer Name 缺失但 Peer MAC 存在时保留该链路，并仅在 Peer MAC 唯一匹配设备管理记录时关联车载 MR。只有明确 `Total 0` 或等价无链路提示才可生成空快照；仅有表头、空回显、命令错误和解析失败不等同于全部 MR 离线。

## API

```text
GET /api/rail-transit/train-online/trains
GET /api/rail-transit/train-online/trains/{train_id}
GET /api/rail-transit/train-online/trains/{train_id}/events
POST /api/rail-transit/train-online/refresh
POST /api/rail-transit/train-online/ap-mapping/refresh

# deprecated 底层查询/历史契约
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

正式列车页的 `refresh` 与 deprecated AC alias 都调用同一个 `AcMeshLinkRefreshApplicationService`，只接受 AC 标识和是否包含切换历史的布尔值。`刷新页面` 只重新读取缓存；`刷新在线状态` 创建或复用真实 `ac_mesh_link_refresh` Task；`刷新 AP 映射` 只重算现有映射，不连接设备。没有 PUT、PATCH、DELETE、任意命令、自动周期采集或 AC 配置操作。
