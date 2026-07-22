# 检测流程

“开始检测”遵循以下流程：

1. 后端校验 Feature、局点和列车 ID。
2. `TrainCommunicationPointTableService` 校验当前列车点表。
3. 点表缺失返回 `TRAIN_COMMUNICATION_POINT_TABLE_MISSING`；点表无效返回 `TRAIN_COMMUNICATION_POINT_TABLE_INVALID`。
4. 在线快照存在时写入辅助任务上下文；不存在、离线或过期时写入 `UNKNOWN` 或原始状态，但不拒绝任务。
5. 通过校验后创建 `car_network_diagnostic` Task Center 任务。
6. 任务按点表节点继续执行 MR SSH、车内 Ping 和跨 TC 检测；AC/Mesh-Link 查询失败或双端离线只形成辅助告警。
7. 查询服务聚合节点、可检测链路和跨 TC 状态，并单独提供 VRRP 虚拟 IP 静态配置。
8. Vue 轮询任务状态并在终态重新读取拓扑。

页面卸载或切换列车只清理前端轮询定时器，不会误停后台任务。Online MR 和 Traffic 任务不属于本流程。
