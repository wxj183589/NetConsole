# 主链路监控验收

## 指标

工作台实际加载并绘制以下 13 项指标：

RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise、TxDesFreeCnt、Tx/Rx、
Retry、Err、GARP、MulJoin。

最终 UI 状态为 13/13 图表完成；本端 / 对端系列均保留；右侧详情包含
RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise、TxDesFreeCnt、Tx、Rx、
Retry、Err、GARP、MulJoin。

## 数据边界

- 原始全范围 Radio 1：44470 行，raw_sample_complete=true。
- 业务派生使用相同 raw cache；原始记录没有被采样器删除。
- 视觉样本默认上限 4000 点，但保留端点、链路连续性边界和明确 gap。
- 右侧详情和选择定位继续使用完整 raw cache / complete index。
- Radio 2：真实查询返回 0 行并显示明确空数据语义，没有伪造 Radio 2 数据。

## 状态与生命周期

真实运行中观察到 PREPARING / QUERYING / PROCESSING / RENDERING /
COMPLETED；Radio 2 空数据完成后不停留在加载状态。单图状态独立，
其余图表继续完成。

## 证据

- 05：主链路监控上部。
- 06：下方图表、记录和历史区域。
- 11、12：计数器 tooltip 和固定选择。
- 13、14：Shift / Ctrl 时间交互。
- 16：右侧详情。
- 17：缺口绘制。
- 20：最终完整范围监控。

结论：主链路监控 PASS。
