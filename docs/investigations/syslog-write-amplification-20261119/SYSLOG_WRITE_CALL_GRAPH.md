# Syslog Write Call Graph

Audited `main` at `f6b1498c85cc7ed42cae74f690720a83a01d5d6f` (`v1.5.15`). No product code changed.

```text
SyslogUdpReceiver._recv_loop
  -> bounded UDP queue; overflow -> durable NDJSON spool
  -> _writer_loop -> RawStreamWriter.write (raw NDJSON)
  -> parser queue/spool -> _process_loop
  -> parser -> AP resolver -> PositionEngine
  -> _flush_events
     -> commit_wmesh_projection_batch
        -> WMESH events + timeline + position state + raw checkpoint
  -> verified event -> touch_boot_syslog -> boot/identity projections
```

Evidence: `src/netconsole/services/ground_unattended/syslog_runtime.py:1628`, `:1660`, `:1723`, `:1873`, `:2456`; repository transaction at `src/netconsole/repositories/ground_unattended_repository.py:4347`; boot projection at `:5572`.

Raw persistence precedes parsing. Structured projections are retryable and are not the raw evidence source. Application `dropped=0` does not prove kernel/network UDP delivery.
