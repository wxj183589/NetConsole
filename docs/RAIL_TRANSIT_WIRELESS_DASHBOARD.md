# 轨道交通无线综合看板

## 定位

阶段 5C-9 在 `/rail-transit/wireless-dashboard` 增加轨道交通无线综合看板，Feature key 为 `web.rail_transit_wireless_dashboard`。它把已经存在的只读结果聚合为一个现场总览，不建立新的业务事实源：

```text
基础资料 / FIT-AP / 光衰 / AC Mesh-Link
        + Online MR / Job Center / Agent 缓存
        + Mesh 离线分析结果
        -> WirelessDashboardQueryService
        -> GET-only API
        -> Vue 综合看板
```

看板不连接 AC 或 Agent，不启动、停止或刷新任务，不读取任意命令，不修改 SQLite、Session metadata、raw、快照或分析结果。告警只转换现有服务已经给出的 `offline / stale / warning / critical / FAILED` 等状态，不增加 RSSI、丢包、带宽、光衰或切换阈值。

## 展示范围

- 概览：FIT-AP 在线/离线/未认证、光衰异常、列车/MR、MR 在线/离线/过期、活动采集、Agent、运行中任务、Mesh 分析会话和告警；
- 基础设施：AC/FIT-AP 汇总、光衰异常和最新 Mesh-Link；
- 列车状态：MR-CT（1车厢端）与 MR-CW（6车厢端）独立展示，复用车内通信检测的综合状态；
- 告警与时效：保留已有严重度、来源状态、更新时间和数据年龄；
- 最近活动：任务中心和 Online MR 会话；
- 离线分析：已有 Mesh 分析摘要和最近会话；
- Agent：仅显示 Controller 已缓存状态，不主动探测。

所有“详情”只跳转到现有页面。看板不复制 AC、Online MR、Agent 或 Mesh 分析的详情能力。

## API

以下接口全部为 GET-only：

```text
GET /api/rail-transit/wireless-dashboard
GET /api/rail-transit/wireless-dashboard/summary
GET /api/rail-transit/wireless-dashboard/infrastructure
GET /api/rail-transit/wireless-dashboard/trains
GET /api/rail-transit/wireless-dashboard/alerts
GET /api/rail-transit/wireless-dashboard/freshness
GET /api/rail-transit/wireless-dashboard/recent-operations
GET /api/rail-transit/wireless-dashboard/analysis
GET /api/rail-transit/wireless-dashboard/agents
```

Router 只调用 `WirelessDashboardQueryService`，不直接查询 SQLite 或文件。聚合服务再调用既有 Query Service，并以“局点 + 数据版本”保存 2 秒进程内快照缓存。缓存不落盘、不改变数据版本，也不是正式数据源。

## 刷新和失败处理

- 活动 Online MR 会话或运行中任务存在时，核心摘要、列车和最近活动每 2 秒刷新；否则每 10 秒；
- FIT-AP/光衰约 30 秒、Mesh-Link 约 5 秒、告警和时效约 5 秒、Agent 约 10 秒、Mesh 分析约 30 秒更新；
- 同类刷新不重入，页面隐藏或组件卸载后停止 timer；
- 连续失败三次后保留最后一次成功数据并降频至 30 秒；
- 任何来源缺失都显示其已有 `no_data / unknown / stale` 状态，不推测实时值。

## 当前边界

- AC Mesh-Link 的受控刷新仍只在原页面创建白名单 Task；综合看板没有刷新入口；
- 综合看板继续不提供 Online MR 控制；LOCAL/Agent 控制只允许从具名 Electron 业务入口调用同一 Application Service，并按 Feature 状态开放；
- Mesh 解析、导入、重建、报告和导出由永久 Job/Application Service 负责，Vue 只展示状态和触发受控动作；
- SNMP Center、通用 MIB/OID 平台和无线勘测已删除。
