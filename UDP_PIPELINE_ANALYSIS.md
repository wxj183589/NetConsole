# UDP Syslog Pipeline Analysis

## Baseline

基线 commit 为 `1463647471d6d5836a6c0fc692062d35290aa0fd`。当前 Ground Syslog 监听由 `SyslogUdpReceiver` 管理，原有实现把接收、解析、AP Identity、数据库投影和 raw 写入放在同一处理线程的有界内存队列之后。

## 修改前真实流程

```text
UDP socket (recvfrom)
  -> 接收线程
  -> Queue(maxsize=20000, put_nowait)
  -> process thread
  -> source/hostname identity + WMESH/IFNET/CFGMAN parser
  -> AP Identity / radio correlation
  -> RawStreamWriter NDJSON
  -> SQLite projection batch / timeline
```

当 Queue 满时，接收线程直接增加 `dropped_count`，原始 payload 没有第二份持久化副本。

## 问题回答

1. UDP 收到后，修改前要等 process thread 完成身份和解析后才写 raw；正常情况下是毫秒级，数据库或解析阻塞时会无限延后。
2. 不能。数据库阻塞会卡住 process thread，随后 Queue 填满；Queue 满后 UDP 报文直接丢失。
3. Queue 保存 `UdpEnvelope`，包含 source IP/port、接收时间、全局和来源序号、原始 bytes。
4. Queue 满时使用 `put_nowait`，不等待、不回压，直接计数并丢弃。
5. 丢弃发生在接收线程处理 `queue.Full` 的分支，发生在 raw 文件之前。

## 修改后流程

```text
UDP recvfrom
  -> Receiver memory queue
  -> overflow append-only disk spool
  -> Raw writer thread -> realtime/syslog/<train>/<role>/<date>/<hour>_<generation>.ndjson
  -> Parser memory queue
  -> parser overflow disk spool
  -> Parser/AP Identity/radio correlation
  -> SQLite projection batch
```

Receiver 只建立 envelope、读取已加载的内存 inventory 进行路由并追加 overflow spool；复杂 parser、AP 查询和数据库调用均在 parser worker。memory queue 是短缓存，disk spool 是恢复和高峰缓冲；写 spool 失败才计入 dropped，并保留错误状态。正常停止且 backlog 已清空时会截断 spool，避免同一 run 重启重复回放；异常退出则保留 spool 内容供下一次启动重放。

## 停止顺序

停止设置事件并关闭 UDP socket，等待 receiver，再等待 writer drain。只有 writer 已退出后才 flush/close raw 文件，随后等待 parser、flush SQLite projection、关闭 spool handles 并保存最终状态。每个 join 使用统一 deadline，不调用无限 `queue.join()`。

## 运行诊断

`health_snapshot()` 增加 receiver/writer/parser alive、received/written/parsed/db_saved/dropped、memory/disk/parser queue、raw file、size 和 last write time，同时保留旧 UDP 健康字段。
