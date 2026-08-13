# Desktop Renderer 源码

本目录按 API、组件、导航、平台适配、状态、类型、视图和主题组织 Vue Renderer。各子目录只负责前端表现与调用契约，不直接连接 SQLite、设备或执行后台任务。

主要入口为 `App.vue`、`main.ts` 和相邻的路由/导航注册。修改用户可见页面、Tab 或动作时检查 Feature Registry 与 i18n，并运行 Desktop Renderer 测试和构建。

## 用途与边界

这里按 API、组件、导航、平台、状态、类型、工具、主题和视图划分 Renderer 源码。各层只处理展示和调用契约，不实现设备、数据库、采集或后台状态机。

## 主要入口

`App.vue`、`main.ts`、`router/` 和 `navigation/` 组成页面启动链；业务入口位于 `views/`，共享状态位于 `stores/`。

## 依赖关系

API 客户端依赖 FastAPI DTO，Store 依赖 API 和类型，视图依赖 Store/组件，platform 依赖 Electron shared Bridge 或 Browser adapter；禁止反向放入 Python 业务逻辑。

## 数据与状态

页面状态、筛选和事件游标保存在 Pinia/组件内存；服务端数据库、任务、文件和会话数据不在 Renderer 持久化。

## 测试与修改

按子目录运行 Vitest，并在 `apps/desktop_renderer` 运行 `pnpm build`。用户可见变更需同时检查 Feature key、i18n、主题、滚动和可访问性。

## 生成与清理

不在 `src/` 生成构建物、报告或缓存；Vite/测试输出按前端配置写入忽略目录，调试数据使用临时目录。

## 相关文档

参见 [Electron Desktop 架构](../../../docs/architecture/RUNTIME.md)、[表格规范](../../../docs/ui/TABLE_GUIDELINES.md) 和 [UI 设计系统](../../../docs/ui/DESIGN_SYSTEM.md)。
