# 设备管理页面

本目录承载设备列表、设备操作和详情页面的 Web 入口。连接测试、采集、命令和持久化由 Application Service/API/Job Center 提供，Renderer 不直接访问设备。

主要入口为 `DeviceManagementView.vue` 及其测试；新增详情或操作需检查 Feature、权限、表格滚动和 API DTO。运行设备页面定向测试。
