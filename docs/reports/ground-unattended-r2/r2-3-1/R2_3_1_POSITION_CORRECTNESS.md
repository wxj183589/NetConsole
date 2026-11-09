# R2.3.1 位置正确性

## 覆盖场景

- A→B 连续切换，最终位置为 B。
- 重复 B 不重复产生位置切换；100 个 MR 的 duplicate count 为 100。
- B 之后迟到的旧 A 被计为乱序，不覆盖更新的 B；100 个 MR 最终仍为 B。
- AP-C/未知 AP 不被随意绑定；未知 MR 只留原始/解析证据。
- 中间 A、B 和迟到事件保留在历史投影中；去重只合并重复中间状态，不删除 Raw。
- 后端同库重启恢复位置状态，随后 AP-C 事件可继续提交。

## 结果

本地模拟中 100/100 MR 最终 `current_ap=B`，PositionEngine 更新 200 次，保留 300 条有效位置历史事件，重复 100 次，乱序 101 次（含未知/迟到边界事件）。`position_quality` 仅对精确 AP 身份进入位置投影；不完整或未识别事件不会清空旧位置。

位置状态由 `PositionEngine` 和 Ground Repository 维护，未重新引入退役 Legacy HistoryStore。
