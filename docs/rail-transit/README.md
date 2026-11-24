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

- [Phase 4 消费者审计](./PHASE4_CONSUMER_AUDIT.md)
- [统一工程上下文契约](./ENGINEERING_CONTEXT_CONTRACT.md)
- [Ground 接入](./PHASE4_GROUND_INTEGRATION.md)
- [轨旁 AP 接入](./PHASE4_TRACKSIDE_AP_INTEGRATION.md)
- [AC / Wireless 接入](./PHASE4_AC_WIRELESS_INTEGRATION.md)
- [MESH / Online MR 接入](./PHASE4_MESH_MR_INTEGRATION.md)
- [Phase 4 定向验收](./PHASE4_ACCEPTANCE.md)
