# 架构门禁债务审计（2026-07-25）

## 范围与结论

本记录基于 `main@e8d8091e` 与本轮独立整改分支的 `scripts/architecture/run_all.py`。只修复两个明确边界：`device_compatibility_router.py` 不再构造 Service，地面无人值守 Service 不再反向导入 Desktop Application。未修改 Guard、未增加例外，也未批量处理 Direct SQL 或 UI。

| 类别 | 整改前 | 整改后 | 本轮处置 |
| --- | ---: | ---: | --- |
| 未豁免架构边界 | 6 | 4 | 修复 2 |
| 未分类 Direct SQL | 31 | 31 | 仅归档 |
| UI 业务/分类候选 | 29 | 29 | 仅归档 |
| UI 样式命中 | 8 | 8 | 仅归档 |
| 失效架构例外 | 2 | 0 | 删除已确认存在生产调用者的 2 条 orphan 例外 |

上述 4、31、29、8 均为未豁免门禁 Finding，会继续导致统一架构门失败。自动扫描候选不等于已确认业务缺陷；整改前应读取实现、调用者和测试，再决定归位或精确分类。

## Router Service 构造与状态访问

| 文件 | 剩余 Finding | 建议切片 |
| --- | --- | --- |
| `src/netconsole/backend/api/ground_unattended_router.py` | `SiteManager.get_current_site` 状态访问 1 处 | 由组合根注入局点查询/校验能力，Router 只调用 Application Service |
| `src/netconsole/backend/api/site_storage_router.py` | 构造 `SiteAuditService`、`SiteCleanupApplicationService` 共 2 处 | 在 `create_app()` 统一构造并挂载 `app.state` |
| `src/netconsole/backend/api/system_settings_router.py` | 构造 `RuntimeSelfCheckService` 1 处 | 注入现有运行时自检 Service |

本轮已关闭 `src/netconsole/backend/api/device_compatibility_router.py` 的 `DeviceCompatibilityService` 构造 Finding。

## 反向依赖

本轮修复后没有新增未豁免的 Python 反向依赖。以下 14 个历史依赖仍由 `config/architecture/exceptions.yaml` 精确限时豁免，不属于“门禁已通过”：

| 层级 | 文件 |
| --- | --- |
| Core | `src/netconsole/core/bootstrap.py` |
| Core | `src/netconsole/core/mr_collect/parser/counter_parser.py` |
| Core | `src/netconsole/core/mr_collect/parser/fping_parser.py` |
| Core | `src/netconsole/core/mr_collect/parser/mesh_parser.py` |
| Core | `src/netconsole/core/mr_collect/ssh_client.py` |
| Core | `src/netconsole/core/ping/fping_v5_runner.py` |
| Core | `src/netconsole/core/sites.py` |
| Repository | `src/netconsole/repositories/ac_repository.py` |
| Repository | `src/netconsole/repositories/mesh_mr_repository.py` |
| Repository | `src/netconsole/repositories/rail_transit_base_data_repository.py` |
| Service | `src/netconsole/services/command_reference_application_service.py` |
| Service | `src/netconsole/services/device_management_web_service.py` |
| Service | `src/netconsole/services/file_management_service.py` |
| Service | `src/netconsole/services/job_center/query_service.py` |

本轮已关闭 `src/netconsole/services/ground_unattended/application_service.py` 对 `netconsole.application.desktop.actions` 的反向依赖，改由下层 `DesktopActionPort` 表达消费方契约。

## 未分类 Direct SQL

| 文件 | 行 | 数量 | 后续确认方向 |
| --- | --- | ---: | --- |
| `scripts/maintenance/migrate_unified_data_root.py` | 466 | 1 | 维护迁移脚本所有权 |
| `src/netconsole/core/data_root_configuration.py` | 138、141 | 2 | 数据根配置/迁移边界 |
| `src/netconsole/repositories/ground_unattended_repository.py` | 917 | 1 | Repository 所有权 |
| `src/netconsole/services/device_compatibility/service.py` | 413 | 1 | 只读数据网关或 Repository |
| `src/netconsole/services/rail_transit/station_source_discovery_service.py` | 394 | 1 | 只读数据网关 |
| `src/netconsole/services/runtime_self_check_service.py` | 234、291 | 2 | 只读自检网关 |
| `src/netconsole/services/site_lifecycle.py` | 132、156、182、507、571 | 5 | Site Repository/迁移边界 |
| `src/netconsole/services/site_sync.py` | 793、794、795、904、999、1000、1074、1249、1260、1261、1271、1282、1291、1292 | 14 | Site 同步专用 Repository/网关 |
| `tests/test_device_compatibility.py` | 179 | 1 | `TEST_ONLY` 或 fixture helper |
| `tests/test_rail_transit_base_data_query_service.py` | 89 | 1 | `TEST_ONLY` 或 fixture helper |
| `tests/test_rail_transit_import_preview.py` | 135 | 1 | `TEST_ONLY` 或 fixture helper |
| `tests/test_unified_data_root_migration.py` | 13 | 1 | `TEST_ONLY` 或 fixture helper |

