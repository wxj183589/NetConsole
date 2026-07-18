# Web 全局样式

## 用途

本目录保存应用外壳和跨页面基础样式。

## 边界

`main.css` 只消费 `--nc-*` Token，不定义固定的浅色或深色外壳色值。业务页面不得在此建立局部主题事实源。

## 主要入口

- `main.css`：侧栏、顶部栏、内容区、滚动条和公共页面骨架。
- `../theme/light.css`、`../theme/dark.css`：颜色、分隔线、滚动条和阴影等语义 Token 的唯一事实源。
- `../theme/element-plus.css`：Element Plus 全局变量和浮层映射。

## 依赖关系

布局和业务组件消费本目录样式；本目录反向依赖 `../theme/` 的 Token，不读取 Store、API 或业务模型。ECharts 统一从 `../theme/echarts.ts` 读取 Token。

## 数据与状态

本目录不持久化主题。系统设置 API 是主题和强调色的唯一持久化来源；`--nc-bg-page`、`--nc-bg-card` 等旧变量只是兼容别名。

## 测试

主题、布局和 Element Plus 映射由 `../theme/*.test.ts`、`../layouts/AppLayout.test.ts` 与架构 Guard 覆盖。

## 修改规则

品牌色和状态原语只在 `../theme/tokens.css` 定义，light/dark 表面色只在对应主题文件定义；布局、组件和业务页不得新增固定主题色或全局 `--el-*` 覆盖。

## 生成与清理

本目录无生成文件；Vite 构建产物进入被忽略的 `apps/web/dist/`，不得回写本目录。

## 相关文档

- [布局边界](../layouts/README.md)
- [UI 设计系统](../../../../docs/UI_DESIGN_SYSTEM.md)
