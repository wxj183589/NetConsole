# 基础资料恢复与兼容

真实历史来源：Phase 1 前 `12b92a716c021a6947d74182b582d61d9e494080`，由 `git log --follow` 和 `git show 5b445862^:apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue` 确认。Phase 1 并未删除主页面；本轮复用原文件，移除嵌入的工作台并恢复标题、导航与原总览，而非从截图重写。

| 原业务 | 恢复情况 |
| --- | --- |
| overview 基础资料总览 | 原元数据/统计和显式解锁保留；不含工程工作台 |
| stations 站点与区间 | 原表格、站点来源、模板预览、编辑、区间生成、引用校验保留 |
| trackside-ap 轨旁 AP | 原台账、过滤、编辑、导入/字段合并/导出保留 |
| trackside-ap-planning 轨旁 AP 规划 | 原受控草稿组件、VLAN规划与模板流程保留 |
| trains 列车与车载 MR | 列车/MR两个子页、查询与监测策略保留；资产限制见下 |
| quality 数据质量问题 | 原分组、过滤与问题信息保留 |
| import-preview 导入预览 | 原策略、文件、预览、逐字段决策与保存流程保留 |
| import-audit 导入审计 | 原操作/字段记录与回滚流程保留 |
| relations 关联运行状态 | 原只读运行关系表保留，不变成工程关系编辑器 |

以上全部原主Tab值、Route `rail-transit-base-data`、Navigation `rail.base-data`、`/rail-transit/base-data?tab=...` 和 Store `rail-transit-base-data` 保留。原规划重定向继续指向基础资料，不误跳工程模块。普通菜单重入仍回总览；明确书签和页面刷新保持指定Tab，不被旧工作区快照覆盖。

原 API、字段含义、导入解析/预览/审计、正式保存/导出流程不删除、不重写。新增模块拆分只改变归属与权限；正式文件交互继续既有协调器，不新增导出任务状态机。原基础资料编辑使用完整scope快照和revision，脏草稿/失败/取消保护不变。

### 历史安全差异

`907183a4` 已封闭原 MR 资产新增/删除和连接字段编辑，本轮不从历史重新开放。设备资产仍由设备管理统一维护，MR备用监测策略继续在原资料子页维护，页面明确提示该限制。Phase3/3.6资产删除冻结高于旧UI恢复，`can_delete=false`继续有效；这不是本轮静默删减。

共享站点/区间/AP基础字段继续由既有BaseData Application Service维护；Phase3工程项目/设备区间/AC服务/MR assignment只由Relationship Application Service维护，不复制同一关系表或另建Repository。旧 `vehicles` scope不用于写入Phase3 assignment。

Phase1–4曾借 `/rail-transit/base-data?node_uid=...` 进入基础设施的外部书签，现在明确落在基础资料，不重定向占用旧路径；请改为 `/rail-transit/infrastructure?node_uid=...`。内部所有工程上下文跳转已迁移；旧`tab`始终只属于基础资料。
