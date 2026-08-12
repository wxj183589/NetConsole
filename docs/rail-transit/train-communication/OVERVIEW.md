# 车内通信检测

点表、固定拓扑、VRRP 静态配置、跨 TC 和迁移事实源的详细说明见 [专题文档目录](./README.md)。

## 定位

`/rail-transit/train-communication` 是固定车载拓扑状态页，不是无线综合看板。页面正式名称为“车内通信检测”，展示当前局点全部已登记列车、TC1/TC2 两端固定六节点、节点和链路状态、VRRP 虚拟 IP 静态配置、跨 TC 通信、刷新与“开始检测”。

固定节点为：

```text
TC1-MR -> TC1-SW -> TC1-SRV
             |
       静态拓扑连接
             |
TC2-MR -> TC2-SW -> TC2-SRV
```

轨旁 AP、RSSI、持续 fping/iPerf、光衰、Online MR、Agent 和原始 Mesh-Link 明细属于各自独立页面，不在本页执行或采集。列车在线状态只读取 `VehicleMrOnlineQueryService` 已计算的辅助结果，不使用正在运行的 Online MR Session 充当在线状态，也不在前端硬编码列车。

## 列车来源与在线辅助状态

本页使用 `GET /api/rail-transit/train-communication/trains`。Query Service 按以下来源合并、统一身份去重并自然排序：

1. 轨道交通基础资料中的列车；
2. 车内通信点表中的列车；
3. 已配置车载 MR 所属列车。

`GET /api/rail-transit/train-communication/online` 继续供“列车在线情况”等需要在线过滤的页面使用，不再驱动车内通信检测页的列车准入。

`trains` 返回行可附带 `canonical_train_id`、`display_name`、CT/TC 在线状态、CT/TC MR 身份、更新时间和在线原因；没有快照时保持未知。双端在线、单端在线、当前离线、数据过期和在线状态未知都只显示为小型辅助标签，不禁用选择或检测。

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

缺失值不能显示为 `unknown`、`no_data`、`-` 或数值 `0`。当前基础资料能够明确关联 CT/TC 车载 MR；交换机、服务器和跨端检测没有明确事实时，必须返回“未配置”或“未检测”，不得按名称、地址或前端规则猜测。VRRP 没有正式状态检测来源，拓扑只在 `vrrp_ip` 有值时展示虚拟 IP，不展示状态、主端、消息或占位文字。

## 检测任务

“开始检测”复用现有 `RailTransitWebApplicationService.start_car_network_diagnostic()` 和 `car_network_diagnostic` Task：

- Router 只校验 Feature、局点和业务 ID，再调用 Application Service；
- Application Service 只要求列车身份可由基础资料或点表解析，且当前列车点表存在、完整并含可执行节点；
- 在线状态查询结果是 Optional。存在时任务参数保存 CT/TC MR、快照时间和原始状态；不存在、离线或过期时仍创建任务；
- Worker 以点表及其绑定设备作为检测目标，找不到正式 MR 分组时仍按点表地址执行可用步骤；
- AC/Mesh-Link 没有数据、查询失败或显示双端离线时记录辅助状态并继续 MR SSH、车内 Ping 和跨 TC 检测，不提前生成离线结论；
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

`summary` 提供页面摘要，`trains` 提供本页全部列车及最近检测状态，`online` 保留为当前在线列车过滤接口。既有 MR 聚合查询接口继续供其他独立页面或兼容调用使用。

## 刷新与导航

- 手工刷新同时重新读取全部列车、辅助在线状态和当前拓扑，并尽量保留当前选择；
- 自动刷新可关闭，或设置为 10、30、60 秒；
- 同一页面只维护一个自动刷新定时器和一个检测任务轮询定时器；
- 点击已有 `device_id` 的节点跳转到 `/devices/{device_id}`，复用设备详情；未配置节点不创建虚假详情；
- 页面卸载时清理全部定时器。

## 验收边界

自动测试覆盖固定六节点、状态映射、VRRP 静态展示、空状态、API DTO、任务路由和定时器清理。交换机/服务器拓扑关联、跨 TC 实际检测及真实设备通信仍需点表事实源和现场验收；完成前不得把“未配置/未检测”提升为正常。当前没有 VRRP 主备状态检测能力，不得由节点、Ping 或跨 TC 结果推断。
