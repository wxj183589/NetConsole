# 性能与缓存

范围变化复用已解析 SQLite、AP 位置快照和身份投影，不重新导入或解析原始日志。统计缓存签名包含数据库/WAL、来源、规则、快照和 `exclude_depot/exclude_parking`；风险集合达到上限时不长期保留。图表继续使用 Full/Overview/High、窗口缓存、取消和迟到响应保护。

本轮没有重复生成大规模基准；上一阶段四档合成基准仍记录在 `docs/reports/mesh-analysis-performance-optimization/02_PERFORMANCE_BENCHMARK.md`。本轮新增回归只使用最小合成数据和既有受控 50,000 点图表 payload，未读取真实数据根。

状态：`PERFORMANCE_STATUS=PARTIAL`，不能据此声明现场 SLA。
