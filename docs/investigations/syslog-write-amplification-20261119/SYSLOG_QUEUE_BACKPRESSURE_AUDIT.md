# Queue and Backpressure Audit

The UDP and parser queues are bounded. Overflow is written to durable NDJSON spool before the receiver returns to `recvfrom`. Raw persistence completes before parser enqueue. Parser spool preserves raw identity and replay cursor. Stop joins receiver, writer, compression, parser and flushes pending projections.

The 50/100/200/400 MR loopback runs completed with `received=written=parsed`, `dropped=0`, and successful stop. No spool remained after clean close in the captured runs.

This is application-level loopback evidence only. Kernel UDP loss, real-device bursts, switch buffering, crash recovery and long-run memory behavior are `NOT_VERIFIED`.

Status: `PARTIAL`.
