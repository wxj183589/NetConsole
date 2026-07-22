# AC 管理页面

本目录呈现 AC/FIT-AP 资源、光衰和受控操作页面；业务查询、写操作和任务由 Python Service/API 提供。列车 Mesh-Link 在线监控已归入轨道交通，不得恢复独立 AC 页面。

主要入口为 `AcManagementView.vue` 和对等页面。修改字段或操作流程时检查 API/Store、权限和 Feature key，并运行本目录测试。

页面顶部 AC 写动作只提交 `persist_auto_ap` / `enable_ap_remote_login` 语义 ID，并使用后端动作计划完成固定命令预览、二次确认、任务执行和审计；`confirm_token` 不渲染、不写日志。动作任务与资源刷新任务使用独立 Store 状态，并按 `target_id` 只锁定当前冲突 AC。

FIT-AP OmniPeek 入口只提交当前 AC 和勾选 AP UUID，预览走普通 Job，`.nam` 生成走 Export Process；Vue 不生成 XML。行右键菜单复用 `NcDataTable` 的 `row-contextmenu`，外部终端只提交 AP、AC 和受控终端类型，Browser 模式禁用，程序路径、启动参数和凭据不得进入 Renderer。

FIT-AP 资源、配置快照、Radio、历史和 AP 扩展表格使用 `NcDataTable`。FIT-AP 页面原有私有列显隐已由公共列设置替代；排序、筛选、光衰状态、选择和详情操作继续使用原 Store/API 语义。页面不得重新直接声明 `el-table-column` 或私有列宽算法。

页面卡片、状态、配置文本和原始回显统一消费 `theme/` 的面板、状态和代码语义 Token，不维护固定浅色面板或隐式深色日志主题。

表格展示改动运行本目录 Vitest、公共表格测试、`vue-tsc` 和 `scripts/ui` Guard；真实 AC/FIT-AP 数据和 Electron 多尺寸视觉仍按既有验收边界单独确认。
