# 在线列车车内通信检测

`/rail-transit/train-communication` 是固定拓扑状态页。正式业务名称为“在线列车车内通信检测”。页面展示 TC1/TC2 两端的六个固定节点、节点链路、VRRP 与跨 TC 状态；检测任务复用现有 Task Center，不在页面内直接连接设备。

## 文档

- [点表模型与维护](POINT_TABLE.md)
- [固定拓扑与节点映射](TOPOLOGY.md)
- [检测任务流程](CHECK_WORKFLOW.md)
- [VRRP 语义](VRRP.md)
- [跨 TC 检测](CROSS_TC.md)
- [Qt 业务迁移说明](MIGRATION_FROM_QT.md)

## 当前边界

- 点表是拓扑和检测对象的唯一配置来源，当前存储为每个局点的 `car_network/parsed/point_table.json`。
- Python `TrainCommunicationPointTableService` 负责读取、revision 和六节点完整性检查。
- 在线列车选择来自 `VehicleMrOnlineQueryService` 的正式当前状态，只允许 `BOTH_ONLINE` 和 `ONE_SIDE_ONLINE` 且在线端数据新鲜的列车进入本页。
- Python `TrainCommunicationQueryService` 负责状态聚合与 canonical 列车身份匹配；Vue 只负责交互和状态映射。
- 点表生成只形成预览；保存任务完成原子替换和 revision 复验后，Dialog 通过 `saved` 事件通知父页面刷新拓扑和检测启动条件。
- 未配置、未检测、检测中、正常、异常和数据过期必须保持区分。
- Online MR、Mesh-Link、轨旁 AP、fping 和 iPerf 不在本页执行或聚合。
