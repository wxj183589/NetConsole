# R5.0.5.1 修复报告

## 修复内容

- 在 `mr_monitoring` 历史路径增加 Heartbeat source-run 解析：归档运行存在自己的 Ping raw 文件时仍使用归档；仅在没有该 MR 的归档 Heartbeat raw 文件时，按回放窗口读取 `heartbeat-resident`。
- API 诊断保留用户选择的归档 `requested_run_id`，新增 `source_run_id`、`source_reason`，避免把 resident 数据伪装成归档数据。
- Resident 回放强制 `active=false`，不会触发实时刷新语义；丢包区间也从同一 Heartbeat source stream 读取。
- Heartbeat 图表按主用/备用地址独立过滤，Tooltip 显示采样时间、管理地址、状态和 `Heartbeat` 来源。
- 无数据提示改为“当前时间范围没有 Heartbeat 采样数据”；Quick Ping 仍独立为空，不影响 Heartbeat。

## 未做的事情

- 未写入或修改真实 DEV 业务数据。
- 未从 Peer AP、Mesh、Syslog 或 Quick Ping 推导 Heartbeat。
- 未补造采样、未把缺失样本转换成“不通”。
- 未访问生产数据或真实设备。

