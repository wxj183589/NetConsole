# Mesh 分析专项交付

本目录及八份文件名由用户明确指定。报告对应 `codex-A/mesh-analysis-performance-optimization` 分支与基线 `37b0df95`，记录实现和测试证据；当前业务规范见 [MESH 分析规则](../../rail-transit/mesh/ANALYSIS_RULES.md)。

1. [架构审计](./01_ARCHITECTURE_AUDIT.md)
2. [性能基准](./02_PERFORMANCE_BENCHMARK.md)
3. [AP 信号质量](./03_AP_SIGNAL_QUALITY.md)
4. [单链路分析](./04_SINGLE_LINK_ANALYSIS.md)
5. [Excel 导出优化](./05_EXCEL_EXPORT_OPTIMIZATION.md)
6. [图表分段加载](./06_CHART_LAZY_LOADING.md)
7. [回归测试](./07_REGRESSION_TESTS.md)
8. [最终报告与状态](./FINAL_REPORT.md)

只记录合成 fixture 和本地验收结论；真实数据、原生 DPI、Electron、Excel/WPS GUI、发布与现场设备验收的缺口以最终报告为准。大型证据和临时输出不入 Git。
