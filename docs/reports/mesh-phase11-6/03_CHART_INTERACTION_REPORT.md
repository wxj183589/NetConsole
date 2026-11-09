# Phase 11.6 图表交互报告

## 当前契约

| 操作 | 当前行为 | 证据 |
|---|---|---|
| 普通滚轮 | MeshMetricChart 不 preventDefault，页面保留自然滚动 | MetricChart wheel test |
| Shift+滚轮向上 | 以鼠标所在时间为中心缩小时间窗口 | wheel/viewport test |
| Shift+滚轮向下 | 放大时间窗口，边界限制在完整 domain | wheel/viewport test |
| dataZoom/slider | 转换为真实毫秒范围并向 Workbench 提交共享 window | datazoom tests |
| 普通指针 | 更新共享 pointer，不发数据库请求 | pointer tests |
| 双击 Tooltip/绘图区 | 无固定时发出固定时间选择；已有固定时清除 | 本轮新增 dblclick test |
| Esc | 发出 selection-clear | existing keyboard test |
| ECharts finished | render-complete 只在真实 finished 后发出 | lifecycle test |
| resize | 复用同一实例，只调用 resize | lifecycle test |
| dispose | 清理监听、Observer、主题订阅并 dispose | lifecycle test |

## 多图联动

MeshPhase11Workbench 维护一个 domain/window/pointer/selectedTime；每张 MeshMetricChart 通过 props 同步，datazoom 由父级合并并重新查询。指标按可见范围和 240px rootMargin 懒加载，counter 子图复用一次 counters 查询。单图错误和完成状态存放在独立 statuses[key]，不会阻塞其它图。

主页面仍同时保留 legacy RSSI、轨旁信号和 Phase 11 Workbench；本报告没有把 Workbench 自动化误报为完整 legacy/真实 Electron 验收。legacy RSSI/Busy/Trackside 组件已有自己的双击固定和生命周期测试。

## 本轮修复风险

- ECharts 双击事件可能由点或空白区域触发；数据点优先使用 data.value，空白区域回退到原生鼠标事件像素转换。
- 当前选择清除由父级 selectionActive 驱动；若父级尚未提交新的 props，不会把无效时间写入状态。
- 没有真实 Chromium Tooltip 像素、触控板惯性和窗口滚动证据，维持 GUI_PENDING。

## 自动化覆盖

MeshMetricChart.test.ts 当前 20/20 通过；Workbench、指标组、Tooltip、挂载和 viewport 测试另见 08。
