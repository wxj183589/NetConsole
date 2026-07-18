# AC 管理页面

本目录呈现 AC/FIT-AP 资源、Mesh-Link、光衰和受控操作页面；业务查询、写操作和任务由 Python Service/API 提供。

主要入口为 `AcManagementView.vue`、`AcMeshLinkView.vue` 和对等页面。修改字段或操作流程时检查 API/Store、权限和 Feature key，并运行本目录测试。

FIT-AP 资源、配置快照、Radio、历史、Mesh-Link 监控/详情、AP 扩展和规划共 11 张表已使用 `NcDataTable`。FIT-AP 页面原有私有列显隐已由公共列设置替代；排序、筛选、光衰状态、选择和详情操作继续使用原 Store/API 语义。页面不得重新直接声明 `el-table-column` 或私有列宽算法。

页面卡片、状态、配置文本和原始回显统一消费 `theme/` 的面板、状态和代码语义 Token，不维护固定浅色面板或隐式深色日志主题。

表格展示改动运行本目录 Vitest、公共表格测试、`vue-tsc` 和 `scripts/ui` Guard；真实 AC/FIT-AP 数据和 Electron 多尺寸视觉仍按既有验收边界单独确认。
