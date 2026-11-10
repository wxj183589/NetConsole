# Ground Unattended R2 阶段交付

本目录保存用户指定的 Ground R2、R2.1、R2.2、R2.3 实施与验收报告，不保存运行数据库或完整日志。

R2.2 入口：[最终验收](R2_2_FINAL_ACCEPTANCE.md)、[实施前审计](R2_2_HEARTBEAT_AUDIT.md)、[架构](R2_2_ARCHITECTURE.md)、[实施](R2_2_IMPLEMENTATION_REPORT.md)、[测试](R2_2_TEST_REPORT.md)、[性能](R2_2_PERFORMANCE_REPORT.md)、[GUI](R2_2_GUI_ACCEPTANCE.md)、[余项](R2_2_REMAINING_ISSUES.md)。整体 PARTIAL，具体证据和未验收边界以各报告为准。

R2.3 入口：[验收记录](R2_3_ACCEPTANCE.md)、[架构](R2_3_SYSLOG_ARCHITECTURE.md)、[性能](R2_3_SYSLOG_PERFORMANCE.md)、[Raw/Parser](R2_3_RAW_WRITER_PARSER.md)、[Position Engine](R2_3_POSITION_ENGINE.md)、[Heartbeat/fping](R2_3_HEARTBEAT_FPING.md)、[AC 差异同步](R2_3_AC_DELTA_SYNC.md)、[对账](R2_3_RECONCILIATION.md)、[集成测试](R2_3_INTEGRATION_TEST.md)、[长稳](R2_3_LONG_STABILITY.md)、[GUI](R2_3_GUI_ACCEPTANCE.md)、[最终验收](R2_3_FINAL_ACCEPTANCE.md)、[余项](R2_3_REMAINING_ISSUES.md)。R2.3 当前整体 PARTIAL：Syslog 位置链路已有本地实现和定向证据，但正常负载分位数、现场设备、长稳和 GUI 验收未宣称完成。

R2.3.1 入口：[基线记录](r2-3-1/R2_3_1_BASELINE.md)、[本地模拟](r2-3-1/R2_3_1_LOCAL_SIMULATION.md)、[Syslog UDP](r2-3-1/R2_3_1_SYSLOG_UDP_TEST.md)、[Raw/Parser](r2-3-1/R2_3_1_RAW_PARSER_TEST.md)、[位置正确性](r2-3-1/R2_3_1_POSITION_CORRECTNESS.md)、[位置延迟](r2-3-1/R2_3_1_POSITION_LATENCY.md)、[AC 差异](r2-3-1/R2_3_1_AC_DELTA_SYNC.md)、[AC 对账](r2-3-1/R2_3_1_AC_RECONCILIATION.md)、[Heartbeat](r2-3-1/R2_3_1_HEARTBEAT_TEST.md)、[集成](r2-3-1/R2_3_1_INTEGRATION_TEST.md)、[故障注入](r2-3-1/R2_3_1_FAULT_INJECTION.md)、[长稳](r2-3-1/R2_3_1_LONG_STABILITY.md)、[Electron](r2-3-1/R2_3_1_ELECTRON_ACCEPTANCE.md)、[最终验收](r2-3-1/R2_3_1_FINAL_ACCEPTANCE.md)、[余项](r2-3-1/R2_3_1_REMAINING_ISSUES.md)、[机器可读结果](r2-3-1/R2_3_1_TEST_RESULTS.json)。R2.3.1 本地结果为 PARTIAL：本地三链路和位置指标通过，8 小时长稳与可见 GUI 截图未完成，现场验收不可用。
