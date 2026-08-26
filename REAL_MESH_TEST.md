# Real MESH Test

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
局点：宁波地铁6号线
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 数据与查询

- 数据库：`sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\列车24-MR-CT\mesh.sqlite`。
- 只读打开；真实 link total：87,402。
- `query_links(limit=1000)`：返回 1,000 行，2,757.6ms。
- active anchor `id=3` 的 `query_active_timeline`：37 行，776.4ms。
- 同一 anchor 的 peer chart 没有有效 segment，因此不伪造 chart 耗时或 heap 数据。

## 结果

- MESH service 1,000 行列表与时间轴查询可完成，未发现锁错误或数据破坏。
- 历史基线 MESH table 为 11.59s、heap 3.22GB；本轮服务端列表为 2.76s，但没有 GUI heap/long-task 证据，结论为 PARTIAL。
- GUI 滚动、首屏、图表、报告导出和 Task Center 恢复仍需单独验收。
