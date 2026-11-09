# R2.3.1 位置更新延迟

延迟起点为 Syslog 解析出的设备 Event Time，终点为 Position Commit；Receiver 同时记录 Receive、Raw Persist、Parse Complete、Position Commit，API/UI 可用时间由现有 DTO/Renderer 字段承载。设备没有可信 Event Time 时沿用现有精度标记，不伪造事件时间。

## 正常本地模拟结果

负载：100 MR、402 条真实格式 loopback Syslog、每 MR A/B/重复 B/迟到 A，批量 Raw/Parser/Position。

| 指标 | 结果 |
|---|---:|
| Event→Position Commit P50 | 3153 ms |
| Event→Position Commit P95 | 4309 ms |
| Event→Position Commit P99 | 4562 ms |
| Receive→Raw Persist P95 | 164 ms |
| Raw Persist→Parse Complete P95 | 2311 ms |
| Parse Complete→Position Commit P95 | 305 ms |
| Raw Writer 队列完成值 | 0 |
| Parser 队列完成值 | 0 |
| 最老未处理日志完成值 | 0 s |
| >10 s / >30 s | 0 / 0 |

另两次同负载运行的 P95 为 4423 ms、6748 ms，均低于 10 秒；这是短时合成负载的观测范围，不是长期 SLA 证明。当前本地模拟满足 P95≤10 秒、P99≤30 秒。

## 时间精度与限制

时间字段由设备格式、Receive、Raw、Parse、Commit 分别保存。该模拟使用本机生成的合成 Event Time，不代表现场设备时钟质量；网络断开、UDP 丢包、设备停机、Backend 故障不纳入 30 秒正常负载指标。
