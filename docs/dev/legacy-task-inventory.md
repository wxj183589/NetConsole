# Legacy Task Inventory

复核日期：2026-09-04。本文是 `legacy_tasks.py` 的只读盘点，不拆分文件、不移动函数、不改变 Job Registry dispatch，也不创建新的 handler。

## 规模与当前入口

| 项目 | 当前事实 |
| --- | --- |
| Legacy 文件 | `src/netconsole/services/job_center/handlers/legacy_tasks.py`：2322 行、91 个顶层函数、1 个类 |
| Legacy 分支 | `run_background_task` 中 67 个 `job.task_type` 分支 |
| Job Registry | `builtin_handlers()` 当前注册 137 个 task type |
| Legacy 兼容 handler | 当前有 49 个 handler 的 docstring 表明其通过 `legacy_handler` 委托到 `legacy_tasks` |
| 运行时入口 | `job_registry.dispatch_job()` → `get_handler()` → `builtin_handlers()` 返回的模块级 `HANDLERS`；`background_tasks.py` 只是兼容调用面，不是第二套运行时 |
| 本表覆盖 | 67 个仍在 `legacy_tasks.py` 分支中的 task type；模块是当前注册入口模块，入口表达式统一写成 `handlers/<module>.HANDLERS[task_type]` |

`legacy_tasks.py` 中的分支和当前 Handler Registry 的注册项不是一一等价的“第二套任务中心”：部分模块已经把同一 task type 接到较新的本地 handler，另一部分仍通过 `legacy_handler` 委托到 `_legacy` 函数。迁移时必须以当前 `HANDLERS` 实际入口、参数契约、结果 DTO、文件副作用和取消语义为准，不能只按文件名搬运。

## 风险与迁移优先级口径

- `LOW`：查询、历史页、导出、文件/Profile 或简单本地读取；主要风险是参数/结果契约漂移。
- `MEDIUM`：本地数据库/文件写入、删除、领域刷新或身份关联；主要风险是副作用、回滚和跨模块数据一致性。
- `HIGH`：Online MR、Vehicle MR 在线状态、MESH 解析/派生库，或会影响持续运行/无人值守链路；必须先固化输入、持久化、取消、失败恢复和现场验收证据。

优先级不是本阶段的实施授权。尤其 HIGH 项只登记，不在本阶段创建迁移 handler 或移动代码。

## 67 个 Legacy task type

