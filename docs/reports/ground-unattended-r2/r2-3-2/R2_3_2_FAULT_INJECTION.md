# R2.3.2 故障注入

## 专项结果

| 组 | 结果 |
|---|---|
| Syslog/Raw/Position | 54 passed；20,000 ingress 在 Full Gate 并发期间一次超时，独立复跑 1 passed |
| AC/Heartbeat/recovery | 119 passed |
| API/Fleet/Foundation | 110 passed |
| Electron local integration | 60 秒 COMPLETED；GUI AP switch run 90 秒 COMPLETED |
| Long soak stop | 24,000.379 秒；正常 STOP；队列排空；SQLite integrity ok |

## 注入项

覆盖 UDP burst、Parser pause/exception、Raw slow/failure、SQLite lock、压缩异常保留原始文件、Heartbeat timeout/process exception/stream end、AC timeout/old/partial/continuous failure/recovery、Backend restart、数据库 recovery 和 Ground stop/Heartbeat resident。

## 结论

队列均有界，Raw 优先保留，失败不会无限重试或静默删除原始日志。长稳正常停止后 Receiver/Writer/Parser/UDP 释放，Heartbeat resident 证据保留。AC 旧快照不覆盖新 Syslog 位置，已由 AC reconciliation 专项覆盖。Full Gate 并发环境使严格 60 秒 burst 等待出现一次环境抖动，独立复跑通过。

未执行真实物理磁盘损坏、真实网络中断、现场设备进程 kill 或跨机故障，因此这些状态不宣称现场 PASS；`FIELD_ACCEPTANCE=NOT_AVAILABLE`。
