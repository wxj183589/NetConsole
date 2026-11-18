# Idempotency and order validation

The per-file metadata queue still processes OPEN before CLOSED. Projection Checkpoint remains in the same SQLite transaction as parsed events, timeline rows and position state. A registration timeout returns without starting that transaction; a failed transaction retains its in-memory batch. Raw lines are never removed to reduce SQL count.

The existing Ground tests cover duplicate Syslog payloads, bounded crash replay, checkpoint failure/retry, Raw close and restart, position ordering and site-filtered Repository behavior. New tests cover delayed registration, failed registration followed by close/retry, repeat checkpoint no-op UPDATE, actual rollback accounting and concurrent file rotation. The final loopback workload sends one exact duplicate pair per MR; each synthetic UDP message remains represented by one Raw line and one event row.

This is application-level duplicate preservation and projection idempotency evidence. The test cannot prove absence of packet loss on a real network, nor behavior of an external sender that reorders or omits packets before local receipt.
