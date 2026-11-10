# R2.3.1 本地三链路模拟

命令：

```powershell
\.venv\Scripts\python.exe -m scripts.dev.ground_unattended_r2_3_1_simulation
```

运行器使用真实 H3C WMESH 脱敏格式、loopback UDP、100 个合成 MR、200 个主备 Heartbeat 目标、隔离 SQLite 和模拟 AC 全快照。每次运行根目录位于 Workspace `test-data\NetConsole`，默认结束后删除；没有复制真实数据。

## 结果

| 项目 | 结果 |
|---|---:|
| Syslog UDP 原始消息 | 402/402 接收、写入、解析 |
| 去重后 WMESH 投影 | 302 条；重复原始行仍保留在 Raw/事件证据 |
| 有效位置历史事件 | 300 条 |
| Position 状态更新 | 200 次 |
| 最终 AP=B | 100/100 MR |
| Heartbeat 目标 | 200（100 primary + 100 backup） |
| Heartbeat 分片 | 17；停止后无存活 worker |
| AC delta 记录 | 301 条 |
| AC 延迟快照状态 | 100 条 `SYSLOG_NEWER` |
| 后续匹配 AC 状态 | 100 条 `CONSISTENT` |
| 丢弃 | 0 |
| Receiver 重启恢复 | 通过；MR-001 接受 AP-C |

模拟覆盖 A→B→重复 B→延迟 A、未知 AP、未知 MR、三次 AC 全快照，以及 Syslog、Heartbeat、AC 同时运行。它是本地证据，不是现场验收。
