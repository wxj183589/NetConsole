# AC 管理页面

本目录呈现 AC/FIT-AP 资源、Mesh-Link、光衰和受控操作页面；业务查询、写操作和任务由 Python Service/API 提供。

主要入口为 `AcManagementView.vue`、`AcMeshLinkView.vue` 和对等页面。修改字段或操作流程时检查 API/Store、权限和 Feature key，并运行本目录测试。

页面卡片、状态、配置文本和原始回显统一消费 `theme/` 的面板、状态和代码语义 Token，不维护固定浅色面板或隐式深色日志主题。
