# 轨道交通文档

本目录收纳轨道交通业务的当前专题说明。车内通信检测已退役，旧资料见 [RETIRED](./train-communication/README.md)。

- [基础设施架构](./INFRASTRUCTURE_ARCHITECTURE.md)
- [数据模型](./INFRASTRUCTURE_DATA_MODEL.md)
- [UI 规范](./INFRASTRUCTURE_UI_SPEC.md)
- [初始化与迁移](./INFRASTRUCTURE_MIGRATION.md)

活动实现以 `src/netconsole/services/rail_transit/`、FastAPI Router 和 `apps/desktop_renderer/src/views/rail-transit/` 为准；本文不恢复 Qt 运行入口，也不把规划状态写成已完成。

- [基础资料编辑生命周期](./BASE_DATA_EDITING.md)
- [轨旁 AP 主数据与关联模型](./TRACKSIDE_AP_DOMAIN_MODEL.md)

- [地面无人值守 V2](./ground-unattended/README.md)
