# UI Design Token

NetConsole 的品牌、状态、字体、间距、圆角、密度和 Shell 尺寸以 `apps/desktop_renderer/src/theme/tokens.css` 为唯一基础事实源，浅色/深色语义值分别由 `light.css` 与 `dark.css` 提供。业务页面不得建立固定主题色或第二套 `--el-*` 变量。

表格测量读取与当前 Renderer 一致的字体：正文默认 `--nc-font-size-base` 和 `--nc-font-family`，表头使用同字号 600 字重。主题、根字体、语言或 DPI 改变时清空测量缓存并重新计算列宽。字段类型宽度不属于视觉 Token，集中维护在 `components/table/columnPresets.ts`。

完整主题层级和 ECharts 规则见 [UI 设计系统](../UI_DESIGN_SYSTEM.md)。
