# 轨道交通页面

本目录承载轨旁 AP、车载 MR、Mesh 分析、基础资料、通信监控和综合看板页面。在线采集与离线分析由 Python Service/Job/导出进程提供。

各页面通过对应 API、Store 和 ViewModel 展示查询或受控操作；修改领域字段、图表或导入流程时运行本目录定向测试并同步专题文档。

`VehicleMrOnlineView.vue` 是列车 Mesh-Link 在线状态的唯一用户入口。页面每列车一行展示 CT/TC 两端，通信详情抽屉展示 MR、当前 AP、MAC、Radio、RSSI、位置、匹配状态、两侧收光和历史；所有状态与匹配结论来自 Python Query Service。旧 `/ac-management/mesh-links` 只做兼容重定向，底层 AC Mesh-Link API 保留为 deprecated 契约。

`RailTransitBaseDataView.vue` 是基础资料唯一入口，默认锁定并通过 revision + Application Service 单事务维护线路参数、站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划。站点来源预览由后端只读读取设备管理“车站”分组的 `station` 字段，确定性移除 1～3 位辅助顺序前缀，并按规范站名与节点类型匹配既有资料；页面只把选中候选或四工作表 XLSX 模板预览应用到当前草稿，覆盖匹配项时保留既有节点身份、引用和人工字段。多轨道设施、中心里程和端点延伸都随草稿统一保存。AP 点表也只从本页进入统一预览、非空字段合并、审计和回滚，`ap_switch_port_point_table` 允许缺少里程并跳过 MAC 为 `-` 的空端口行；AC 管理不得恢复独立导入入口。区间生成只向后端提交当前站点/区间草稿并展示双向与端点预览，人工区间、冲突项和默认保留的过期自动区间不得在前端被静默覆盖或删除。轨旁 AP 规划使用逐站编辑表和只读上线情况概览；规划 AP 总数量由用户维护，实际上线按稳定 `station_id` 汇总当前项目有效 FIT-AP，参考资料记录数不得作为上线率分母或覆盖规划值。轨旁 AP 业务页面、业务导出和概览复用同一范围服务，按项目/显式建设阶段、在用状态与稳定身份过滤去重，排除项可查看；规划为 `0` 或超规划时比例显示 `—`。规划模板只有 `AP规划` 8 列，当前导出另附只读 `AP上线情况概览`；导入只消费 `AP规划`，模板与当前导出不得重新合并为同一种文件。旧 VLAN 分组 API 与表只作兼容，不得恢复分组页面。旧独立规划路由只做兼容重定向，不得恢复重复页面或导航。

轨旁 AP 表格将 AC 当前真实名称与项目点位编号分开显示：名称来自运行态 `fit_ap_name`，点位编号来自基础资料 `point_code`。FIT-AP 按规范化 MAC 唯一关联；基础资料提供“导出重命名命令”，仅通过任务中心生成受控 TXT Artifact，不执行设备命令，并支持未保存草稿的明确选择。

基础资料、Online MR、Mesh 原始回显和通信日志均消费共享面板、状态和代码 Token；图表配色只从 `theme/echarts.ts` 读取。轨旁 AP 业务页首次加载才使用整表遮罩，后续刷新保留上一次成功数据；接口简称和光衰中文展示只是 presentation，导出通过 Task/Artifact 和 Runtime Adapter 保存。

`OnlineMrAnalysisView.vue` 始终先读取会话 metadata，再按 `database_summary.status` 局部加载 parsed 指标；缺库、旧库和不可读库不能阻止原始日志或采集日志展示。切换会话必须立即清空全部派生展示缓存，并通过请求 generation/AbortController 丢弃迟到响应。Online MR 与离线 MESH 的解析/重建均进入 Job Center，不在 Renderer 或 FastAPI 请求线程同步运行。

`MeshAnalysisView.vue` 按会话和指标区隔离旧 schema；单个损坏派生库不能拖垮概览。普通导入固定为“显式准备当前局点正式车载 MR → 统一预览 ZIP/LOG/GZ/文件夹 → 自动匹配 CT/CW → 确认导入并分析 → Task 完成后自动打开新来源”，无法匹配时才展开高级内部归属。当前来源重建使用 `mesh_source_rebuild`，raw 缺失但 bundle 可恢复时显示恢复动作；`mesh_schema_rebuild` 仅作为高级 Profile 全量重建。页面不得删除 SQLite 或绕过确认。
