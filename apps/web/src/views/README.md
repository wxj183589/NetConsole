# Web 页面视图

本目录按产品模块组织页面组件，负责布局、输入、加载/错误状态和 Store 绑定。页面不直接实现设备采集、数据库访问、命令执行或后台状态机。

各子目录对应 Feature Registry 中的模块/页面；新增用户可见入口需同时更新路由、导航、i18n 和测试。运行 Web 定向测试与构建验证。

## 用途与边界

本目录承载用户可见页面，负责布局、输入、加载/错误状态和 Store 绑定；页面不直接连接设备、SQLite、文件系统、Job Worker 或 Export Process。

## 主要入口

各模块子目录的 `*View.vue` 是页面入口，路由和导航在上级 `router/`、`navigation/` 注册，页面专属模型/词条与视图相邻维护。

## 依赖关系

视图依赖 API 客户端、Pinia Store、共享组件、类型和 Feature/i18n；长耗时执行由 FastAPI/Application Service/Job Center 提供。

## 数据与状态

视图只消费 API/Store 的 DTO、事件和轻量 UI 状态；数据库、原始日志、会话目录和正式报告由 Python 数据根管理。

## 测试与修改

运行对应 View 的 Vitest、API/Store 测试和 `pnpm build`。新增动作、Tab 或页面必须登记 Feature key、i18n、权限/状态和空数据行为。

## 生成与清理

页面不生成持久文件；导出、下载和清理按钮只调用受控 API，测试/构建产物留在临时或忽略目录并按脚本清理。

## 相关文档

参见 [功能模块](../../../../docs/FEATURE_MODULES.md)、[表格规范](../../../../docs/ui_table_guidelines.md) 和 [Web 架构](../../../../docs/WEB_ARCHITECTURE.md)。
