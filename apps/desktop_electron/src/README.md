# Electron 源码

本目录包含 Main、Preload 和 shared Bridge 的 TypeScript 源码。Main 只负责窗口/进程生命周期与白名单本机动作，Preload 只暴露受控 API，shared 只放契约和校验。

依赖 `apps/desktop_renderer` 的唯一 Renderer 和 Python Backend；不得新增任意命令、路径或第二套业务 Core。修改后运行 `apps/desktop_electron` 的测试与类型检查。
