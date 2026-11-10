# R2.3.2 Heartbeat resident

## 结果

- Electron 集成：50 trains、100 MR、100 primary + 100 backup，200 targets，17 workers/processes；5,900 Syslog loopback 消息与 Heartbeat 同 Backend 运行。
- Ground stop 后：Syslog UDP/Receiver/Raw Writer/Parser 均停止，Heartbeat 保留 200 targets/17 processes，Renderer reload 并继续读取 Heartbeat 页面。
- 长稳 runner：100 primary targets，默认 5,000 ms 周期，478,184 samples；9/9 worker 停止、无存活 worker、元数据持久化成功；使用受控 in-process synthetic runner，无真实 fping child。
- 长稳 ping 汇总：2,390,920 sent、2,390,920 success、0 loss；RTT min/avg/max 为 1.0/1.1999/1.4 ms，最大 loss rate 0%。
- 长稳资源：RSS 69,160,960→108,236,800 bytes，峰值 126,242,816；线程范围 16–17；CPU process time 3,115.609 s。
- AC/Heartbeat/recovery 专项 `119 passed`；API/Fleet 基础专项 `110 passed`。

## 判定

`HEARTBEAT_100_IP=PASS`；`HEARTBEAT_200_IP=PASS`；`HEARTBEAT_RESIDENT_AFTER_GROUND_STOP=PASS_WITH_EVIDENCE_CAVEATS`；`HEARTBEAT_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`。真实 fping.exe、现场网络和 ICMP 行为未验收。
