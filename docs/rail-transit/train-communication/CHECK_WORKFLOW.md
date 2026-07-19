# 检测流程

“立即检测”遵循以下流程：

1. 后端校验 Feature、局点和列车 ID。
2. `TrainCommunicationPointTableService` 校验当前列车点表。
3. 点表缺失返回 `TRAIN_COMMUNICATION_POINT_TABLE_MISSING`；点表无效返回 `TRAIN_COMMUNICATION_POINT_TABLE_INVALID`。
4. 通过校验后创建 `car_network_diagnostic` Task Center 任务。
5. 任务按已有车内通信检测逻辑执行并保存结构化结果。
6. 查询服务聚合节点、链路、VRRP 和跨 TC 状态。
7. Vue 轮询任务状态并在终态重新读取拓扑。

页面卸载或切换列车只清理前端轮询定时器，不会误停后台任务。Online MR 和 Traffic 任务不属于本流程。
