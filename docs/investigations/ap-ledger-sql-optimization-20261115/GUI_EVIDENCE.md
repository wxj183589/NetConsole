# GUI 证据

本轮未启动 Electron、未连接真实 Backend、未执行 Playwright/桌面截图，因此没有可宣称的现场 GUI 通过证据。

已完成的静态/编译级证据：

- Renderer `vue-tsc -b --pretty false`：`PASS`；
- Renderer Vitest：209 个测试文件、1537 个测试通过；
- AP 页面已加入交换机、端口、建设阶段、来源类型筛选和站点/交换机/端口排序选项；
- AP 表格已展示交换机、端口、建设阶段和来源类型列。

本轮 GUI 状态：`NOT VERIFIED`。下一步需在隔离真实开发数据 Authority 上完成窗口启动、基础资料查询、筛选/排序、导出和 AC 离线回退截图，再单独记录 `GUI_PASS` 或 `GUI_BLOCKED`。
