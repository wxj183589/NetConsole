# 在线列车车内通信检测

点表、固定拓扑、VRRP、跨 TC 和迁移事实源的详细说明见 [专题文档目录](rail-transit/train-communication/README.md)。

## 定位

`/rail-transit/train-communication` 是固定车载拓扑状态页，不是无线综合看板。页面正式名称为“在线列车车内通信检测”，只展示当前在线列车选择、TC1/TC2 两端固定六节点、节点和链路状态、VRRP、跨 TC 通信、刷新与“立即检测”。

固定节点为：

```text
TC1-MR -> TC1-SW -> TC1-SRV
             |
          VRRP / 跨 TC
             |
TC2-MR -> TC2-SW -> TC2-SRV
```

轨旁 AP、RSSI、fping、丢包、iPerf、光衰、Online MR、Agent 和原始 Mesh-Link 明细属于各自独立页面，不在本页执行、采集或展示。列车可选状态只读取 `VehicleMrOnlineQueryService` 已计算的正式在线结果，不使用正在运行的 Online MR Session 充当在线状态，也不在前端硬编码列车。

## 在线列车来源

`GET /api/rail-transit/train-communication/online` 是本页下拉框的正式来源。该接口复用列车在线页的当前状态，只有 `BOTH_ONLINE` 和 `ONE_SIDE_ONLINE` 且至少一个在线端 `data_status == FRESH` 的列车可进入检测页；`BOTH_OFFLINE`、`STALE` 和 `UNKNOWN` 不作为当前在线列车返回。

返回行包含 `canonical_train_id`、`display_name`、CT/TC 在线状态、CT/TC MR 身份、更新时间和在线原因。`active_sessions` 仍可展示当前是否存在采集任务，但不参与在线列车判定。

列车身份统一归一到 `train:<两位车号>`，例如 `列车01`、`01车`、`01`、`1`、`train-01`、`train:01` 和 `LC01` 均匹配同一列车。拓扑查询、点表校验和最新诊断结果查询均使用同一规则。

## 状态契约

Python `TrainCommunicationQueryService` 返回稳定状态，Vue 只映射中文和语义颜色：

| 状态 | 页面文本 | 含义 |
| --- | --- | --- |
| `normal` | 正常 | 已有事实明确正常 |
| `abnormal` | 异常 | 已有事实明确异常 |
| `checking` | 检测中 | 车内通信检测任务运行中 |
| `stale` | 数据过期 | 最近事实已经过期 |
| `not_detected` | 未检测 | 已配置但没有可用检测结果 |
| `not_configured` | 未配置 | 当前基础资料未建立对应节点关联 |

缺失值不能显示为 `unknown`、`no_data`、`-` 或数值 `0`。当前基础资料能够明确关联 CT/TC 车载 MR；交换机、服务器、VRRP 和跨端检测没有明确事实时，必须返回“未配置”或“未检测”，不得按名称、地址或前端规则猜测。

## 检测任务

“立即检测”复用现有 `RailTransitWebApplicationService.start_car_network_diagnostic()` 和 `car_network_diagnostic` Task：

- Router 只校验 Feature、局点和业务 ID，再调用 Application Service；
- Application Service 提交任务前再次复核正式在线状态，列车离线或数据过期时返回 409；
- 任务参数保存 `canonical_train_id`、车号、显示名、CT/TC MR、点表 revision、在线快照时间和在线状态；
- 页面轮询现有任务状态，终态后重新读取拓扑；
- 页面卸载或切换列车时清理轮询，不停止后台任务；
- 本入口不启动 Online MR、不启动持续 fping/iPerf、不采集轨旁 AP，也不接受命令、凭据或路径。

## 点表闭环

点表仍是拓扑和检测对象的唯一配置来源，存储路径为当前局点 `car_network/parsed/point_table.json`。保存任务必须原子替换文件并重新读取 revision 后才返回成功。

点表 Dialog 在当前列车无配置时显示六节点缺失清单，可生成当前列车六节点预览。生成结果只是编辑区预览，只有用户确认保存并收到 `saved` 事件后，父页面才刷新在线列车、当前拓扑和检测启动条件。

## API

```text
GET  /api/rail-transit/train-communication/summary
GET  /api/rail-transit/train-communication/trains
GET  /api/rail-transit/train-communication/online
GET  /api/rail-transit/train-communication/trains/{train_id}/topology
POST /api/rail-transit/train-communication/trains/{train_id}/diagnostics
GET  /api/rail-transit/train-communication/diagnostics/{task_id}
POST /api/rail-transit/train-communication/diagnostics/{task_id}/cancel
POST /api/rail-transit/train-communication/diagnostics/recover
```

`summary` 提供页面摘要，`online` 提供当前可检测列车，`trains` 保留为通用通信聚合列表。既有 MR 聚合查询接口继续供其他独立页面或兼容调用使用，但不再驱动本页下拉框。

## 刷新与导航

- 手工刷新同时重新读取正式在线列车和当前拓扑；
- 自动刷新可关闭，或设置为 10、30、60 秒；
- 同一页面只维护一个自动刷新定时器和一个检测任务轮询定时器；
- 点击已有 `device_id` 的节点跳转到 `/devices/{device_id}`，复用设备详情；未配置节点不创建虚假详情；
- 页面卸载时清理全部定时器。

## 验收边界

自动测试覆盖固定六节点、状态映射、空状态、API DTO、任务路由和定时器清理。交换机/服务器拓扑关联、VRRP、跨 TC 实际检测及真实设备通信仍需点表事实源和现场验收；完成前不得把“未配置/未检测”提升为正常。
