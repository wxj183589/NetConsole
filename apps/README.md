# 应用目录

本目录承载 NetConsole 的三个应用边界：Windows Go Agent、Electron Desktop 外壳和 Vue Desktop Renderer。应用之间通过既有 HTTP/API、Electron Bridge 与共享 Python Core 协作；这里不放 SQLite、日志、采集结果或正式报告。

主要入口分别位于 `agent/`、`desktop_electron/` 和 `desktop_renderer/`。各应用使用自己的锁定依赖和测试命令，跨应用改动还要回看 `docs/ARCHITECTURE.md` 的边界。

验证使用对应子目录的 Go、pnpm 或 Electron 测试；运行数据写入 `.local/` 或系统应用数据目录，清理只按项目维护脚本和白名单执行。

## 用途与边界

这里是 Agent、Electron Desktop 和 Vue Desktop Renderer 三个应用的物理边界。应用不得复制 Python Core、建立第二套 Renderer，或把数据库、日志、采集结果写入源码目录。

## 主要入口

入口分别是 `agent/`、`desktop_electron/` 和 `desktop_renderer/`；每个应用的 package/module 配置和启动脚本位于自己的子目录。

## 依赖关系

Agent 使用 Go module，Desktop 外壳使用 Electron/pnpm，Desktop Renderer 使用 Vue/Vite/pnpm；两者通过受控 Bridge/API 连接 Python Backend。

## 数据与状态

应用状态和任务数据由 Python Core、Agent 数据根或系统应用数据目录承载；应用源码只保存版本化配置和静态资源。

## 测试与修改

按应用执行对应 Go、pnpm、typecheck 和 smoke 测试。跨应用改动必须同时检查 API、Bridge、Feature Registry 和 `docs/ARCHITECTURE.md` 的边界。

## 生成与清理

前端构建物、Electron 打包物和 Agent 构建物分别写入规定的 dist/临时目录，不提交；清理由项目脚本和白名单负责。

## 相关文档

参见 [当前架构](../docs/ARCHITECTURE.md)、[仓库目录规范](../docs/development/repository-layout.md) 和各应用 README。
