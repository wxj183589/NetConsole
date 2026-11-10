# Phase 11.9 架构审计

审计基线：`3eed9e87`。滚轮经 MeshMetricChart 的 viewport-change 到工作台 setWindow，取消当前 generation，180ms 后 loadMain。loadMain 对可见图调用 loadMetric，并调用 loadRecords、loadHistory；存在选择点时还调用 locateTime。

指标请求通过 links API 的 metric_group 参数执行，busy 和 counters 各由多张图共享精确查询键；RSSI、CPU、Memory、busy、Rate、Noise、TxDesFreeCnt、counters 共八组。后端 list_links 执行计数和排序查询，select_monitor_rows 先计算计数器差分，再保留边界和极值。响应可能降采样，不能代表完整原始采样。

建链请求使用 active-build-order；历史请求使用 links 分页；时间定位使用 links 的 nearest_time，后端补查计数器上下文。此前 Electron 记录中 300 秒缩到 240 秒产生 RSSI、CPU、Memory、active-build-order、history、nearest 六次请求，见 Phase 11.8 的 12_ELECTRON_WHEEL_ACCEPTANCE.md。

原缓存按会话、指标和完整查询参数的精确窗口保存，窗口变化后无法命中；右侧索引仅在 counters 响应完整时构建。所有图使用工作台同一窗口，数据组按指标构建。懒加载和重新进入仍由工作台生命周期管理。