合计 31 处。后续不能直接批量登记分类；每个文件必须先确认连接的数据库、读写性质、生命周期与测试证据。

## UI 业务逻辑与分类

| 文件 | 候选符号 | 数量 |
| --- | --- | ---: |
| `apps/web/src/api/tracksideApBusiness.ts` | `normalizeTracksideApBusinessArtifactName` | 1 |
| `apps/web/src/components/charts/multiSeriesTimeChart.ts` | `resolveChartDevicePixelRatio`、`normalizedApRadioColorKey` | 2 |
| `apps/web/src/components/mesh-analysis/MeshTracksideSignalChart.vue` | `resolvedPoint`、`normalizedIdentity` | 2 |
| `apps/web/src/components/mesh-analysis/meshChartViewport.ts` | `resolveMeshSharedTimeDomain` | 1 |
| `apps/web/src/components/mesh-analysis/meshRssiLayout.ts` | `normalizeMeshRssiLayoutMode`、`normalizeMeshRssiSplitRatio`、`resolveMeshRssiCompareLayout` | 3 |
| `apps/web/src/components/mesh-analysis/tracksideSeriesCache.ts` | `mergeTracksideCoverageIntervals`、`tracksideFrameMatchToleranceMs`、`resolveTracksideTooltipFrame` | 3 |
| `apps/web/src/utils/opticalPresentation.ts` | `normalizedOpticalStatus` | 1 |
| `apps/web/src/validation/opaqueIdentifier.ts` | `normalizeOpaqueIdentifier`、`normalizeMeshSessionIdentifier` | 2 |
| `apps/web/src/views/DashboardView.vue` | `resolveNavigationTarget` | 1 |
| `apps/web/src/views/rail-transit/CarNetworkPointTableDialog.vue` | `normalizeTrainIdentity`、`normalizeNodeName`、`rowMatchesTrain` | 3 |
| `apps/web/src/views/rail-transit/RailTransitBaseDataView.vue` | `handleStationClassificationChange`、`matchesApSection`、`sourceMatchLabel` | 3 |
| `apps/web/src/views/settings/SiteStoragePanel.vue` | `classificationLabel`、`classificationTag` | 2 |
| `apps/web/src/views/settings/SystemSettingsView.vue` | `aggregateSelfCheckStatus`、`resolveFeatureConfigurationAvailability` | 2 |
| `apps/web/src/workspace/route-identity.ts` | `resolveWorkspacePolicy`、`normalizeParam` | 2 |
| `apps/web/src/views/rail-transit/OnlineMrAnalysisView.vue` | 已登记的 `clearDerivedData` 不再被 AST 检出，属于 stale classification | 1 |

合计 29 处。处理顺序应先清理 stale classification，再将纯展示/传输适配候选连同测试精确分类；真正计算业务事实的逻辑再下沉 Backend。

## UI 样式

| 文件 | Finding | 数量 |
| --- | --- | ---: |
| `apps/web/src/components/mesh-analysis/MeshTracksideSignalChart.vue` | 图表字面颜色 `#909399` | 1 |
| `apps/web/src/styles/main.css` | `.app-main` 宽度不是 `100%` | 1 |
| `apps/web/src/views/rail-transit/OnlineMrAnalysisView.vue` | 3 处状态背景色同时命中 `WEB_STATUS_COLOR_TOKEN` 与 `WEB_THEME_BASE_LITERAL` | 6 |

合计 8 处。颜色应复用现有语义 Token；布局需在多尺寸与横向滚动约束下单独验证，不能只为消除字符串 Finding 改值。

## 失效例外

`src/netconsole/services/online_mr/ping_presets.py` 已由 `online_mr_control_router.py` 生产引用；`src/netconsole/services/online_mr/traffic_presets.py` 已由同一 Router 生产引用。两条 `ORPHAN_SERVICE_MODULE` 例外已失效并在本轮删除，剩余 stale architecture exception 为 0。

本轮没有删除其他精确限时例外。其余 orphan 候选不在本次整改范围，不能据静态调用图猜测性删除。
