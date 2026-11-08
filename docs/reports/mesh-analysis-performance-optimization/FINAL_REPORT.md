# Mesh 原始日志分析专项报告

日期：2026-11-08；Agent：codex-A。分支 `codex-A/mesh-analysis-performance-optimization`；比较基线 `37b0df95a3208d0d03380e76ccfe5419af1422f1`。本专项只本地提交，不 Push、不合并、不发布。

## 实现与业务结果

1. Peer 质量对 segments、switch-in/out 和 flap 一次建立索引，消除每个 Peer 重扫；保留原 Radio 作用域、跨 Radio flap、排序、阈值及事件口径。原 Parser、日志格式、ProcessPoolExecutor 和 worker 策略保留。
2. 完整来源按物理 AP MAC 统计唯一 ACTIVE 的正有限 MR RSSI：平均/最低/最高/P10、有效/弱样本数量及比例、首末时间。多 Radio 归并；名称不作身份主键；Alias/历史投影冲突进入未识别，保留 Peer 证据。缺样本为数据不足。
3. 新分级使用任务覆盖 > Site默认 > 原规则资源，nullable阈值继承；不改全局资源。P10沿用原RSSI单位及good/warning边界，新分级独立于原质量评分。导出创建前校验并冻结参数和身份快照。
4. 单链路复用 build_sample_quality：唯一ACTIVE且available_backup_count=0，与LinkCnt无关。无STANDBY、弱STANDBY、STANDBY缺RSSI分开；按来源/Radio/AP/类型/缺口合并区段，保留源行及时间。新增区段数不等于原达到时长门槛的NO_BACKUP事件数。
5. 新增摘要、AP筛选排序分页、单链路分页API，保留旧ap-statistics。单session缓存包含DB/WAL、来源、有效参数规则及身份快照；>=10k风险区段不缓存。七卡点击才加载明细，Abort/旧响应保护，失败保留有效内容。
6. XLSX默认业务模式、可选完整诊断模式。默认视图移出重复身份匹配字段及noise/rate/CPU/Retry等技术列，未识别Peer证据保留。新增AP/风险表和规则追溯，中文表头、冻结、筛选、列宽和百分比样式保留。原始导出完整，明细和raw Writer支持ZIP64。
7. <=50k首开full，大/未知数据overview，局部缩放high，显式full保留。复用现有LOD、窗口、预算、缓存、取消、generation、极值/事件/缺口及可见性初始化。业务统计不取图表采样结果。

## 性能与验证

[02_PERFORMANCE_BENCHMARK.md](02_PERFORMANCE_BENCHMARK.md) 记录同机50k/200k/500k/1M的解析、完整质量、Peer、查询、业务统计、核心导出、Payload和三个浏览器视口组件首屏及峰值内存。全部合成数据、各项独立进程单轮，不能推导稳定SLA或现场端到端性能。

百万合成记录：完整质量分析18.354→13.386s，Peer阶段3.725→1.162s；图表Payload 6,837,768→1,572,262 bytes（减少77.0%）；1920×1080组件首屏1120.7→360.7ms。50万业务核心导出184.507→123.750s，文件79,575,141→30,672,422 bytes。均为单轮特定fixture，导出列模式和新增统计不同。

四档完整质量报告摘要仅排除生成时间后前后一致。Parser未改，前后摘要一致只证明该fixture重复结果。非零NO_BACKUP/乒乓、多Radio、异常及阈值边界另由定向回归覆盖。最终定向、浏览器和Full Gate实际结果见 [07_REGRESSION_TESTS.md](07_REGRESSION_TESTS.md)。

百万基线诊断导出触发ZIP32 FileSizeError，失败耗时不用于成功导出的加速比。当前支持ZIP64；结构/行数验证与原生Excel/WPS GUI分别报告。

## 主要修改文件

