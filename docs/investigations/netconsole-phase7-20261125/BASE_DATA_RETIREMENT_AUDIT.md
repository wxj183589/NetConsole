# Phase 7 基础资料退役条件与轨旁光衰消费者审计

2026-11-25，审计工作树为 `organization-task-network-services-phase6`。本报告基于当前源码、现有领域文档与隔离测试，真实设备和真实数据验收为 NOT VERIFIED。

## 结论

基础资料退役条件尚未满足，状态为 BLOCKED。组织结构已经拥有独立页面和工程关系入口，基础资料仍承担站点、区间、AP 点位、逐站规划、列车/MR、受控编辑、导入审计和回滚的正式来源职责。直接移除其页面、API、Repository 或表结构会影响多个在用消费者。

本阶段只交付退役条件审计。后续退役须具备明确任务授权，并逐项满足下表条件。

## 入口与持久化清单

| 层次 | 当前来源 | 退役前必须具备的证据 |
| --- | --- | --- |
| 导航与路由 | `router/routes.ts` 的 `rail-transit-base-data`、`rail-transit-infrastructure` 两个独立入口，旧规划路由重定向到基础资料规划 Tab | 原九个 Tab 的职责映射、旧书签和工作区恢复兼容测试 |
| Feature | `module.rail_base_data`、`module.rail_infrastructure` 共用 `internal.rail_base_data`，写权限分别治理 | Full/Customer 的独立权限和 internal 依赖测试，隐藏导航不能切断底层消费者 |
| 页面与 Store | `RailTransitBaseDataView.vue`、`stores/railTransitBaseData.ts` 持有 scope 草稿、revision、导入和查询。组织结构使用独立 View/Store | 每个编辑 scope 的替代入口、草稿保护、失败恢复与同 revision 保存证明 |
| API | `/api/rail-transit/base-data` 保留查询、编辑快照、校验、保存、来源预览、导入应用、审计和回滚。组织结构兼容查询也位于该 Router | 全部调用方迁移、兼容期与错误契约测试，独立组织结构仍能读取查询服务 |
| Application / Query | `application/rail_transit/base_data_application_service.py` 与 `services/rail_transit/base_data_query_service.py` | 稳定 ID、只读 GET、scope 边界、冲突响应和事务回滚等价证明 |
| Repository | `repositories/rail_transit_base_data_repository.py` | 正式写入者和所有只读消费者均有明确接替，历史数据可读 |
| Schema / revision | `core/database.py` 的 `ap_extension_points`、`ac_trackside_ap_plan` 与触发器。站点/区间为辅助行，`devices.station_id` 保留设备绑定 | 显式迁移设计、兼容读取、revision 等价及历史恢复方案 |
| 独立工程事实 | `core/rail_infrastructure_schema.py` 与 `rail_infrastructure_repository.py` 的 `rail_infra_node/train/device_link/train_mr/node_layout` 等事实 | 核验组织初始化标记、节点 UID、显式设备关系与基础资料兼容回退的实际读取边界 |
| 导入导出 | `base_data_import_service.py`、`base_data_preview_store.py`、`railTransitBaseData.ts` 和既有 Export Process | 来源文件、字段决策、operation ID、审计/回滚与导出契约均可继续追溯 |
| 历史 | 导入 operation/changes、关系有效时间、AP/设备采集历史、导出冻结快照 | 当前归属与历史归属分别可解释，历史文件、主键、采集时间和来源引用仍可读取 |

路径位于 `src/netconsole` 或 `apps/desktop_renderer/src` 对应目录。原九个业务 Tab 包含总览、站点与区间、轨旁 AP、规划、列车/MR、质量、导入预览、导入审计和关联运行状态。现有兼容说明是消费者起点，最终结论采用本轮源码核验。[现有模块边界](../../rail-transit/PHASE5_MODULE_BOUNDARY_AUDIT.md) [基础资料规则](../../rail-transit/base-data/README.md)

## 消费者矩阵

