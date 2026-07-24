# AC 管理页面

本目录呈现 AC/FIT-AP 资源、光衰和受控操作页面；业务查询、写操作和任务由 Python Service/API 提供。列车 Mesh-Link 在线监控已归入轨道交通，不得恢复独立 AC 页面。

主要入口为 `AcManagementView.vue` 和对等页面。修改字段或操作流程时检查 API/Store、权限和 Feature key，并运行本目录测试。

页面顶部 AC 写动作只提交 `persist_auto_ap` / `enable_ap_remote_login` 语义 ID，并使用后端动作计划完成固定命令预览、二次确认、任务执行和审计；`confirm_token` 不渲染、不写日志，`localStorage` 只保存 `plan_id`。当前 DTO/确认 client 仍让 Renderer 在内存中接收并回传 Token，这是待收紧的已知边界，不能据现有 UI 测试宣称前端从未接收 Token。动作任务与资源刷新任务使用独立 Store 状态，并按 `target_id` 只锁定当前冲突 AC。

FIT-AP OmniPeek 入口提交当前 AC、勾选 AP UUID、数据源/内容/颜色和稳定 `item_key` 选择，预览走普通 Job，`.nam` 生成走 Export Process；Vue 不生成 XML。行右键菜单使用 `NcDataTable` 的类型安全菜单模型，外部终端只提交 AP、AC 和受控终端类型，Browser 模式禁用，程序路径、启动参数、协议、端口、用户名和密码不得进入 Renderer。H3C FIT-AP 外部终端固定由后端按 Telnet 23 直连生成，不保存、不读取、不传递 FIT-AP 登录凭据。

FIT-AP 资源、配置快照、Radio、历史和 AP 扩展表格使用 `NcDataTable`。FIT-AP 页面原有私有列显隐已由公共列设置替代；排序、筛选、光衰状态、选择和详情操作继续使用原 Store/API 语义。页面不得重新直接声明 `el-table-column` 或私有列宽算法。

AP 点表导入入口归属“轨道交通 / 基础资料”；AC 管理不显示独立“导入 AP 元数据”按钮。FIT-AP 仍可按 MAC 消费共享基础资料关联结果，但不得在 AC 页面建立第二套点表预览或写入流程。

页面卡片、状态、配置文本和原始回显统一消费 `theme/` 的面板、状态和代码语义 Token，不维护固定浅色面板或隐式深色日志主题。

表格展示改动运行本目录 Vitest、公共表格测试、`vue-tsc` 和 `scripts/ui` Guard；真实 AC/FIT-AP 数据和 Electron 多尺寸视觉仍按既有验收边界单独确认。
