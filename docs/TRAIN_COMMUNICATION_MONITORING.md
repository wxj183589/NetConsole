# 在线列车车地通信检测

点表、固定拓扑、VRRP、跨 TC 和迁移事实源的详细说明见 [专题文档目录](rail-transit/train-communication/README.md)。

## 定位

`/rail-transit/train-communication` 是固定车载拓扑状态页，不是无线综合看板。页面只展示列车选择、TC1/TC2 两端固定六节点、节点和链路状态、VRRP、跨 TC 通信、刷新与“立即检测”。

固定节点为：

```text
TC1-MR -> TC1-SW -> TC1-SRV
             |
          VRRP / 跨 TC
             |
TC2-MR -> TC2-SW -> TC2-SRV
```

轨旁 AP、RSSI、fping、丢包、iPerf、光衰、Online MR、Agent 和 Mesh-Link 属于各自独立页面，不在本页聚合、筛选或控制。底层业务模块和历史数据不因此删除。

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
- 页面轮询现有任务状态，终态后重新读取拓扑；
- 页面卸载或切换列车时清理轮询，不停止后台任务；
- 本入口不启动 Online MR、不启动持续 fping/iPerf、不采集轨旁 AP，也不接受命令、凭据或路径。

## API

```text
GET  /api/rail-transit/train-communication/summary
GET  /api/rail-transit/train-communication/trains
GET  /api/rail-transit/train-communication/trains/{train_id}/topology
POST /api/rail-transit/train-communication/trains/{train_id}/checks
GET  /api/rail-transit/train-communication/checks/{task_id}
```

`summary` 和 `trains` 只为当前局点及列车选择提供来源。既有 MR 聚合查询接口继续供其他独立页面或兼容调用使用，但不再驱动本页 UI。

## 刷新与导航

- 手工刷新只重新读取拓扑快照；
- 自动刷新可关闭，或设置为 10、30、60 秒；
- 同一页面只维护一个自动刷新定时器和一个检测任务轮询定时器；
- 点击已有 `device_id` 的节点跳转到 `/devices/{device_id}`，复用设备详情；未配置节点不创建虚假详情；
- 页面卸载时清理全部定时器。

## 验收边界

自动测试覆盖固定六节点、状态映射、空状态、API DTO、任务路由和定时器清理。交换机/服务器拓扑关联、VRRP、跨 TC 实际检测及真实设备通信仍需点表事实源和现场验收；完成前不得把“未配置/未检测”提升为正常。
