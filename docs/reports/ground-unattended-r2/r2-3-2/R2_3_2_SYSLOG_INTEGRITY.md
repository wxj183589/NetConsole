# R2.3.2 Syslog / Raw / Parser 完整性

## 实际本地链路

长稳 runner 使用 100 MR、loopback UDP sender、生产 `SyslogUdpReceiver`、RawStreamWriter、Parser 和 Position Engine。长稳实际结果为 `30,424 sent / 30,424 received / 30,424 raw / 30,424 parsed / 0 dropped`。停止时 `data_complete=true`、`queue_empty=true`、UDP 端口释放、projection/metadata/compression flush 完成，SQLite `integrity_check=ok`、`foreign_key_check=[]`。

Electron 集成使用 50 列车/100 MR、真实 Electron/Backend/Vite、200 个 Heartbeat targets 和 5,900 条 loopback UDP，最终 `5900 sent / 5900 received / 5900 raw / 5900 parsed / 0 dropped`；Raw、SQLite、gzip 完整性检查通过。证据根：`D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-electron-final-015-20261110`。

## Raw 独立审计

长稳 SQLite 中 syslog Raw 文件 800 行登记记录、`sum(record_count)=30,424`；文件系统中 plain `.ndjson` 行数为 30,424，736 个 gzip 文件均可读取。旧 `summary.json` 的 `raw_record_count=7,452` 是运行器调用分页 Raw 列表造成的统计字段缺陷，不是数据缺失；候选运行器已改为使用停止前 Receiver 的 authoritative `written` 计数。

## 覆盖与观察

- 正常持续上报、多 MR 并发、重复、乱序、未知 AP、坏格式、周期突发。
- Raw Writer 慢写/失败、压缩队列有界、SQLite lock/recovery、Parser 暂停/异常、Backend 重启恢复。
- 20,000 mock ingress 测试在 Full Gate 并发期间一次超时，独立复跑 `1 passed in 48.93s`；不归因于本轮 Raw 完整性。
- 长稳中压缩队列曾出现 bounded `compression queue is full`，对应原始 NDJSON 保留、压缩失败为 0；作为资源与压缩吞吐 caveat 记录。

`SYSLOG_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`。loopback 结果证明指定本机负载下的链路，不证明现场 UDP 网络不丢包。
