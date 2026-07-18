# Electron 测试

本目录覆盖 Main 生命周期、配置、IPC、Preload、安全边界、打包和真实 Backend 契约。测试不应依赖开发机绝对路径或真实设备。

在 `apps/desktop_electron` 使用项目锁定的 Vitest/typecheck/build 命令；临时文件写入测试临时目录，打包 smoke 后清理产物。