| 消费者 | 当前代码证据 | 退役阻断条件 |
| --- | --- | --- |
| 组织结构与工程关系 | `base_data_query_service.py` 的 infrastructure 投影，`rail_transit_base_data_router.py` 的 infrastructure 查询，`rail_relationship_router.py`、`rail_relationship_repository.py` | 原查询 API 与节点来源仍被使用，工程关系历史须保留 |
| 设备管理与详情 | `device_management_web_service.py` 的站点查询，`device_detail_query_service.py` 的工程上下文 | 设备 UUID、站点 ID、资产归属和未关联状态需要持续可读 |
| Trackside AP | `trackside_ap_business_query_service.py`、`trackside_ap_export_service.py` | 基础资料、规划、Identity、接口与光衰组成同一业务投影，缺任一来源需真实表示 partial/unresolved |
| AC / FIT-AP | `services/ac/query_service.py` 的 `EngineeringContextQueryService`，AC Repository 的 AP 基础资料与规划读取 | AC 资源及实时光衰保有独立来源，组织上下文仍依赖基础资料 |
| MESH | `rail_transit/mesh_ap_location_service.py` 的 `base_query`，`mesh_analysis_query_service.py` 的 current/historical context | AP 点位、站点与 MR 关系必须有稳定读取入口，历史分析按事件时间解释 |
| 地面无人值守 | `ground_unattended/inventory.py` 的 `list_mrs` 与 `base_data_revision`，`deep_scheduler.py` 的 `get_mr`，application 的工程上下文 | MR 清单、监测策略、调度目标与历史归属依赖仍在 |
| Online MR | `online_mr/web_control_service.py` 的 `get_mr`，`query_service.py` 的 current/historical context | 运行控制目标与会话历史归属必须继续可解析 |
| 设备任务中心 | `device_task_service.py` 的 `RailInfrastructureRepository.organization_catalog` 节点范围选择及设备 UUID 快照 | 此链直接读取已初始化的组织结构与设备清单，退役审计需覆盖其节点身份和重试目标契约，源码未发现该选择分支直接调用基础资料 Query |
| 无线总览 | `wireless_dashboard_query_service.py` 的设备及 point 上下文 | 聚合页面的工程归属消费者仍需覆盖 |
| 局点生命周期 | `site_lifecycle.py` 引用基础资料 Repository | 局点初始化、复制或维护契约变更须独立审计和授权 |

`engineering_context_query_service.py` 当前通过基础资料 revision、infrastructure 与关系历史组装上下文，并明确区分 current / historical。该聚合查询也属于退役影响面。

当前组织结构读取还包含独立 `rail_infra_*` 事实和初始化状态。`base_data_query_service.infrastructure()` 组合 Infrastructure Repository，并在组织未初始化时保留部分基础资料兼容映射。后续退役需要逐项界定这些兼容读取，不可仅凭公共查询类名称认定所有组织结构事实都由基础资料持有。

## 轨旁光衰事实链审计

