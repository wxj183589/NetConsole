# 轨道交通页面

本目录承载轨旁 AP、车载 MR、Mesh 分析、基础资料、通信监控和综合看板页面。在线采集与离线分析由 Python Service/Job/导出进程提供。

各页面通过对应 API、Store 和 ViewModel 展示查询或受控操作；修改领域字段、图表或导入流程时运行本目录定向测试并同步专题文档。

`VehicleMrOnlineView.vue` 是列车 Mesh-Link 在线状态的唯一用户入口。页面每列车一行展示 CT/TC 两端，通信详情抽屉展示 MR、当前 AP、MAC、Radio、RSSI、位置、匹配状态、两侧收光和历史；所有状态与匹配结论来自 Python Query Service。旧 `/ac-management/mesh-links` 只做兼容重定向，底层 AC Mesh-Link API 保留为 deprecated 契约。

`RailTransitBaseDataView.vue` 是基础资料唯一入口，默认锁定并通过 revision + Application Service 单事务维护线路参数、站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划。站点来源预览由后端只读读取设备管理“车站”分组的 `station` 字段，页面只把候选或模板预览应用到当前草稿；旧独立规划路由只做兼容重定向，不得恢复重复页面或导航。

基础资料、Online MR、Mesh 原始回显和通信日志均消费共享面板、状态和代码 Token；图表配色只从 `theme/echarts.ts` 读取。轨旁 AP 业务页首次加载才使用整表遮罩，后续刷新保留上一次成功数据；接口简称和光衰中文展示只是 presentation，导出通过 Task/Artifact 和 Runtime Adapter 保存。

`OnlineMrAnalysisView.vue` 始终先读取会话 metadata，再按 `database_summary.status` 局部加载 parsed 指标；缺库、旧库和不可读库不能阻止原始日志或采集日志展示。切换会话必须立即清空全部派生展示缓存，并通过请求 generation/AbortController 丢弃迟到响应。Online MR 与离线 MESH 的解析/重建均进入 Job Center，不在 Renderer 或 FastAPI 请求线程同步运行。

`MeshAnalysisView.vue` 按会话和指标区隔离旧 schema；单个损坏派生库不能拖垮概览。普通导入固定为“显式准备当前局点正式车载 MR → 统一预览 ZIP/LOG/GZ/文件夹 → 自动匹配 CT/CW → 确认导入并分析 → Task 完成后自动打开新来源”，无法匹配时才展开高级内部归属。当前来源重建使用 `mesh_source_rebuild`，raw 缺失但 bundle 可恢复时显示恢复动作；`mesh_schema_rebuild` 仅作为高级 Profile 全量重建。页面不得删除 SQLite 或绕过确认。
