# 性能、Heap 与缓存收敛

## 页面与查询

- MESH 详情页面真实状态：加载完成（2.5 s）。
- Radio 1 full raw query：44470 rows，SQL 3，HTTP duration 9198 ms。
- Radio 2 full raw query：0 rows，SQL 2，HTTP duration 616 ms。
- 主链路建链查询：8102 total，page 100。
- 链路明细初始查询：108700 total，page 100。
- 文本筛选 Z04-27：97 total，page 97。
- 导出提交：HTTP 202；后台 task 完成。
- 热范围复用：记录为 HTTP=0、SQL=0；已有 raw / derived cache 不重复拉取。

## 图表负载

全范围业务原始记录保持完整，传给 ECharts 的每个业务图表视觉样本上限
4000 点，并保留：

- 首尾端点；
- Peer / Radio / 角色 / 建链边界；
- monitor gap boundary；
- 完整 raw cache 与右侧详情索引。

这样没有把数据正确性依赖在视觉降采样上，也避免完整 44470 行同时复制到
13 个图表造成 Renderer 崩溃。

## Heap 与生命周期

受影响场景的实测采样：

- 全指标加载前 JS heap 约 790 MB；
- 全部指标完成后约 1.54 GB；
- 45 秒空闲后约 1.498 GB；
- 反复窗口、Radio、tooltip 和页面重入后一次快照：
  usedJSHeapSize 2,003,764,913 bytes；
  totalJSHeapSize 2,551,742,693 bytes；
  jsHeapSizeLimit 4,395,630,592 bytes。
- 同一快照 Renderer working set 约 2.86 GB；没有超过约 4.30 GB 的 JS heap limit，
  没有出现 crash。

ECharts / canvas 受影响场景最后快照：active ECharts 3、canvas 6、
init 33、dispose 30、mount 33、unmount 30、native listeners 15、
pending raw / metric / records / AP 均为 0。13 项图表均进入 COMPLETED。

## 限定

本轮没有把 45 秒空闲结果写成 30 分钟长稳；30 分钟长稳结论沿用 Phase 11.9，
本轮仅对受影响的图表、缓存、页面重入和快速切换做持续复测。
