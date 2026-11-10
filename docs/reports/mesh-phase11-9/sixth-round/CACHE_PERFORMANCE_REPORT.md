# Cache / Performance Report

## Cold / Warm

| 场景 | 时长 | 完成字段 | Chart | MESH API | SQL |
|---|---:|---:|---:|---:|---:|
| warm-1 | 16,868 ms | 13 | 13 | 1 overview | 0 |
| warm-2 | 16,802 ms | 13 | 13 | 0 | 0 |
| cold-reload | 20,440 ms | 13 | 13 | 6 | 4 |

warm-1 与 warm-2 的图表和数据均完成；warm-2 没有新增 API/SQL。cold reload 重新触发 session、active-build-order、business-summary 和 raw links 等真实查询，raw links 返回 465 条 total、466 条结果项。

## Cache counters

主运行初始 raw cache 为 1 scope / 466 samples / 1 covered interval；最终主运行状态仍为 13 个 metric 完成、metric cache entries=16、raw cache 1 scope。补充 gap 完成状态为 571 samples，说明新增窗口被纳入缓存。缓存 hit、gap miss、HTTP 和 SQL 分别记录在 `final_trace` 与各 action trace 中。

## 边界

性能报告是本机隔离快照上的实测，不是生产数据或真实设备性能承诺；没有为未给定的毫秒阈值强行判定 PASS。

