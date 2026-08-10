# 时间图表组件

本目录提供多序列时间图的 ECharts 基础选项、性能阈值、颜色计算和定向测试。

交互式时间图必须遵守项目级 `dynamic-chart-stability` Skill：显式关闭 dirty rectangle，保留 `null` gap，容器只拥有一个 ECharts instance，Resize 只调整尺寸，卸载释放实例；指标替换使用 `replaceMerge` 清理旧 series，并保持共享 viewport/DataZoom。HTML Tooltip 应限制在图表容器内且不可拦截指针，详细信息进入固定分析栏或受控外部组件。

组件只处理图表展示配置；业务数据、采集和持久化由调用方及后端负责。
