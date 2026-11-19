# Batch write optimization decision

The existing projection API already batches parsed events, timeline rows and position states in one transaction and uses `executemany` for compatible rows. The Raw writer remains append-only; the receiver uses bounded queues and a durable overflow spool. This task does not change batch size, worker count or acknowledgement order.

The dominant measured amplification was retrying the entire projection transaction while asynchronous Raw File registration was incomplete. The completion barrier removes those doomed transactions. The raw-file checkpoint now skips an UPDATE only when its selected `parse_status` is already the exact target value; it does not skip freshness, event-time or position-state updates. No extra SELECT is added for this guard.

The 400 MR five-repeat comparison shows complete-trace SQL falling from the historical 536,364 average to the current result recorded in `SYSLOG_BENCHMARK_COMPARISON.md`. COMMIT count does not materially fall because one-time Raw File OPEN/CLOSED registration and required boot/identity work remain. Consolidating boot transactions or further position writes would change their immediate visibility/freshness contract, so this task does not infer that they are safe to remove from SQL count alone.

Raw event count, order, source isolation and existing projection batching stay unchanged. No speculative SQL or state coalescing was added.
