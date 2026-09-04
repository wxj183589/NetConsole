# UDP Syslog 可靠接收整改报告

## 1. 问题根因

原接收线程把 UDP payload 放入有界 Queue；Queue 满时 `put_nowait` 直接丢弃。解析、AP 匹配、radio correlation、raw 写入和 SQLite 投影共享后续处理线程，数据库锁或慢事务会反向阻塞接收，造成现场高峰丢包。停止时也按固定顺序等待多个线程，backlog 大时可能超时并留下打开文件。

## 2. 修改前架构

```text
UDP -> recv thread -> bounded Queue -> parser/identity/DB -> Raw NDJSON
```

raw 写入晚于解析和数据库，Queue overflow 是原始数据丢失点。

## 3. 修改后架构

```text
UDP Receiver -> memory queue -> UDP disk spool (overflow)
             -> Raw writer -> append-only NDJSON
             -> parser queue -> parser disk spool (overflow)
             -> parser/AP Identity/radio correlation -> SQLite
```

Receiver 不等待数据库或复杂解析。disk spool 每条追加并 flush；启动时重计未消费记录，支持异常退出后的 bounded replay。Raw 路径保持既有 `realtime/syslog/<train>/<role>/<date>/...ndjson` 结构，不修改数据库 schema。

停止按 receiver、socket、writer flush/close、parser、projection flush 的依赖顺序执行，并使用统一 timeout deadline。运行状态增加线程存活、四阶段计数、memory/disk queue、raw 文件大小和最后写入时间。

## 4. 测试数据

- 1000 条高频 UDP：`received=1000`、`written=1000`、`parsed=1000`、`dropped=0`。
- 5000 条 UDP + 数据库投影 barrier：raw 持续写入，parser spool 使用，释放 barrier 后 `received/written/parsed=5000`、`dropped=0`。
- 停止验证：端口释放、队列清空、raw 文件关闭，返回成功。
- 代码质量：`py_compile`、Ruff、`git diff --check` 通过。

## 5. 风险说明

自动化测试只覆盖本机回环和临时数据根，不能替代 7 台 MR 长时间现场验证、真实设备 UDP 缓冲、低磁盘故障和主备 AC 切换。应用层 dropped=0 依赖 spool 文件可写；spool 写失败会进入 dropped/error 诊断，现场仍需监控磁盘容量和权限。旧测试中有一项要求 raw 追加时同步包含 AP Identity 派生字段；该要求与 raw-first append-only 文件契约冲突，应由消费者改为读取 parser/SQLite 派生结果，不能通过重写 raw 破坏事实源。
