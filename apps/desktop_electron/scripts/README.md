# Electron 构建脚本

本目录编排开发启动、Electron 构建、打包和包级 smoke 检查，负责宿主资源和受管 Backend 的组合，不实现设备或数据库业务。

入口是 `dev.mjs`、`build.mjs`、`package.mjs` 与 `package-smoke.mjs`；依赖由 Electron 项目锁文件管理。修改后执行对应的 `pnpm` 测试、typecheck 或构建，并清理临时产物。
