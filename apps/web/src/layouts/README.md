# Web 布局

## 用途

本目录保存 Vue 应用外壳、导航结构和响应式布局。

## 边界

`AppLayout.vue` 只负责外壳结构、导航状态和响应式折叠，不判断设备业务、light/dark 颜色或系统设置持久化。

## 主要入口

- `AppLayout.vue`：Logo、一级/二级导航、顶部栏、内容区和窄屏抽屉。
- `AppLayout.test.ts`：路由、菜单状态和主题 Token 契约。

## 依赖关系

布局读取 Navigation Registry 和 i18n；颜色统一由 `../styles/main.css` 消费 `../theme/` Token。

## 数据与状态

仅用命名明确的浏览器存储键保存侧栏折叠和展开组，不保存主题、凭据或业务任务状态。

## 测试

修改后运行 `pnpm exec vitest run src/layouts/AppLayout.test.ts`，并在最终集成运行 Vue 全量测试与构建。

## 修改规则

Element Plus 菜单变量只允许保留在 `.app-menu` 与弹出菜单作用域，且必须引用 `--nc-*` Token；浅色主题不得恢复固定深蓝侧栏。

## 生成与清理

本目录无生成文件和运行数据。

## 相关文档

- [全局样式](../styles/README.md)
- [Web 架构](../../../../docs/WEB_ARCHITECTURE.md)
