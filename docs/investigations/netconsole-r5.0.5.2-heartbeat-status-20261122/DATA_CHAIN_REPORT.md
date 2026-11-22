# R5.0.5.2 Heartbeat 通断数据链调查

## 真实数据证据

- Site：`hzdt-09`；数据库：`D:\NetConsoleData-dev\sites\hzdt-09\files\rail_transit\ground_unattended\index.sqlite`。
- 归档运行：`ground_20261120_c8f2edb88f15`；MR UUID：`09bb8f5e-0749-443f-859a-15947d308854`；列车 35 / CT。
- 回放窗口：`2026-11-20 15:11:00+08:00` 至 `16:08:24.710+08:00`。
- Heartbeat 原始文件属于 `heartbeat-resident`，共 4 个 NDJSON 文件；归档 run 本身没有逐条 Heartbeat 文件。

| 地址 | 原始采样 | `ok=true` | `ok=false` | 无法识别 |
| --- | ---: | ---: | ---: | ---: |
| 10.82.24.235 | 3,144 | 2,289 | 855 | 0 |
| 192.168.35.249 | 3,404 | 2,342 | 1,062 | 0 |

原始字段为 `ok: true/false`，成功样本包含 `rtt_ms`，失败样本 `rtt_ms: null`。原始记录没有可独立区分“失败”和“超时”的枚举，因此前端只能将 `ok=false` 统一显示为“不通/超时”，不会虚构更细状态；本轮未修改数据库、Raw 日志或历史记录。

## 根因

R5.0.5.1 已正确回退到 resident stream，但 `mr_monitoring()` 仍以通用 Ping 查询的 `max_points=2400` 读取 Heartbeat。通用查询为保证丢包事件完整，先保留失败点，再从剩余预算抽样成功点。窗口共有 6,548 条样本，导致成功记录大量被抽掉，图表视觉上几乎全红；原始数据并非全部失败。

同时，Renderer 原先复用 Quick Ping 的状态分类：`ok=true` 但 RTT 缺失会被判为 UNKNOWN。Heartbeat 的通断契约应以持久化 `ok` 结果为准，不能从 RTT 推断。

## 链路数量核对

- Backend `mr_monitoring`：1 次 Heartbeat resident `ping_series` 查询，输入窗口内 6,548 条原始样本，返回 6,548 个点（主地址 3,144、备用地址 3,404）；查询预算为 10,000，未触发下采样。
- API：1 个 `GroundMrMonitoring` 响应，`series.points` 为 6,548 条；响应诊断保留归档 `run_id` 与 resident `source_run_id`。
- Renderer：1 次响应适配，按管理地址拆分为主地址 3,144 条、备用地址 3,404 条；每个 Heartbeat 图表生成正常、失败、未知 3 条独立状态序列。
- Quick Ping：本归档无记录时仍显示无数据，不参与 Heartbeat 查询或状态统计。

## 修复

- 历史 Heartbeat 查询预算提升到 10,000，当前 24 小时上限足以保留真实窗口全部样本，不改变原始记录。
- 新增 `heartbeatPointValues()`：`ok=true` 为正常连通，`ok=false` 按明确超时/失败显示红色，状态缺失才为 UNKNOWN。
- 主备图表 Tooltip 增加原始采集结果；主备统计独立显示成功、失败、未知和连通率，统计随全局可视窗口更新。
