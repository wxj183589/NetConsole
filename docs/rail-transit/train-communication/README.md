# 车内通信检测

`/rail-transit/train-communication` 是固定拓扑状态页。正式业务名称为“车内通信检测”。页面展示当前局点全部已登记列车、TC1/TC2 两端的六个固定节点、节点链路、VRRP 虚拟 IP 静态配置与跨 TC 状态；检测任务复用现有 Task Center，不在页面内直接连接设备。

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
- 列车列表由基础资料、点表和已配置车载 MR 合并，按统一列车身份自然排序和去重；没有在线快照时仍可选择。
- `VehicleMrOnlineQueryService` 只补充双端在线、单端在线、离线、过期或未知状态，不参与页面准入和任务启动判定。
- Python `TrainCommunicationQueryService` 负责状态聚合与 canonical 列车身份匹配；Vue 只负责交互和状态映射。
- VRRP 仅保留点表 `vrrp_ip` 静态配置展示；兼容 DTO 字段不参与状态、主备角色或诊断结论，中间交换机横线只表示拓扑连接。
- 点表生成只形成预览；保存任务完成原子替换和 revision 复验后，Dialog 通过 `saved` 事件通知父页面刷新拓扑和检测启动条件。
- 未配置、未检测、检测中、正常、异常和数据过期必须保持区分。
- Online MR、轨旁 AP、fping 和 iPerf 不在本页执行；Mesh-Link 仅作为检测过程中的辅助状态，不替代点表节点的真实 SSH/Ping 结果。
