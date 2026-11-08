# R3 进程边界设计

| 边界 | 当前职责 | 决策 |
|---|---|---|
| Electron Renderer | 展示、用户操作、断线重连 | 不承载采集任务 |
| Python Core | Supervisor、Repository、Heartbeat、AC、Syslog 接收 | 保持单进程，局部失败隔离 |
| Fleet Ping | 心跳分片线程和状态回调 | 与 Quick Ping 队列隔离 |
| Quick Ping | 独立运行/停止/限并发/Raw 分片 | 不抢占心跳资源 |
| Syslog Parser | Raw 落盘后异步解析 | 解析失败保留 Raw |
| 按需 Worker | 压缩、报表、深度分析 | 任务完成后退出或回收 |

本轮不拆 Heartbeat 或 Quick Ping 操作系统进程。压力证据不足以证明拆进程收益，后续以资源和恢复指标触发重新评估。
