# 轨道交通服务

本目录实现轨旁 AP、车载 MR、Mesh 分析、基础资料、通信监控和无线看板的领域查询/Job/写入边界。在线采集、离线导入和报告导出保持独立流程。

主要入口包括 `base_data_*`、`vehicle_mr_*`、`trackside_*`、`mesh_analysis_query_service.py` 和看板查询服务。修改字段、匹配或导入安全时运行轨交专题测试并同步文档。

## 用途与边界

本目录实现轨旁 AP、车载 MR、Mesh 分析、基础资料、通信监控和无线看板的领域查询、Job 和受控写入；在线采集、离线导入和报告导出保持独立流程。

## 主要入口

`base_data_*` 管理基础资料，`vehicle_mr_*`/`car_network_*` 管理车载与通信，`trackside_*` 管理轨旁 AP 快照、光衰和多 Sheet 业务导出，`mesh_analysis_query_service.py` 提供 MESH 只读聚合。MESH 导入、恢复和重建由 ApplicationService/Job 调用 `mesh_bundle_import_service.py`、`mesh_source_rebuild_service.py`；来源级操作只替换当前 detail SQLite，Profile 全量重建是独立高级任务。正式轨旁工作簿仍由独立 Export Process 从局点数据库重建，使用临时文件与原子替换，不以 Vue 当前页数据为事实源。

## 依赖关系

服务依赖 Repository、Parser、Online MR/Mesh Service、Job Center、Application Service 和 PathResolver，由 FastAPI/API/页面调用；不把 SQL 或设备连接放进 Router。

## 数据与状态

基础资料、轨旁快照、MR/Mesh 原始/解析/输出和任务状态按局点数据根分层；身份匹配仍保留 shadow/diagnostics，不把不确定结果当生产结论。

## 测试与修改

修改字段、匹配、导入预览/回滚、采集 Job、图表或只读聚合时运行轨交、Online MR、Mesh、Repository、API 和 Web parity 测试。

## 生成与清理

导入预览、原始日志、解析库和报告使用 PathResolver/Job/Export 的目录与原子策略；失败时保留审计和原始证据，不静默删除备份。

## 相关文档

参见 [轨道交通无线业务模型](../../../../docs/RAIL_TRANSIT_WIRELESS.md)、[基础资料](../../../../docs/RAIL_TRANSIT_BASE_DATA.md)、[Online MR](../../../../docs/ONLINE_MR_COLLECTION.md) 和 [MESH 规则](../../../../docs/mr_mesh_log_analysis_rules.md)。
