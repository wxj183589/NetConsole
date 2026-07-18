# 流量测试组件

本目录展示 Traffic 任务的执行目标、实时日志、带宽和历史结果，负责图表与状态渲染，不直接连接 Agent 或控制 iPerf/fping。

主要入口为 `ExecutionTargetSelect.vue`、`TrafficLogViewer.vue`、`TrafficRealtimeChart.vue` 等；数据来自 Traffic API/Store。修改字段、单位或状态颜色时运行对应测试。
