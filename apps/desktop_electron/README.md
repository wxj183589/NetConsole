# Electron Desktop

本目录是唯一正式桌面外壳，负责 Electron Main、Preload、共享 Bridge 和打包脚本；业务状态、设备访问、数据库和导出仍属于 Python Core/FastAPI，不在这里复制实现。

主要入口由 `package.json` 和 `scripts/` 编排，Renderer 使用 `apps/web`。使用 `pnpm test`、类型检查和项目规定的构建/smoke 命令验证；构建产物不得留在源码目录。

## 用途与边界

本目录是唯一正式 Electron Desktop 外壳，负责窗口、进程生命周期、Preload、安全 Bridge 和打包；设备、数据库、任务和导出业务不在此实现。

## 主要入口

`src/main/` 管理宿主生命周期，`src/preload/` 暴露最小桥接，`src/shared/` 保存契约，`scripts/` 编排开发、构建和打包。

## 依赖关系

依赖 `package.json`/pnpm lock、唯一 `apps/web` Renderer 和 Python Backend；Native Bridge 必须与 Feature Gate、PathResolver 和 shared validation 对齐。

## 数据与状态

窗口与临时会话状态由 Main 管理，业务状态留在 Backend/应用数据目录；Token 不通过 Renderer 返回，源码目录不保存数据库或日志。

## 测试与修改

在本目录执行 Vitest、typecheck、build 和 package smoke。修改 IPC、Preload 或白名单动作时同步更新 shared、Web platform 和安全测试。

## 生成与清理

打包和构建输出写入项目规定的 dist/临时目录；测试临时文件使用临时目录，完成后清理，不提交 node_modules、缓存或安装包。

## 相关文档

参见 [Electron Desktop](../../docs/ELECTRON_DESKTOP.md)、[Native Bridge 契约](../../docs/DESKTOP_NATIVE_BRIDGE.md) 和 [Web 架构](../../docs/WEB_ARCHITECTURE.md)。
