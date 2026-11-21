# v1.5.17 Windows 兼容性复审

## 源码与构建检查

- 路径处理集中在 PathResolver/Portable data-root helper；运行路径架构检查 PASS。
- Electron 主进程、Preload 和 Backend manager 的进程回收、端口释放、日志轮转和窗口关闭路径有定向测试覆盖。
- NSIS/Portable 入口、Full-only edition、资源图标、Python Backend 和 Electron 版本来源已纳入构建契约。
- Python compileall、Ruff、Electron/Renderer 构建与最终包 smoke 需在本轮构建阶段再次记录。

## 尚未实机确认

Windows 10 20H2、Windows 11 非管理员安装/UAC、中文用户名/路径、端口占用、防火墙/Defender、升级/卸载数据保留和真实 GUI 启动均未在本轮环境完成实机验收，状态保持 PARTIAL/NOT VERIFIED。
