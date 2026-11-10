# 单链路与无可用备链区段

日期：2026-11-08
分支：`codex-A/mesh-analysis-performance-optimization`
对照基线：`37b0df95a3208d0d03380e76ccfe5419af1422f1`

每个 source/采样身份/Radio 直接复用 `build_sample_quality()`，要求唯一 ACTIVE（active_peer_count=1）且 available_backup_count=0。LinkCnt 不作为判定；存在可用备链的正常 LinkCnt=2 三角链路不进入风险。

风险分为 NO_STANDBY（无备链记录）、WEAK_STANDBY（有备链但低于有效备链阈值）、MISSING_STANDBY_RSSI（备链无可用 RSSI 证据）。沿用原 backup_available_threshold、best_backup_rssi 和 RSSI fallback；没有重新实现备链算法。

同来源同 Radio、同物理 AP/未识别 Peer、同风险类型且相邻采样 <=2秒合并；AP、风险类型、来源变化或>2秒断点拆分。不同 Radio 独立，来源结束结算。持续时间为末次采样减首次采样，单点为0，不外推采样周期。备链记录数为区段最大数量，最佳 RSSI 为区段最大值，可用备链恒为0。

保留所有连续区段（包括短区段）；`qualifies_no_backup_event` 用原 no_backup_min_seconds 标明是否达到已有 NO_BACKUP 事件门槛，旧事件生成与计数不变。新增单链路发生次数是连续风险区段数，不能与原事件数直接等同。多 Radio 累计时长相加，允许重叠，不等于整列车时钟去重时间。

摘要返回区段数、累计秒数、涉及物理 AP 数和 Radio。分页明细及 XLSX 保留开始/结束、来源 ID、源行号范围、ACTIVE Peer 证据与诊断，支持回溯原日志。没有改写原始日志和派生事实。
