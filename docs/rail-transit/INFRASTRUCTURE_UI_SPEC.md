# 基础设施工作台

Phase 5 起，轨道交通下的「基础设施」使用导航 ID `rail.infrastructure`、路由名 `rail-transit-infrastructure`、路径 `/rail-transit/infrastructure` 和 Feature ID `module.rail_infrastructure`。原 `rail.base-data` 等标识恢复为独立基础资料，`?tab=` 只属于基础资料。详见 [模块规范](./INFRASTRUCTURE_MODULE_SPEC.md)。

工作台顶部显示局点、线路、设备与节点数量。左栏按线路、控制中心、正线车站、区间、车辆段与停车场、车载设备展示可折叠组织树。按编号、正式名称、工程名称、历史名称和设备名搜索。中栏显示所选节点的工程资料，右栏通过稳定设备 UUID 打开现有设备详情。原资料子页、数据质量和导入审计仅在独立基础资料模块中保留。

工作台以正式关系展示设备、交换机、AP 及 MR，未确认关系显示待配置。切换节点清理旧选中设备，设备详情保持现有 Current、last-known 和采集失败状态。未提供正式写入契约的新关系只读，既有站点、区间、AP 与计划编辑保持草稿和 revision 边界。

桌面按 1920×1080 和 2560×1440 验收各栏滚动、深链接、设备详情及长标签。统一使用现有应用主题与组件。
