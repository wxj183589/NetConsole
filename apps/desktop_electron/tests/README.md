# Electron 测试

本目录覆盖 Main 生命周期、配置、IPC、Preload、安全边界、打包和真实 Backend 契约。测试不应依赖开发机绝对路径或真实设备。

在 `apps/desktop_electron` 使用项目锁定的 Vitest/typecheck/build 命令；临时文件写入测试临时目录，打包 smoke 后清理产物。

`artifact-save-integration.test.ts` 使用真实 Preload bridge、Main IPC、受控回环响应和文件系统完成 Artifact 保存闭环。默认目标位于测试临时目录；仅人工验收时可设置绝对路径环境变量 `NETCONSOLE_ARTIFACT_ACCEPTANCE_PATH` 保留结果文件，该变量只由测试读取，生产 Renderer 和 Bridge 不接受测试目标路径。
