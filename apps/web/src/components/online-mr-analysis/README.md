# Online MR 分析图表组件

本目录只负责“车载 MR 收集分析”页面的 ECharts 展示，不解析设备日志、不读取 SQLite，也不判断会话或指标的业务状态。

## 文件

- `OnlineMrAnalysisChart.vue`：渲染 Backend 已归一化的时间序列和切换事件，保留 `null` 断点，并响应主题与容器尺寸变化；Canvas 初始化、DPR、网格、图例、dataZoom、toolbox、Tooltip 和大数据符号策略复用 `../charts/multiSeriesTimeChart.ts`。
- `OnlineMrAnalysisChart.test.ts`：验证空值不补零、事件标记以及图表、ResizeObserver 和主题订阅的卸载清理。

## 边界

- 会话、parsed 数据库状态、分页和能力判断由 Python Application/Query Service 提供。
- 页面只向本组件传入 `OnlineMrMetricSeries`；组件不得直接调用 API 或访问 Electron Bridge。
- 图表卸载时必须释放 ECharts、窗口监听、ResizeObserver 和主题订阅。
- 新图表类型应先复用当前 DTO 与主题 Token；不得在 Renderer 中增加设备版本、采集或解析规则。

定向验证：

```powershell
pnpm --dir apps/web exec vitest run src/components/online-mr-analysis/OnlineMrAnalysisChart.test.ts
```
