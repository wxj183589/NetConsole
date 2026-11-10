# Phase 11.6 实施报告

## 结论

本轮完成一次从 Phase 9 到 Phase 11.5 的代码、API、Parser、导出、图表和 DevStatus 追溯审计，并修复一个已确认的交互缺口：统一工作台的 MeshMetricChart 之前只有 Shift/Ctrl 时间选择，未响应任务书要求的 Tooltip 双击固定/再次双击解除固定。

## 实施内容

- 在 MeshMetricChart.vue 注册 ECharts dblclick 监听。
- 双击已有数据点时使用数据时间；双击空白绘图区时使用原生鼠标事件和像素时间转换。
- 无固定选择时发出 time-select(time, true)；已有固定选择时发出 selection-clear。
- 卸载时解绑 dblclick，和现有 wheel、click、datazoom、finished、ZRender、ResizeObserver、主题订阅一起清理。
- 保留原有 Shift/Ctrl 选择、普通滚轮页面滚动、Shift 滚轮共享 viewport、ECharts finished 渲染完成边界。
- 增加回归用例覆盖双击固定、第二次双击清除和卸载监听清理。

## 未修改范围

- 未修改 Parser 字段语义、SQLite schema、API DTO、AP Identity、导出列契约或设备逻辑。
- 未重写已通过测试的 Trackside AP 稳定颜色分配。
- 未访问或复制 D:\NetConsoleData、D:\NetConsoleData-dev，未执行数据库/设备写入。

## 主要文件

- apps/desktop_renderer/src/components/mesh-analysis/MeshMetricChart.vue
- apps/desktop_renderer/src/components/mesh-analysis/MeshMetricChart.test.ts
- docs/reports/mesh-phase11-6/

## 影响与兼容性

该变更触及 MESH 共享图表组件，按 L3 动态图表共享契约处理。消费者是 Phase 11 工作台的所有指标图，以及使用该组件的 MESH 详情布局。没有改变 API、数据、缓存键或导出格式。未知/缺失时间不触发选择，避免制造虚假时间点。

## 验收边界

自动化结果见 08_REGRESSION_REPORT.md。真实 Electron、Windows 原生 125% DPI、Excel/WPS GUI、30 分钟长稳和慢查询故障注入仍不能从本轮自动化推导，最终状态为 PARTIAL_WITH_BLOCKERS。
