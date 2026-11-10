# 位置 Current/Previous 对照

## Syslog 与 scheduler 投影

- scheduler 可比较 MR：26。
- 当前扩展身份、有效事件时间序回放状态：35 个 MR。
- Current AP：26/26 与旧 scheduler 最终状态一致，匹配率 100%。
- Previous AP：22/22 与旧 scheduler 最终状态一致。
- Current AP 差异：0；无法解析而导致的可比较状态缺失：0。
- WMESH 历史：39,827 条原始业务事件均参与 PositionEngine 内存回放；严格 Repository 投影按语义去重保留 39,778 个唯一 WMESH 行。

旧 scheduler 不是绝对 ground truth，因此 100% 只能表述为“与旧投影一致”，不能替代现场定位验收。

## Syslog 与 AC

26 个可比较 MR 的 AC 最新精确观察均被判定为 `AC_NEWER`（以较宽时间窗口观察顺序），而不是当前 Syslog 覆盖 AC。使用 120 秒新鲜度阈值时，35 个 Syslog MR 中 29 个为 `AC_NEWER`、6 个为 `STALE`。

这说明该归档的 AC 观察时间晚于 Syslog 事件投影或部分证据已过新鲜度窗口；回放没有把 AC 快照无条件写回 Syslog Current。该结果不能直接解释为 AP 错位，需结合实时采集时间和局点现场窗口确认。

