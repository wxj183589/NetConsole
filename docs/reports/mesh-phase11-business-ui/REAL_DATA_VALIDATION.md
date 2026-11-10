# 真实数据验证

验证数据：`D:\NetConsoleData-dev\sites\宁波地铁12号线\files\rail_transit\mr_raw_mesh`。

验证方式：只读读取既有 MESH 会话，通过实际 Electron 页面打开 `列车03-MR-CW`，未复制、迁移或写入真实数据目录。

## 结果

- 分析会话列表返回 7 个来源，页面可打开真实会话。
- 分析概览显示物理 AP、信号分级、有效记录、ACTIVE/STANDBY 和单链路风险。
- 日志解析显示真实异常类型与数量，未显示来源文件、行号或解析规则。
- AP 情况显示 601 个 AP 的真实统计，业务列可读。
- 主链路监控加载真实 RSSI、CPU、Memory、Tx/Rx Busy、Rate、Noise、Counter 趋势；无数据指标显示空态，不伪造零值。

## 边界

本验证不代表现场设备、生产数据写入、Excel/WPS GUI 或 Windows 原生 DPI 验收。
