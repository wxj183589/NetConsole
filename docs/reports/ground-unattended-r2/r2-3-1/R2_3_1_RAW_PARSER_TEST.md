# R2.3.1 Raw Writer / Parser 测试

## 自动化证据

```text
pytest -q tests/test_ground_unattended_foundation.py tests/test_ground_unattended_syslog_position_latency.py tests/test_ground_unattended_syslog_v2_stress.py tests/test_ground_unattended_syslog_field_validation.py tests/test_ground_unattended_position_engine.py tests/test_ground_unattended_raw_lifecycle.py tests/test_ground_unattended_raw_v2_consumers.py
74 passed
```

AC/Heartbeat/故障隔离专项另外通过 142 项。

## 本地模拟证据

- 402 条 UDP 输入全部 Raw 持久化和 Parser 成功。
- 初始 Receiver 停止时关闭 101 个 Raw 文件，`data_complete=true`，没有丢弃。
- 同库重启后旧 Raw 文件被标记为 `RECOVERED`，新文件正常 `CLOSED`；Raw 记录总数在重启后为 403（初始 402 + 重启事件 1）。
- Parser 队列长度、Raw Writer 队列长度、最老未处理等待时间在完成时均为 0。
- SQLite/Raw 恢复路径保留原始日志，解析失败不会删除原始内容。

Raw 文件、SQLite 和运行日志没有写入报告目录；证据仅保留统计和测试命令。
