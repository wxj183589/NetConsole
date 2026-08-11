# 轨道交通文档

本目录收纳轨道交通业务的当前专题说明。车内通信检测的固定拓扑、点表、检测流程、VRRP、跨 TC 通信和 Qt 迁移事实见 [train-communication](train-communication/README.md)。

活动实现以 `src/netconsole/services/rail_transit/`、FastAPI Router 和 `apps/desktop_renderer/src/views/rail-transit/` 为准；本文不恢复 Qt 运行入口，也不把规划状态写成已完成。

- [基础资料编辑生命周期](BASE_DATA_EDITING.md)
- [轨旁 AP 主数据与关联模型](TRACKSIDE_AP_DOMAIN_MODEL.md)
