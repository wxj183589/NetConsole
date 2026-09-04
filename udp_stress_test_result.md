# UDP Syslog Stress Test Result

测试使用本机 `127.0.0.1` UDP socket 和临时 Ground 数据根，未连接真实设备，也未访问生产数据目录。

| 场景 | 结果 |
| --- | --- |
| 1000 messages（约 1000 msg/s，memory capacity=100） | PASS，received=1000，written=1000，parsed=1000，dropped=0 |
| 5000 messages，parser projection barrier 阻塞，memory capacity=100 | PASS，received=5000，written=5000，parsed=5000，dropped=0；parser spool 被使用 |
| 停止 | PASS，UDP 端口释放，raw 文件关闭，队列清空 |

命令：

```text
python -m pytest tests/test_udp_syslog_reliable_spool.py -q
3 passed in 28.85s
```

补充定向回归：Ground foundation、radio correlation、syslog field validation 共 50 项中 49 项通过。剩余 1 项旧断言要求 raw NDJSON 在追加瞬间包含 AP Identity 派生字段；新架构明确 raw 先落盘、parser 异步派生，该断言需要按新文件契约调整，未将其伪装为通过。

数据库异常模拟使用可控 barrier：数据库投影暂停期间 raw writer 和 disk spool 继续增长，释放 barrier 后 parser 完成回放；应用层 dropped 保持 0。
