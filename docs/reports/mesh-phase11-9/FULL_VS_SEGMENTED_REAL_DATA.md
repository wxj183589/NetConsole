# 宁波地铁12号线真实 full-vs-segmented 派生对照

日期：2026-11-10
数据：只读 `D:\NetConsoleData-dev`，站点“宁波地铁12号线”，Session `7c7b6df2-e67b-452a-ab1a-91760014501f:1`，MR `列车03-MR-CW`，Radio 1，detail source 1。未访问 Production。

## 查询结果

窗口为 `2026-10-20 00:05:00.000–00:05:20.000`，分为两个不重叠的毫秒区间：

| 查询 | 可见 raw | items（含 context） | complete | SQL |
|---|---:|---:|---|---:|
| `00:05:00.000–00:05:10.000` | 31 | 34 | true | 3 |
| `00:05:10.001–00:05:20.000` | 30 | 33 | true | 3 |
| 一次性 20 秒 | 61 | 64 | true | 3 |

一次性可见 `record_id` 与两段可见 `record_id` 串联完全相同，重复 0、遗漏 0，实际可见序列为 `[806..866]`。第二段的 predecessor context 为 `834,835,836`，仅参与边界派生，不计入可见数量。

同一窗口使用 `include_zero=true` 复核：第一段 `total=32/items=35/zero=1`，第二段 `total=30/items=33/zero=0`，一次性 `total=62/items=65/zero=1`；可见 ID 串联仍无重复/遗漏。zero 样本为 `record_id=-1401`、时间 `00:05:06.412`、`link_count=0`、角色 `UNCONNECTED`。

## 真实派生字段对照

本轮从上述真实 Service raw 响应生成一个仅包含该窗口 raw 行的小型临时 JSON，调用实际 Renderer `deriveMeshRawSamples()` 和 `meshRawSampleKey()`，对一次性输入与两段按顺序写入 raw cache 后的派生结果逐条、逐字段比较。临时 JSON 已在比较完成后删除，没有复制 Site、数据库或完整数据根。

对照范围包括：

- `record_id`、时间、角色、链路身份及所有普通 DTO 字段；
- `counter_samples` 内每个累计计数的 `current`、`previous`、`delta`、间隔、每秒速率和状态；
- `monitor_gap_before`、`raw_sample_version`、`derived_metric_version` 及边界过滤结果。

结果：61 条可见行逐字段相等，context 不出现在派生结果中，结论为 `PASS`。

## 本轮修复的确定性问题

第一次用真实数据对照时发现 raw SQL 的 `DENSE_RANK() OVER (ORDER BY sample_time, id)-1` 是“查询子集相对序号”，因此同一记录在 full 与 segmented 查询中的 `sample_group_index` 不稳定。raw 路径现改为持久化稳定的 `s.id-1`；非 raw 旧查询保持原语义。修复后重新生成真实窗口 fixture，字段级对照通过。

这证明了真实 raw/TS 派生连续性，但不等同于真实 Electron 页面已完成全工作台交互、Heap 或长稳验收。
