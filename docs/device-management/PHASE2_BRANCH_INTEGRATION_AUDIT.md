# Phase 2 分支集成审计

## 基线

- Phase 1：`907183a44ed4530b733df280389259e4af750844`
- 设备管理历史分支：`codex-A/device-management-ui-polish-20261124`
- 历史分支最新提交：`547be73a`
- 两分支共同祖先：`12b92a716c021a6947d74182b582d61d9e494080`
- 历史分支相对 Phase 1：领先 4 个提交，Phase 1 相对历史分支领先 3 个提交

## 历史分支分析

历史分支主要包含设备管理页面、设备管理 API/Repository、连接健康检查、设备详情兼容修复和发布验收记录。它还重新带回了 Phase 1 已退役的车内通信检测入口、专用 API、Feature 和页面，并删除了 Phase 1 的基础设施 Schema、Query 和工作台文件。

因此本阶段不整合历史分支的整体提交。设备管理页面的现有交互改进、服务端分页、分组计数、批量任务、凭据保护和共享 `DeviceDetailPanel` 已在 Phase 1 基线中保留。历史分支新增的健康检查服务与设备管理 API 需要按文件和契约重新评估，避免重新引入已退役功能或覆盖工程关系边界。

## Phase 1 冲突

1. 历史分支删除 `rail_infra_*` Schema、Repository、模型和基础设施工作台，不能直接合并。
2. 历史分支恢复 `train_communication_router.py`、车内通信页面和 Feature，违反 Phase 1 的 RETIRED 结论。
3. 设备管理已有 `station`、`project_phase` 和 `work_scope_status` 写入链。Phase 2 保留旧 API 的兼容读取和受控迁移，关闭设备管理页面中的工程属性维护入口。
4. `DeviceDetailPanel` 是设备列表抽屉和完整详情页共用组件，工程上下文应由 Backend Query Service 返回，Renderer 不拼接基础设施表。

## 采用方案

- 从 Phase 1 建立 `codex-A/device-management-phase2`，不 cherry-pick 历史分支整体提交。
- 扩展 `RailTransitBaseDataQueryService` 的只读工程上下文投影，并注入设备详情查询服务。
- 设备列表显示只读工程归属摘要，设备详情显示完整工程上下文和跳转入口。
- 设备创建、编辑和批量操作继续只维护设备资产字段。建设阶段、工程角色和站点关系不再从设备管理页面写入。
- 保留旧 DTO/API 字段，保证旧数据库、CSV 和现有调用方兼容。新页面不提交这些工程字段。

## 验证影响

涉及 Device DTO、DeviceDetail Query、设备管理 Vue 页面和基础设施 Query，风险为 L3。需要运行设备管理 API/Renderer、基础设施回归、详情组件、架构门、Renderer Full 和最终 Full Gate。真实设备、真实 Electron 安装态、现场局点和长时任务仍需独立验收。
