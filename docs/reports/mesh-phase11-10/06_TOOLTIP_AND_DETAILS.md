# Tooltip、Counter 与右侧详情

## 普通 tooltip

11 展示指标 tooltip 的时间、曲线侧、本端 / 对端值及计数器信息。

## 固定 tooltip

12 通过真实双击固定当前时间，鼠标移出后 tooltip 仍存在，并显示
“已固定 … · Esc 退出固定”。按 Esc 清除固定状态，右侧详情同步回收。

## Counter

Counter 字段采用 previous、delta、interval_seconds、per_second、status
的真实业务结构；tooltip 显示上次值、增量、间隔、速率和状态，而不是只显示
原始累计值。

## 右侧详情

16 证明选择样本后右侧详情使用实际数据填充：

- AP 名称与 AP MAC；
- 采样时间；
- 本端 / 对端 Radio；
- 历史角色和 LinkCnt；
- 建链时间、持续时长；
- RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise；
- TxDesFreeCnt、Tx、Rx、Retry、Err、GARP、MulJoin。

## 选择语义

- Shift 选择：更新 selected sample 和右侧详情。
- Ctrl 浏览：只浏览时间，不错误覆盖固定选择。
- 双击固定：同一事件不会被 ECharts 和 native fallback 重复处理。
- Esc：清除固定选择，监听器仍保持可释放。

结论：Tooltip、Counter Tooltip、双击固定、Esc、Shift、Ctrl、右侧详情
全部 PASS。
