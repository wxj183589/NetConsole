# Web 公共组件

本目录提供跨页面复用的 Vue 组件和基础交互约束；业务域专属组件放在对应子目录或视图目录。公共组件不得隐藏网络、数据库或长耗时任务。

主要入口包括 `NcCard.vue`、`NcStatusTag.vue`、`NcTable.vue` 等；表格遵守 `docs/ui_table_guidelines.md`。修改后运行组件测试并检查主题、滚动和可访问性。

## 用途与边界

本目录提供跨页面复用的展示组件；业务域专属组件留在对应子目录。组件只消费 props、events、Store 或 API 状态，不隐藏网络、数据库和长耗时任务。

## 主要入口

`NcCard.vue`、`NcStatusTag.vue`、`NcTable.vue` 是公共基元，Mesh、网络工具和 Traffic 组件在各自子目录维护。

## 依赖关系

组件依赖 Vue、Element Plus、统一 Token/主题和类型契约；表格交互遵守 UI 规范，不能反向依赖 Python Service。

## 数据与状态

组件状态限于展示、排序、选择和轻量输入；业务数据来自父级/API/Store，组件不持久化数据库、文件或任务结果。

## 测试与修改

运行组件 Vitest、相关页面测试和必要的 Web build。修改公共 props、事件、列宽或可访问性时同步所有消费者与主题测试。

## 生成与清理

组件不生成运行文件；测试截图/mock 只能进入临时目录，构建物和缓存按前端规则清理，不写回 `src/`。

## 相关文档

参见 [表格规范](../../../../docs/ui_table_guidelines.md)、[UI 设计系统](../../../../docs/UI_DESIGN_SYSTEM.md) 和 `src/theme/`。
