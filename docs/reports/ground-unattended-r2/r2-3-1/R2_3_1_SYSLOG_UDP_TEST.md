# R2.3.1 Syslog UDP 测试

## 测试方法

`SyslogUdpReceiver` 绑定 loopback 随机端口；发送方按 100 个合成 MR 的 primary loopback 地址绑定，发送 H3C `%%10WMESH/5/MESH_LINKUP` 真实格式。接收、Raw Writer、Parser、Position 投影运行在独立线程，批次参数为有限队列、Raw 32 条/0.05 秒、位置事件批量 64 条/0.05 秒。

## 结果

- 接收 402 条，Raw Writer 402 条，Parser 成功 402 条，Raw 写失败 0，UDP 丢弃 0。
- 未知 AP 和未知 MR 均保留原始日志；未识别证据没有被强行关联到车辆位置。
- `receiver.stop()` 返回成功，队列为空，UDP 端口释放，Raw metadata/projection flush 成功。
- 重启 Receiver 使用同一隔离库恢复已有位置状态，再接收 AP-C 事件成功。

原始消息与解析投影的数量不同是预期行为：重复 B 的业务投影按 dedup key 合并，但原始 Raw 记录不删除、不覆盖。详见 [Raw/Parser](R2_3_1_RAW_PARSER_TEST.md) 和 [位置正确性](R2_3_1_POSITION_CORRECTNESS.md)。
