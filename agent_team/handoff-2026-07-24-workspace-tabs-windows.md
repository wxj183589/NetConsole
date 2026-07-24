# 多标签、多窗口与系统托盘交接

- 日期：2026-07-24
- 分支：`feat/workspace-tabs-windows`
- 功能提交：`631e6fcb feat: 支持工作区标签、多窗口与系统托盘常驻`

## 修改内容

- Vue 新增 Pinia 工作区状态、路由身份规范化与受控持久化；支持标签打开、关闭、固定、复制、溢出定位、右键操作及弹出为独立工作区窗口。
- Electron 新增受管工作区窗口、窗口布局恢复、安全 IPC 校验和 Windows TrayController。主窗口默认关闭到通知区域；托盘菜单可恢复主窗口、新建工作区、打开任务中心、同步 Backend/局点状态和设置开关，并由“退出 NetConsole”执行一次受控完整退出。
- 系统设置增加“关闭主窗口后继续驻留通知区域”持久化选项；补充 MESH 等重型页面的 KeepAlive 激活/停用处理。
- 更新 README、Electron/Web 架构、Native Bridge、测试基线与变更日志。

## 验证结果

- Electron 全量 Vitest：25 个文件、159 项通过。
- Electron TypeScript 检查和 Main/Preload 构建：通过。
- Web `vue-tsc -b` 与 Vite 生产构建：通过。
- `node scripts/dev.mjs --smoke --workspace-tray`（端口 5188）：通过；验证附加窗口、关闭主窗口到托盘、Backend 保持 ready、恢复主窗口和明确退出回收。
- `git diff --check`：通过。
- Web 全量 Vitest 曾在单进程运行 60 秒时超时，未作为通过结果；此前本轮全量结果为 112 个文件、546 项通过。

## 遗留事项

- 仍需在真实 Windows 通知区域人工确认托盘图标的可见性、双击恢复、任务中心菜单和“关闭到托盘”设置切换。
- 未修改数据库、用户数据目录、导出内容或后台任务语义；托盘隐藏窗口不会停止 Backend 或业务任务。
