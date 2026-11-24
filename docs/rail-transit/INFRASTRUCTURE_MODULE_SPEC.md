# 基础设施模块

入口 `/rail-transit/infrastructure`；导航 `rail.infrastructure`；Feature `module.rail_infrastructure`。它是工程组织与工程关系中心，独立于基础资料。

复用 Phase 1–4 的 InfrastructureWorkbench：左侧组织树按控制中心、正线车站、车辆段/停车场和列车分组，站间区间位于正线车站下的展示分组并保留两个端点；中间按节点类型精简，名称历史和工程关系按需展开，右侧通过稳定 UUID 查看设备事实。没有正式关系的层级不补造；Point/Identity/LLDP/运行状态保持原边界。详见[工程层级与真实验证](./PHASE5_2_INFRASTRUCTURE_HIERARCHY.md)。

四类关系仍走 `/api/rail-transit/relationships`，保留创建/修改/解除、MR 更换、AC 多站点、项目管理、服务器预览、明确确认、幂等、revision冲突、历史与操作审计。模块查看权限与 `capability.rail_infrastructure.write` 独立校验；BaseDataWriteGuard继续负责环境/副本/桌面会话保护，其实现没有修改。

`/api/rail-transit/infrastructure` 的新 Application Service 复用 BaseData Query；`/switch-aps` 复用 Trackside Query，另要求 Trackside Feature。AC资源概览仍要求 AC Feature。所有工程上下文节点跳转指向新路径，仅传 `node_uid`。设备、Wireless、Online MR仍为原专业页面，不纳入本模块。

独立 Pinia `rail-transit-infrastructure` 只保存查看快照、筛选、选中节点/设备与刷新状态；基础资料 Store不引用它。关系草稿仍由原 RelationshipEditor 管理，离开路由/切换局点沿用脏状态保护。

不新增节点或设备采集引擎，不重写正式关系逻辑，不伪造无数据的运行摘要。资产删除只读预检继续 `can_delete=false`，不提供物理删除授权。
