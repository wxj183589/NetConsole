# Mesh 分析组件

本目录承载 Mesh 离线分析的图表组件，负责把已查询的序列数据呈现为 RSSI 等趋势，不在组件内解析原始日志或计算业务结论。

主要入口为 `MeshRssiChart.vue`；数据来自 Mesh API/ViewModel，主题来自统一 ECharts 配置。修改图表字段或语义时运行对应测试并检查空数据和单位。
