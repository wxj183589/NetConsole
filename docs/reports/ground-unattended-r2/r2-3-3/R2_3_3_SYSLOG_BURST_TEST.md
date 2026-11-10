# R2.3.3 Syslog 短时突发测试

## 命令

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_r2_3_3_burst.py -q -s
退出码：0
结果：1 passed in 2.74s
```

场景使用 50 列车、100 台 MR、10 个并发发送线程，loopback UDP，真实 Receiver/Raw Writer/Parser/Position 投影链路；每台 MR 产生 AP-A、AP-B，另含 1 条延迟到达事件和 1 条重复事件。

## 原始指标

| 指标 | 结果 |
|---|---:|
| events sent / received / written / parsed | 202 / 202 / 202 / 202 |
| dropped | 0 |
| 突发发送耗时 | 0.873 s |
| 接收 EPS | 231.501 |
| Raw 文件 / Raw 记录 | 100 / 202 |
| gzip 可读 | 是 |
| Position update count | 200 |
| duplicate / out-of-order | 1 / 1 |
| 位置延迟 P50 / P95 / P99 | 197 / 399 / 399 ms |
| 阶段 P95：Receive→Raw | 183 ms |
| 阶段 P95：Raw→Parse | 544 ms |
| 阶段 P95：Parse→Position | 617 ms |
| Parser queue / Raw Writer queue | 0 / 0 |
| 最老未处理等待 | 0.0 s |
| stop data_complete / queue_empty | true / true |

50 辆列车的 100 台 MR 最终均为 AP-B，Previous 均保留 AP-A；延迟事件没有把 Current 回退，重复日志没有产生重复位置切换。该结果满足本地合成正常负载的 P95≤10 秒、P99≤30 秒，但不替代真实现场网络验收。

结论：`SYSLOG_BURST=PASS`，`POSITION_P95=PASS`，`POSITION_P99=PASS`。
