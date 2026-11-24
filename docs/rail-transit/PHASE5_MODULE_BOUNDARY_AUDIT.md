# Phase 5 模块边界与历史审计

2026-11-24，产品/远端 `334f6226`，DevStatus/远端 `ad5c10c`；工作树均 clean。复用 Phase 3 工作树创建 Phase 5 分支，不移动目录、不合并 main、不回退旧阶段。

## 历史来源

`git log --all`、`git log --follow` 和 `git show 5b445862^:<path>` 确认：Phase 1 前真实基线为 **12b92a716c021a6947d74182b582d61d9e494080**。页面为 `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue`，Pinia 为 `stores/railTransitBaseData.ts`，API 为 `api/railTransitBaseData.ts`，服务为既有 BaseData Query/Application/Import Service 与 Repository。

真实主 Tab：`overview`、`stations`、`trackside-ap`、`trackside-ap-planning`、`trains`、`quality`、`import-preview`、`import-audit`、`relations`；站点页保留站点/区间，列车页保留列车/MR。已有来源导入、预览、字段合并、导入审计/回滚、质量分组、模板及导出在当前文件中仍存在，不需要重写或复制主页面。

Phase 1 的 `5b445862` 将导航、路由、Feature 标题改成基础设施，并在 overview 插入 `InfrastructureWorkbench`；`907183a4` 封闭原 MR 资产增删与连接编辑。Phase 3/4 继续在该工作台接入关系维护与节点跳转。基础资料原 Store/API 与主要业务未被替换。

## 恢复和边界

基础资料恢复原标识、标题及原总览，删除后来嵌入的基础设施工作台；保留当前原业务实现及安全修复。原 MR 资产操作涉及设备管理和删除冻结，不能从历史恢复破坏性写入；保留查询、备用监测策略及既有业务入口，页面明确标记边界。原车站/区间/AP资料与导入继续调用正式 BaseData Application Service，不复制实体或关系表。

基础设施使用独立 View、Pinia、Navigation、Router、Feature。复用 InfrastructureWorkbench/RelationshipEditor/DeviceDetailPanel，独立读取现有工程投影；四类工程关系仍由同一个 Relationship Application Service 写入。工作台不再把用户导航到基础资料 Tab。

| 契约 | 基础资料 | 基础设施 |
| --- | --- | --- |
| Navigation | rail.base-data | rail.infrastructure |
| Route name | rail-transit-base-data | rail-transit-infrastructure |
| Path | /rail-transit/base-data | /rail-transit/infrastructure |
| Feature | module.rail_base_data | module.rail_infrastructure |
| 写权限 | capability.rail_base_data.write | capability.rail_infrastructure.write |
| 页面/Store | 既有 BaseData View/Store | 独立 Infrastructure View/Store |
| HTTP | 原 base-data API/导入预览审计 | 新 infrastructure 查询与既有 relationships API |

旧 base-data/infrastructure API保留兼容，但额外要求基础设施权限；新独立入口不依赖基础资料模块可见性。关系路由改为基础设施模块/写权限；底层保护仍复用原环境/副本/明确确认规则。专业业务内部只读 Query 无新增交叉菜单依赖。工程上下文的节点跳转迁往新基础设施；质量治理、原规划深链接继续基础资料。

## Change Impact / Consumers

最高风险 L4（Feature注册与权限），无Schema/迁移/删除规则变化。用户明确要求本次定向验收，不默认Full Gate；不得把定向结果写为平台完整基线。新增Feature是独立兄弟节点，只共用 internal.rail_base_data 低层服务依赖；不能继承另一可见模块权限。

消费者：Full/Customer配置、FeatureGate/snapshot、导航、Router guard、关系API、原基础资料API、BaseData编辑锁与导入/导出、工作区标签/缓存/恢复、Electron路径白名单、DeviceDetail/AC/Ground/Trackside/MESH/Online MR上下文跳转。旧书签base-data及九个tab继续指向原资料；Phase1–4借用旧路径的基础设施书签不再占用该路径，node_uid只在新路径解释。

并行检查：其余产品worktree为主仓库detached 547be73a、Phase1 907183a4、Phase2 4031f88d；只读核对status，不修改它们。DevStatus原Phase4分支保留。已有任务产物和历史数据保留。

回归矩阵：Feature registry/profile/edition、独立导航/Route/Store、九Tab兼容和编辑/导入审计、关系读写/权限/冲突/删除冻结、上下文消费者、Electron路径/重启恢复、双分辨率截图、Main smoke、Architecture、Ruff、文档与diff。最终集成main未请求，后续合并必须独立验证。
