# Vue Web Renderer

本目录是 NetConsole 唯一 Vue 3 + TypeScript + Vite Renderer，负责布局、输入、轻量校验、状态绑定和可视化。设备、数据库、采集和后台状态机必须通过 FastAPI/Application Service 使用。

入口由 `package.json`、`vite.config.ts` 和 `src/` 组成。依赖使用 pnpm 锁文件；在此目录运行 `pnpm test` 与 `pnpm build`，构建目录和缓存不提交。

## 用途与边界

本目录是唯一 Vue Renderer，负责页面布局、输入、轻量校验、Store 绑定和可视化；不得直接访问设备、SQLite、文件系统或启动长耗时进程。

## 主要入口

`src/main.ts` 启动应用，`src/App.vue` 提供根布局，`src/router/`、`src/navigation/` 和各 `views/` 组织页面入口。

## 依赖关系

依赖 Vue 3、TypeScript、Vite、Element Plus、Pinia、ECharts 和 FastAPI API；Electron 能力只能通过受控 platform adapter/Bridge 使用。

## 数据与状态

API 响应和用户交互状态由 `src/api/`、`src/stores/` 和类型契约承载；持久业务数据仍由 Python PathResolver/Repository 管理。

## 测试与修改

在此目录执行 `pnpm test` 与 `pnpm build`。新增页面、Tab 或动作前更新 Feature Registry、路由、导航、i18n、Store/API 类型和测试。

## 生成与清理

Vite 输出、缓存和依赖目录不得提交；测试临时数据使用测试框架临时目录，构建失败后按前端脚本清理。

## 相关文档

参见 [Web 架构](../../docs/WEB_ARCHITECTURE.md)、[表格规范](../../docs/ui_table_guidelines.md) 和 [UI 设计系统](../../docs/UI_DESIGN_SYSTEM.md)。