|范围|文件（仓库相对路径）|
|---|---|
|计算|`src/netconsole/services/mesh_quality_analysis.py`、`src/netconsole/services/mesh_business_statistics.py`|
|参数/查询|`src/netconsole/models/mesh_analysis_params.py`、`src/netconsole/services/mesh_analysis_params_service.py`、`src/netconsole/services/rail_transit/mesh_analysis_query_service.py`|
|API/契约|`src/netconsole/models/api/mesh_analysis.py`、`src/netconsole/backend/api/mesh_analysis_router.py`、`src/netconsole/application/rail_transit/web_application_service.py`、`src/netconsole/core/feature_registry.py`|
|登记/模板|`config/architecture/direct_sql_access.yaml`、`config/storage_registry.yaml`、`config/profiles/features/full.json`、`config/profiles/features/customer.json`|
|报告/导出|`src/netconsole/services/mesh_analysis_report.py`、`src/netconsole/services/mesh_analysis_excel_report.py`、`src/netconsole/services/mesh_link_detail_export.py`、`src/netconsole/export_worker.py`|
|Renderer|`apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.vue`、MeshBusinessSummary/MeshBusinessParams/meshLoadingPolicy、API/types/i18n文件|
|测试/复现|`tests/test_mesh_business_statistics.py`、既有Mesh report/web与export identity测试、Renderer policy/summary/view/API测试、Mesh visual fixture/spec、`scripts/maintenance/benchmark_mesh_business.py`|
|文档|本目录8份报告与README、`docs/reports/README.md`、`docs/README.md`、`docs/rail-transit/mesh/ANALYSIS_RULES.md`、`docs/CHANGELOG.md`；`tests/test_project_docs_layout.py`固定交付路径精确例外|

精确文件清单由最终本地Git commit追踪，不提交数据库、大日志、临时导出和本地配置。

## 兼容与未验收边界

无schema迁移或原始数据改写；明确列游标兼容旧optional identity列及metrics_json，缺物理身份进入未识别。旧API、原始导出、导入/扫描/重新解析/删除来源操作链保留。没有访问、复制或写入 `D:\NetConsoleData` / `D:\NetConsoleData-dev`，没有设备写操作。

Parser/quality/report和建链列表仍随输入增长；AP histogram、身份缓存、风险集合仍物化，不能称全链路恒定内存。分页在完整聚合结果上由SQLite执行，不是原始链路SQL聚合。性能fixture没有风险区段，不能代表最坏情况。

真实脱敏大日志、完整Electron用户流程、Windows原生125%DPI、Excel/WPS GUI、正式制品及长稳未验收。浏览器组件及deviceScaleFactor1.25不能替代上述验收。未来合并main后须在最终集成commit重跑L4 Full Gate。

初次Full Gate的完整Python为5554 passed / 9 failed / 2 skipped，9个失败节点修复后集中复验全部通过；完整Renderer重跑1409通过。没有在修复后重跑整套Full Gate，不宣称最终完整门禁全绿；原始失败与修复复验分别保留，详见07。

两处可重建的合成基准目录因自动审批拒绝删除（`blocked by policy`）而保留，未改用其它手段绕过：`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-business-90d08ddfc2614846b8ba207d984400e6`、`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-business-5a2c32e42f7f42f08d410ca71ac94419`。仅登记后续受控清理，不包含真实数据副本。

## 状态

|状态项|结果|说明|
|---|---|---|
|IMPLEMENTATION_STATUS|PASS|专项功能及复现工具已实现|
|TEST_STATUS|PARTIAL|初次Full Gate失败项定向复验通过，未整套重跑；真实及原生验收留有缺口|
|DATA_COMPATIBILITY_STATUS|PARTIAL|无迁移、旧schema fixture回归；真实历史库未读取|
|PERFORMANCE_STATUS|PARTIAL|四档合成单轮；缺真实脱敏数据及重复统计|
|EXPORT_STATUS|PARTIAL|业务/诊断、结构/行数验证；原生GUI未验收|
|CHART_STATUS|PARTIAL|加载策略与组件验证；Electron/原生DPI未验收|
|AP_QUALITY_STATUS|PASS|完整数据、物理身份、RSSI/阈值/置信度规则及回归|
|SINGLE_LINK_STATUS|PASS|复用备链语义，区段及追溯回归|
|GIT_STATUS|PASS|本报告随专项代码本地提交，提交号见交付清单与DevStatus；未Push/Merge/Release|
