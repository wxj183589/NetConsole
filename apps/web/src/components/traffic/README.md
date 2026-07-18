# 流量测试组件

本目录展示 Traffic 任务的执行目标、实时日志、带宽和历史结果，负责图表与状态渲染，不直接连接 Agent 或控制 iPerf/fping。

主要入口为 `ExecutionTargetSelect.vue`、`TrafficLogViewer.vue`、`TrafficRealtimeChart.vue` 等；数据来自 Traffic API/Store。修改字段、单位或状态颜色时运行对应测试。

`TrafficRunHistory.vue` 使用 `NcDataTable` 展示任务、执行端、状态、时间和原有详情/停止/重试动作。表格迁移不改变 Traffic 状态、参数、Agent 映射或 iPerf/fping 执行语义。
