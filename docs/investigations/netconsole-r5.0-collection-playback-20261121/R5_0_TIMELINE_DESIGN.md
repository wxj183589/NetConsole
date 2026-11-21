# 全局时间轴设计

父级保存唯一状态：

- `fullStart/fullEnd`：本次查询范围；
- `visibleStart/visibleEnd`：当前可见窗口；
- `cursorTime`：所有轨道共享定位线；
- `generation` 与 AbortController：阻止旧响应覆盖新状态。

主地址、可折叠备用地址、Peer AP 区间和底部 Navigator 使用真实时间戳。三条业务图仅保留 inside zoom，不显示独立 slider；底部 Navigator 是唯一 slider。任一图的缩放更新父级状态，其他图由 props 重绘；程序性 `setOption` 不反向 emit，避免同步循环。

可见窗口变化先本地同步，250 ms 防抖后取消旧事件请求，并按新窗口重新查询 MESH/丢包列表。事件点击设置 `cursorTime`，所有轨道显示同一定位线。Ping 缺样以 `null` 断线，`connectNulls=false`，不把空白补成 0。

60 分钟 Ping 统计可以读取查询起点之前的样本，但 `queried_start/queried_end`、MESH、Peer 区间和事件严格保持用户选择的窗口。
