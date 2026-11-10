# R2.3.3 Syslog 队列边界与恢复

## 根因

`bounded-full` 出现在 Raw 已登记/关闭文件之后的压缩任务队列，不是 UDP Receiver、Raw Writer 或 Parser 的静默丢弃。压缩队列是有界内存队列；原始文件登记和内容写入先完成，压缩任务不能入队时只推迟压缩。

## 实现

- `RawCompressionWorker` 保持有界队列，不新增消息中间件，不把容量无限放大。
- 队列满时记录 `SYSLOG_COMPRESSION_QUEUE_FULL`，保留 Raw registry 作为 durable recovery index。
- 每 `0.25s` 进行一次有界 registry rediscovery，每轮最多 `128` 个待压缩文件。
- 通过 `list_pending_raw_compression()` / `count_pending_raw_compression()` 提供恢复和积压观测。
- 暂停/停止时再执行有界恢复轮次；关闭状态仍能证明已登记任务不会静默消失。
- Health 暴露 `compression_queue_full_count`、`compression_recovery_count`、`compression_pending_count`。

## 证据

测试：

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m pytest tests/test_udp_syslog_reliable_spool.py tests/test_ground_unattended_syslog_v2_stress.py tests/test_ac_mesh_link_resident_polling.py tests/test_ground_unattended_r2_3_3_burst.py tests/test_ground_unattended_api.py::test_runtime_train_list_and_detail_share_persisted_decision_contract -q
退出码：0
结果：43 passed
```

其中 `test_compression_queue_full_is_recovered_from_closed_raw_registry` 使用容量为 1 的压缩队列，验证 queue-full 计数、registry rediscovery 和恢复计数均发生；Raw 内容仍可读取。独立短突发也观察到停止时 `queue_empty=true`、`data_complete=true`、`dropped_count=0`。

结论：`QUEUE_SOURCE_IDENTIFIED=PASS`，`QUEUE_DATA_SAFETY=PASS`，`QUEUE_RECOVERY=PASS_WITH_EVIDENCE_CAVEATS`。恢复策略有界，但真实现场持续过载仍需以 health 队列和最老等待时间告警处置。