| 项目 | 正式来源与身份 | 当前消费者及限制 |
| --- | --- | --- |
| AP 与站点 | `ap_extension_points`、正式 `station_id/section_id`、规划 `station_id` | 名称与 VLAN 只提供属性。AP 解析使用完整规范 MAC 或 Identity entity ID，多候选保持歧义 |
| AC / FIT-AP | `ac_fit_ap_resources`、metadata、`ac_fit_ap_optical`，保留 `ac_device_uuid` 与 AP UUID/MAC | 当前 AC 光衰由 AC 表提供，Site 物理投影独立组合。多 AC 下的物理 AP 去重须保留所有来源 |
| AP Rx / Tx | `AcRepository.list_all_fit_ap_optical()` 及采集时间 | AP 业务 Rx 严格小于 `-13.90 dBm` 异常，等于门限正常，WA6522 不适用。业务异常、设备原生状态、在线状态各有字段 |
| 交换机端口 Rx / Tx | `device_optical_modules`、接口事实与 `device_uuid + normalized interface` | 当前值需要匹配采集代次与时效，旧值通过 last-known 字段呈现 |
| LLDP 与上联 | `device_lldp_neighbors`、FIT-AP LLDP 元数据及历史 | AP 使用完整 MAC 精确关系，交换机身份在当前局点内解析。冲突、快照陈旧和缺失状态均有明确计数与原因 |
| 时间戳 | Query DTO 的 `switch_optical_updated_at`、`switch_last_known_optical_updated_at`、`fit_ap_snapshot_collected_at`、`lldp_snapshot_collected_at`、generation | 快照 `created_at` 表示投影构建时间。各来源采集时间须分别保留 |
| 端口光衰历史 | `TracksideOpticalHistoryService` -> `DeviceFactRepository.list_optical_history()` | 按设备 UUID 和规范接口查询，保留 `collect_run_uuid`、`collected_at`、raw log 引用，并按采集时间排序分页 |
| AP 历史与处置 | AC 资源/光衰历史、交换机光衰历史和 `ap_optical_treatment_events` | 历史导出有独立 revision，处置事件与当前值属于不同来源 |
| 光衰更新任务 | `trackside_ap_update_job.py` -> `collect_trackside_optical()` | 先读取完整业务范围，再执行现有采集入口，任务结果区分成功、失败和部分来源失败 |
| 页面与导出 | 页面 `expected_revision`，Export Worker revision preflight -> staging JSON -> SHA-256 -> XLSX | 同一业务构建逻辑。冻结后的文件内容由哈希验证，当前页面分页数据不能充当完整导出数据 |

身份规则和来源字段可由当前 Query DTO、光衰历史 Service 及领域模型复核。[领域模型](../../rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md) [业务快照规则](../../rail-transit/trackside-ap/BUSINESS_SNAPSHOT.md) [AP Identity](../../AP_IDENTITY.md)

## 快照与缓存一致性

`read_trackside_ap_source_revisions()` 读取 base/planning/device/LLDP/FIT-AP/optical/Identity 等来源。部分基础来源共用同一正式 `base_data_revision`。`trackside_ap_export_service.py` 的缓存键包含数据库与局点范围、来源 revision 及查询身份，缓存保存不可变业务行，最多 64 项，并使用 in-flight 协调。

当前源码在短重试的最后一次允许冻结已经完整读取的非 partial 内容，即使确认阶段 telemetry revision 继续前进。导出也在有限重试后保留完整 payload，再冻结 staging 文件。这保证可交付内容的固定哈希，跨多个 Repository 的读取仍可能经历实时更新。现有 `BUSINESS_SNAPSHOT.md` 中“持续漂移一律失败”的描述与当前实现有差异，应在后续快照契约任务中同步。该差异必须纳入真实持续采集验收。

普通 Query 的 `expected_revision` 冲突、来源 partial、读取错误、Identity 歧义与导出 preflight stale 都应维持结构化诊断。退役前需要覆盖缓存失效、连续 telemetry、部分源不可用和历史导出变更的集成验收。

## 退役门禁与剩余验证

1. 给每个现有编辑 scope、导入/回滚入口和书签明确目标与兼容周期。
2. 列出所有读写者，先实现等价职责，再验证只读 GET、事务、稳定 ID 和 revision。
3. 验证组织结构、设备、AC/FIT-AP、Trackside、MESH、Ground、Online MR、任务中心和导出的跨模块契约。
4. 明确工程关系历史、原始采集、导入审计、处置记录与工作簿历史的保留规则。
5. 通过隔离迁移、失败恢复、旧数据读取和真实 UI/设备验收后，才评估具体退役变更。

本轮定向回归 PASS，共 57 tests，命令如下。

```powershell
python -m pytest tests/test_rail_infrastructure.py tests/test_engineering_context.py tests/test_trackside_ap_business_snapshot.py tests/test_rail_transit_base_data_query_service.py -q
```

该结果覆盖组织结构、工程上下文、快照及基础查询的现有自动化契约。完整导入导出、真实持续采集、全消费者集成与 Electron 四尺寸验收为 NOT VERIFIED。未运行全量 Gate。

```text
MAINTENANCE_AUTHORIZED=NO
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVICE_CONFIGURATION_WRITES=0
```
