# 一次性查询与分段查询对照

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
总体判断：raw 记录对照通过；全量真实 Renderer 派生字段对照尚未完成。

## 确定性 fixture 对照

前端测试构造同一条 lane 的 4 个累计计数采样。一次性输入为 `[0,1,2,3]` 秒；分段输入先放入 `[0,1]`，再放入 predecessor context `1` 秒和目标 `[2,3]`。两种输入经过 `deriveMeshRawSamples()` 后，以下 tuple 完全相同：

```text
[record_id, local_tx.previous, local_tx.delta, local_tx.per_second]
```

该 fixture 同时验证了 raw row 不变、context 不显示、前值跨段传递，以及按 lane 独立计算。另有 reset、role change、长间隔 fixture，确认异常时返回 null/状态而不是伪造当前累计值为增量。

## 宁波地铁12号线真实 raw 对照

数据：`D:\NetConsoleData-dev`，站点 `宁波地铁12号线`，会话 `7c7b6df2-e67b-452a-ab1a-91760014501f:1`，MR `列车03-MR-CW`，Radio 1。

| 对照项 | 第一段 | 第二段 | 一次性完整 | 结论 |
|---|---:|---:|---:|---|
| 时间范围 | 00:05:00.000–00:05:10.000 | 00:05:10.001–00:05:20.000 | 00:05:00.000–00:05:20.000 | 毫秒边界无重叠 |
| 可见 raw 记录 | 31 | 30 | 61 | 31+30=61 |
| 返回 items（含 context） | 34 | 33 | 64 | 各自 context=3 |
| 第一条可见 record id | 806 | 837 | 806 | 连续 |
| 最后一条可见 record id | 836 | 866 | 866 | 连续 |
| 角色 | 按 raw DTO 保留 | 按 raw DTO 保留 | ACTIVE 21 / STANDBY 40 | 未合并不同角色 |
| raw 完整性 | true | true | true | 可进入 raw cache |
| SQL 计数 | 3 | 3 | 3 | route 真实返回 |

完整窗口可见 record id 与两段可见 record id 的串联结果完全相等，序列为 `[806..866]`，重复记录 0、遗漏记录 0。两段第二段上下文 `[834,835,836]` 仅用于窗口边界派生，不计入可见数量。

真实窗口的角色统计为：可见 ACTIVE 21、STANDBY 40；context 为 ACTIVE 1、STANDBY 2；可见链路身份 4 个。这里的“角色”验证来自 raw DTO/真实 SQL 返回，不把 AP 名称单独当作链路身份。

## 尚未宣称的字段级结论

真实数据本轮已比较 raw 记录身份、时间、顺序、数量、边界 context 和角色分布；确定性 fixture 已比较前值、增量、每秒速率、reset/role/gap 状态。

尚未在真实 Renderer 中把同一真实窗口的一次性派生结果与两段/三段/逆序/重叠加载后的每一条 `counter_samples`、`monitor_gap_before`、ACTIVE/STANDBY 序列逐字段规范化比较，也未完成 100 次交互和 JS Heap 观测。因此“完整查询与分段查询业务字段完全一致”在真实端仍为 `PENDING`，本轮状态必须保持 `PHASE_11_9_FOURTH_ROUND=PARTIAL`。
