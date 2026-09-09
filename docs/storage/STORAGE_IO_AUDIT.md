# Storage I/O Audit

历史基线：`github/codex-B/fix/udp-syslog-reliable-spool` (`b1f42b71`)，2026-09-07 只读审计；本文件记录分支移植前的当时状态。

## 结论

- Raw Syslog 是每条消息一次 `write`，按 train/role/hour 路由到多个 NDJSON 文件；没有 per-message `fsync`，原实现按 100 条或 1 秒 `flush`。
- UDP overflow spool 是单个 run NDJSON append 文件，不是 1 message = 1 file；但每条 append 都 `flush`。
- Parser spool 是 Raw 已写入记录的 envelope+record 完整副本，属于可靠恢复副本而非独立 canonical authority，存在约 1 倍 payload 写放大。
- Ground SQLite 使用单连接上下文提交；Syslog 事件在 100 条或 1 秒批量提交，连接初始化为 WAL + `synchronous=NORMAL`，busy timeout 10 秒。WAL checkpoint 未设置独立策略，需后续专项治理。
- Raw active writer 数量等于并发 train/role/hour key 数，可能是几十个；当前实现未做统一 ingest segment。

## ACTIVE_WRITE_PATHS

`realtime/syslog/<train>/<role>/<date>/<hour>_<generation>.ndjson`、`realtime/syslog/_spool/<run>.ndjson`、`realtime/syslog/_spool/<run>.parser.ndjson`、Ground SQLite 与其 `-wal`/`-shm`。归档在活动目录之外，已有 spool isolation 会阻止 pending spool 被归档。

## 风险

主要 HDD write amplification 来自 Raw 小记录写、多个 active 文件、overflow/parser spool 重复写和 SQLite 高频小事务；本轮保留 Parser spool 以保证崩溃恢复，未删除或改变历史 reader。
