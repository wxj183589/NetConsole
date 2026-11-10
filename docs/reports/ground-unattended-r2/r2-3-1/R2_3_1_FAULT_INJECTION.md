# R2.3.1 故障注入

## 已验证

- Parser/投影写入异常：Raw 保留，parse status 进入 recovery 状态。
- SQLite `database is locked`：Heartbeat/事件写入失败可观测，dirty 记录保留并可重试。
- AC 查询延迟：不阻塞 Fleet Heartbeat。
- fping stream end、runner exception：分片退避、健康告警和后续恢复。
- UDP、AC、Mesh、Replay 组件故障：resident Heartbeat 继续运行，故障被隔离。
- Backend restart：计数/位置/开放 Raw 段恢复测试通过。
- 发送突发：有限队列指标、pressure/drop 告警路径覆盖；本次正常 100 MR 模拟无丢弃。

## 未覆盖为 PASS 的场景

没有执行物理磁盘满、真实 SQLite 长时间持锁、真实 UDP 网络断链/丢包或真实 fping 进程 kill；这些需要受控运行环境，不能用本地 monkeypatch 伪装成现场结果。对应状态保留为 `PASS_WITH_EVIDENCE_CAVEATS` 或 `NOT_AVAILABLE`。
