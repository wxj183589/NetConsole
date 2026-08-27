# MESH Renderer Phase2 报告

日期：2026-08-26

## 结论

MESH Renderer 当前实现已经采用局部性能边界：图表结果使用 `shallowRef`/`markRaw`，表格使用服务端分页，图表请求有上限、懒加载和取消控制。本轮没有全局改写 `NcDataTable`，也没有新增跨页面缓存。

## DEV 实测

使用宁波 12 号线 DEV MESH 数据，真实场景约 99,299 条链路、51,324 条 active frame：

| 场景 | 历史基线 | 当前只读实测 |
| --- | ---: | ---: |
| MESH table/大表 | 11.59s，heap 3.22GB | link table page 647ms，1,000 行分页返回 |
| active build order | 未单列历史基线 | 1,296ms，8,500 events |
| active path chart | 历史图表约 9.22s | 1,231ms，1,000 points |
| trackside chart | profiling 约 17.06s | 2,022ms，payload 2.22MB，返回 128 series/3,319 points |

当前数据均从 `D:\NetConsoleData-dev` 只读读取。当前未单独采集 GUI 滚动 FPS 和浏览器 long-task trace，因此 UI 端滚动验收仍标记为待补充。

## 风险边界

- 没有修改 MESH 原始日志解析、身份拓扑、任务恢复或报告字段。
- 没有引入新缓存，也没有改变历史数据。
- 1000 行表格的真实 GUI 滚动体验仍需人工桌面验收。
