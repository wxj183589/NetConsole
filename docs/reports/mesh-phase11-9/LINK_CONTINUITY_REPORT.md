# 链路连续性报告

## 实现

`meshRawLaneKey()` 将 source、radio、peer MAC、establish time、peer radio MAC/label、peer AP MAC 组合为物理 lane。后端 `_raw_context_rows()` 在窗口起点前按 source/radio 批量扫描，针对目标 identity 选择最近 predecessor；它故意不应用可见的 AP/role filter。

因此：

- predecessor 只用于计算，不进入 `total`、分页或图表可见 rows。
- ACTIVE/STANDBY 历史状态按 raw `link_state` 保留。
- role、peer、establish time 变化不会被模糊匹配合并。
- context 数量和标记由 API 明确返回。

## 宁波真实窗口

会话：列车03-MR-CW，`7c7b6df2-e67b-452a-ab1a-91760014501f:1`，Radio 1，`00:05:00.000–00:05:20.000`。

- 可见 raw：61 条；ACTIVE 21，STANDBY 40。
- context：3 条，其中 ACTIVE 1、STANDBY 2。
- 可见物理 identity：4 个。
- 第二分段的 context record_id 为 `[834, 835, 836]`，未计入第二段 `total=30`。

这证明真实 SQL 层的前置采样和可见状态边界成立；完整 UI 图表渲染仍需后续真实 Electron acceptance。
