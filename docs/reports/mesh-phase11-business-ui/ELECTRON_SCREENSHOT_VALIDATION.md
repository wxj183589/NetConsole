# Electron 截图验证

运行方式：`NETCONSOLE_DEV_PORT=5183 pnpm run dev:codex`。

窗口：实际 NetConsole Electron，在当前 Windows 缩放环境捕获窗口图像（PNG 为 2576×1568，等效高 DPI 桌面窗口）。截图来自真实 Electron 窗口，不是静态设计稿。

## 截图

- [分析会话与工作台概览](screenshots/electron-mesh-session.png)
- [分析概览](screenshots/electron-mesh-session.png)
- [日志解析](screenshots/electron-log-parse.png)
- [AP 情况](screenshots/electron-ap-situation.png)
- [主链路监控](screenshots/electron-main-monitor.png)

辅助导航截图保留在同目录，包含 Electron 启动窗口、轨道交通菜单和 MESH 页面入口。

## 结论

四个工作区已在真实数据会话中可见并可切换；主链路八组趋势逐图完成。严格 1920×1080 固定窗口、多显示器和 125% DPI 尚未作为独立验收门禁执行。
