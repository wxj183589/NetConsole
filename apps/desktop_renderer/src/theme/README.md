# Web 主题与图表语义

本目录是 NetConsole 明暗主题、强调色、Element Plus 和 ECharts 视觉语义的唯一事实源。它只负责视觉系统，不改变业务状态、设备能力或数据含义。

## 事实源与边界

- `tokens.css`：品牌/状态原语、间距、密度和流式内容容器 Token。
- `light.css`、`dark.css`：页面、侧栏、面板、代码/日志、文字、边框、阴影和滚动条的明暗语义值。
- `element-plus.css`：全局 `--el-*` 到 `--nc-*` 的唯一映射；业务页不得单独覆盖基础 Element Plus 主题变量。
- `theme.ts`：`light`、`dark`、`auto` 的解析、系统主题监听、主题变更事件和严格桌面主题报告。
- `echarts.ts`：ECharts 文字、网格、Tooltip、背景和系列色的事实源。仓库没有单独的 `charts/theme/` 目录，新增图表继续复用本文件，禁止复制第二套图表主题。

系统设置 API 是主题与强调色的唯一持久化来源，Pinia 和 `localStorage` 不保存第二份主题。Electron 启动先显示跟随操作系统配色的只读加载页；Renderer 加载真实系统设置后只上报解析后的 `light`/`dark`，Main 再同步窗口背景。安全浅色只用于 Browser 首屏或设置读取失败，不得作为 Electron 已保存主题提前上报。

业务 Vue/CSS 的 `background`、`color`、`border` 和 `box-shadow` 必须消费语义 Token。品牌、状态或图表确需字面量时，只能登记到架构 Guard 的精确受控清单；当前清单为空。修改颜色、密度或图表状态时运行主题定向测试和 `check_ui_business_logic.py`。
