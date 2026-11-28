# Phase 5.1 线路数据验收

HZL10 既有隔离归档用于只读 SQL 测量。相同 10 分钟范围前后返回 2,022 条且顺序和摘要一致。只读检查 HZL9 READY ZIP 的 104 个条目，其中 45 个路径包含 Syslog。HZL10 READY ZIP 669 个条目，没有路径名称包含 Syslog 或 Heartbeat。名称盘点仅覆盖归档目录，专用 Quick Ping 延续 Phase 5 的 `NOT AVAILABLE`。

现有入口提供归档摘要 JSON 与整包 ZIP。本轮原生另存与按范围提取各源原始记录未验收。[Phase 5 的 CSV 实测](UI_UX_PHASE5_REAL_DATA_ACCEPTANCE.md)