| task type | module | current entry | risk | migration priority |
| --- | --- | --- | --- | --- |
| `device_csv_import` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 本地文件导入并写入设备资料 | MEDIUM |
| `device_list_page` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备列表查询 | LOW |
| `device_object_history_page` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备历史查询 | LOW |
| `trackside_interface_history_page` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁接口历史查询 | LOW |
| `car_network_point_table_import` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 点表文件导入与本地持久化 | MEDIUM |
| `car_network_point_table_load` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 点表和配置本地读取 | LOW |
| `car_network_refresh_all` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 设备资料与车内通信投影刷新 | MEDIUM |
| `car_network_generate_point_table` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 从设备资料生成本地点表 | MEDIUM |
| `car_network_save_point_table` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 点表本地写入 | MEDIUM |
| `trackside_ap_plan_import` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁 AP 规划文件导入 | MEDIUM |
| `trackside_ap_plan_refresh` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁规划本地读取/刷新 | LOW |
| `trackside_ap_plan_save` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁规划写入和排序契约 | MEDIUM |
| `vehicle_mr_mapping_import` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 车载 MR 映射文件导入 | MEDIUM |
| `vehicle_mr_mapping_load` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 车载 MR 映射读取 | LOW |
| `vehicle_mr_mapping_save` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 车载 MR 映射写入 | MEDIUM |
| `vehicle_mr_online_refresh_all` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 在线状态、当前态和历史清理 | HIGH |
| `vehicle_mr_ap_mapping_refresh` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 在线事件与轨旁 AP 映射回填 | HIGH |
| `vehicle_mr_event_page` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 在线事件历史查询 | LOW |
| `vehicle_mr_history_query` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 在线历史筛选查询 | LOW |
| `fit_ap_metadata_import` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | FIT-AP 元数据文件导入 | MEDIUM |
| `fit_ap_extension_preview` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | 扩展字段预览 | LOW |
| `fit_ap_extension_commit` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | FIT-AP 扩展字段写入 | MEDIUM |
| `ac_overview_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AC 概览领域刷新 | MEDIUM |
| `ac_fit_ap_resources_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AC/FIT-AP 资源采集和持久化 | MEDIUM |
| `ac_fit_ap_optical_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | FIT-AP 光衰采集和状态更新 | MEDIUM |
| `ac_ap_extensions_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AP 扩展资料刷新 | MEDIUM |
| `omnipeek_name_table_preview` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | 本地名称表预览 | LOW |
| `ac_overview_history_snapshot` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AC 概览历史读取 | LOW |
| `ac_station_online_history_page` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | 站点在线历史查询 | LOW |
| `ac_ap_history_page` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AP 历史查询 | LOW |
| `ac_trackside_business_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AC 与轨旁 AP 业务聚合刷新 | MEDIUM |
| `config_compare_latest_running_between_devices` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 已保存 running 快照比较并生成文件 | LOW |
| `config_compare_latest_snapshots` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 已保存快照比较 | LOW |
| `config_compare_snapshot_pair` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 指定快照比较 | LOW |
| `config_snapshot_load_content` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 快照文件内容读取 | LOW |
| `config_snapshot_copy` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 快照文件复制 | LOW |
| `config_snapshot_pair_load_content` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 快照对内容读取 | LOW |
| `config_snapshot_delete_many` | `config_jobs.py` | `job_registry.dispatch_job` → `handlers/config_jobs.HANDLERS` | 多文件/快照删除和部分失败 | MEDIUM |
| `online_mr_parse` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | parsed DB 重建及 identity shadow | HIGH |
| `mesh_log_import` | `mesh_jobs.py` | `job_registry.dispatch_job` → `handlers/mesh_jobs.HANDLERS` | 原始 MESH 日志导入、解析和映射 shadow | HIGH |
| `mesh_derived_rebuild` | `mesh_jobs.py` | `job_registry.dispatch_job` → `handlers/mesh_jobs.HANDLERS` | 派生分析库重建 | HIGH |
| `online_mr_report_export` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | Online MR parsed 数据导出 | HIGH |
| `wireless_scan_history_refresh` | `wireless_scan_legacy_jobs.py` | `job_registry.dispatch_job` → `handlers/wireless_scan_legacy_jobs.HANDLERS` | 无线扫描历史刷新 | MEDIUM |
| `wireless_scan_result_load` | `wireless_scan_legacy_jobs.py` | `job_registry.dispatch_job` → `handlers/wireless_scan_legacy_jobs.HANDLERS` | 无线扫描结果读取 | LOW |
| `ac_devices_refresh` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AC 设备清单刷新 | LOW |
| `ac_fit_ap_delete_many` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | FIT-AP 资料批量删除和索引更新 | MEDIUM |
| `ac_ap_extension_save` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AP 扩展字段写入 | MEDIUM |
| `ac_ap_extension_delete` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AP 扩展字段删除 | MEDIUM |
| `ac_ap_extension_clear` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | AP 扩展字段清空 | MEDIUM |
| `ac_station_overview_value_save` | `ac_jobs.py` | `job_registry.dispatch_job` → `handlers/ac_jobs.HANDLERS` | 站点概览值写入 | MEDIUM |
| `device_detail_load_all` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备详情资料本地读取 | LOW |
| `fit_ap_detail_load` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | FIT-AP 详情读取 | LOW |
| `fit_ap_metadata_save` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | FIT-AP 元数据写入 | MEDIUM |
| `online_mr_collection_devices_refresh` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | 在线采集设备范围刷新 | HIGH |
| `online_mr_mark_stale_sessions` | `online_mr_jobs.py` | `job_registry.dispatch_job` → `handlers/online_mr_jobs.HANDLERS` | Online MR 会话过期标记 | HIGH |
| `mesh_mr_profiles_refresh` | `mesh_jobs.py` | `job_registry.dispatch_job` → `handlers/mesh_jobs.HANDLERS` | MESH/MR Profile 与设备资料同步 | HIGH |
| `file_management_navigation_refresh` | `file_jobs.py` | `job_registry.dispatch_job` → `handlers/file_jobs.HANDLERS` | 文件管理目录读取 | LOW |
| `device_mutation` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备资料本地写入 | MEDIUM |
| `device_lookup` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备查询 | LOW |
| `device_group_refresh` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备分组读取/刷新 | LOW |
| `device_group_create` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备分组创建 | MEDIUM |
| `device_group_rename` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备分组重命名 | MEDIUM |
| `device_group_count_devices` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 分组设备计数 | LOW |
| `device_group_delete` | `device_jobs.py` | `job_registry.dispatch_job` → `handlers/device_jobs.HANDLERS` | 设备分组删除 | MEDIUM |
| `trackside_device_detail_resolve` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁设备身份匹配 | MEDIUM |
| `trackside_fit_ap_detail_resolve` | `rail_transit_jobs.py` | `job_registry.dispatch_job` → `handlers/rail_transit_jobs.HANDLERS` | 轨旁 FIT-AP 身份匹配 | MEDIUM |
| `network_profile_store` | `network_jobs.py` | `job_registry.dispatch_job` → `handlers/network_jobs.HANDLERS` | 本地网络 Profile 文件读写 | LOW |

## 后续迁移排序

1. 先为 HIGH 项补齐输入/输出 DTO、持久化 owner、取消与失败恢复、数据隔离和真实验收证据，再讨论 handler 迁移。
2. 再处理 MEDIUM 项，逐项核对数据库写入、文件格式、索引刷新、审计和回滚，不以“函数较短”作为迁移依据。
3. LOW 项适合先做契约冻结和最小迁移，但仍需保留旧 task type 的兼容读取/历史数据边界，直到调用方完成切换。

本阶段只完成 inventory；未新增 handler、未改变 dispatch、未修改 Task Runtime/API/DB/UI，也未触碰真实设备或真实开发数据。
