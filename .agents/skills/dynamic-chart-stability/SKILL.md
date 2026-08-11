---
name: dynamic-chart-stability
description: NetConsole ECharts 时间轴动态图的稳定性规范与回归流程。处理 RSSI、Ping/fping、iPerf、Channel Busy、接口速率、Timeline、DataZoom、Tooltip、Resize、KeepAlive、指标切换或沉浸式布局时使用；不适用于静态图、普通表格或与图表无关的 parser。
---

# 动态图稳定性

将动态图当作共享交互基础设施维护。Online MR 与 MESH 图必须保留真实时间缺口、共享 viewport、DataZoom、指针联动和容器生命周期，不用单点 CSS 遮蔽渲染异常。

## 必须遵守

- 先阅读 `apps/desktop_renderer/src/components/charts/multiSeriesTimeChart.ts`、相关图组件、测试和 MESH 历史修复；确认数据、Overlay、Tooltip、Resize 与 viewport 的责任边界。
- 动态时间图初始化显式使用 `createTimeChartInitOptions(..., { useDirtyRect: false })`。Canvas dirty rectangle 在指针、Resize、切换或大量 mark 更新后可能留下白色重绘矩形。
- 一个容器只拥有一个 ECharts instance。挂载时初始化，停用时隐藏交互，卸载时解绑 `ResizeObserver`、事件、主题订阅并 `dispose()`；Resize 只调用 `resize()`，不重置数据或另建实例。
- `setOption` 明确 `replaceMerge`。替换指标至少清理 `series`，同时保留共享 viewport、DataZoom、selectedTime 和 cursorTime；不要用 `chart.clear()` 代替状态恢复。
- `null` 表示真实数据缺口，曲线使用 `connectNulls: false`；不得新增白色 `graphic`、`markArea`、loading mask 或 area overlay 伪装缺口。
- Tooltip 必须轻量、边界可控、不可阻塞图表。优先容器内 HTML Tooltip（`appendToBody: false`、`confine: true`、`pointer-events: none`、有宽高上限）；详细信息放固定分析信息栏或外部受控组件。
- 指标语义由 `metricId` 的公共定义决定，不由页面名、图种或数值大小猜测。Tooltip、Y 轴和固定分析信息栏必须复用同一 formatter：`ping_rtt` 永远为 `ms` 且 Y 轴自适应，`ping_loss` 永远为 `%` 且范围 `0~100`，原始 `rssi` 无单位。新增动态图必须覆盖单位一致性测试。
- 历史反例：Online MR 曾把 Ping RTT Series 错套 Ping Loss Tooltip 与 Percent Axis。禁止同一 metric group 共享单位或 formatter；必须保持 `metricId -> valueField -> unit -> axis -> formatter` 一一绑定，并分别验证 RTT 异常高点与零丢包点。
- 站点/区间背景和选中标记的层级低于业务 series；切换指标、共享指针、Resize、KeepAlive 恢复后检查 stale Overlay 与 tooltip 是否清理。
- 逻辑时间范围与当前渲染范围分开维护；异步查询用 generation/Abort 丢弃迟到响应，不让旧数据覆盖新会话或新 viewport。

## 禁止模式

- 不用 `useDirtyRect: true` 处理交互式时间轴。
- 不把 `appendToBody: true`、无尺寸上限的 HTML Tooltip 或 `width: 100%; height: 100%` 的 Tooltip/Overlay 引入动态绘图区。
- 不用 `connectNulls: true` 掩盖采集缺口，不把 `null` 转成 0，也不通过 traffic-specific CSS 修白块。
- 不在 Resize、Tab/沉浸式切换或 KeepAlive 激活时重复 `echarts.init()`，不遗留旧 canvas 或全局 tooltip。
- 不通过全局删除 `dBm` 改变物理量语义。`rssi`/`mr_rssi`/MESH 原始信号值无单位；只有明确 `*_dbm` 或 `signal_dbm` 字段显示 dBm。

## 必须验证

为共享组件补充 Vitest：空值断点、Tooltip DOM 边界、指标切换无旧 series/graphic、Resize 后尺寸、卸载 dispose、KeepAlive/active 切换和 stale response。对共享时间轴验证 DataZoom、selectedTime、cursorTime 和反向定位仍同步。

至少在 1920x1080 普通与沉浸式窗口检查 RSSI、Ping、业务打流、Channel Busy、接口速率；循环进入/退出沉浸式至少 5 次、切换指标至少 10 次。用 DevTools/脚本确认每个图容器只有一个 canvas，Tooltip 不覆盖绘图区，Canvas 网格在 null gap 后仍存在。

运行相关 Vitest、`pnpm build`、`scripts/architecture/run_all.py` 及 `dynamic-chart-stability` 单门。报告自动化结果与真实桌面/设备验收分开，不把 Guard 或测试通过写成 GUI 已验收。
