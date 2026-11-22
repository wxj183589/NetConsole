# Session Recording

## 格式与位置

每个会话写入 runtime：

```text
terminal-recordings/<session-id>/metadata.json
terminal-recordings/<session-id>/events.jsonl
```

- metadata：设备 UUID/名称、Site、协议、状态、时间、断开原因、计数、完整性和 SHA-256；不含用户名、密码或私钥。
- events：STATE、INPUT、OUTPUT、RISK、RECORDING_END；每条含毫秒时间戳。

## 完整性策略

- 有界队列为 2048；实时连接线程不等待磁盘。
- 队列满时丢弃新录制事件并累计 `recording_dropped_events`，最终标记 `INCOMPLETE`，不伪报完整。
- 正常结束 flush + fsync，并计算 JSONL SHA-256，标记 `COMPLETE`。
- metadata 原子替换并有进程内写锁。
- TXT 导出流式读取完整 JSONL，不再截断在 2000 条；JSONL 导出保留原始事件。

## 状态

- 历史搜索、详情、分页事件、TXT/JSONL：IMPLEMENTED / TESTED。
- 输出回放：IMPLEMENTED（文本顺序查看），不是按时间节奏播放。
- HTML 导出、跨崩溃活动会话恢复：NOT_IMPLEMENTED。

## 双日志

- 自动操作日志在会话创建时启动，按会话保存 metadata/JSONL。
- 手动会话日志由用户单独启动、暂停、恢复和停止，可导出 TXT/JSONL，并记住最近保存目录。
- 两套 writer、状态和丢弃计数独立；SFTP 传输不阻塞终端日志线程。
