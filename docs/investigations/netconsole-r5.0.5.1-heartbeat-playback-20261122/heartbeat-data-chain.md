# R5.0.5.1 Heartbeat 回放数据链调查

## 范围

- Site：`hzdt-09`
- DataRoot：`D:\NetConsoleData-dev`
- SQLite：`sites/hzdt-09/files/rail_transit/ground_unattended/index.sqlite`
- 归档运行：`ground_20261120_c8f2edb88f15`
- 目标：35 车 CT，MR UUID `09bb8f5e-0749-443f-859a-15947d308854`
- 回放窗口：`2026-11-20 15:11:00+08:00` 至 `16:08:24.710+08:00`

## 证据链

1. `ground_unattended_runs` 只有一个已完成归档运行，归档运行的 `run_id` 是 `ground_20261120_c8f2edb88f15`。
2. `ground_unattended_heartbeat_states` 的 30 条状态均属于 `heartbeat-resident`，归档运行没有 Heartbeat 状态快照。
3. `ground_unattended_raw_files` 的 Heartbeat Ping 文件属于 `heartbeat-resident`，35/CT 有 4 个逐条 NDJSON 文件登记；归档运行的 raw 文件是 Syslog，不含 Heartbeat Ping。
4. 逐条 NDJSON 中同时存在 `10.82.24.235` 和 `192.168.35.249`，并保存相同 MR UUID、列车 `train:35`、端位 `CT`。
5. 历史 API 查询原先把归档 `run_id` 直接传入 Ping 查询，因而只查归档 Ping 文件并返回空数组。
6. 修复后，历史回放保留归档运行作为上下文；当该运行没有该 MR 的 Ping raw 文件时，在精确时间窗口内读取 `heartbeat-resident`，并在诊断中返回 `source_run_id` 与 `source_reason`。

## 各层数量

| 层 | 数量 | 说明 |
| --- | ---: | --- |
| SQLite raw Heartbeat（精确窗口） | 6,548 | 主 3,144；备 3,404 |
| Raw Query 输入/匹配 | 6,548 | 精确窗口；服务为统计保留前置 1 小时时返回 6,868 |
| API `series` | 6,868 | 诊断 `source_run_id=heartbeat-resident` |
| Renderer 输入 | 6,868 | 按主/备地址独立过滤 |
| 图表轨道 | 2 | 主用与备用分别渲染；每轨在线/失败/未知三类序列 |

Quick Ping 表及运行记录均为空，未被用来替代 Heartbeat。

