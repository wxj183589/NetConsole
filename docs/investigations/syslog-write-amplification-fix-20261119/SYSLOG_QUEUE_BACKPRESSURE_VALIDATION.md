# Queue and backpressure validation

The UDP receiver, Raw writer and parser retain their bounded queues and disk overflow spool. The metadata worker retains a 256-item bounded queue. The new file-scoped barrier waits only in the projection worker, leaving the UDP receive thread independent of SQLite registration. A timeout blocks checkpoint advancement and leaves work pending; it does not acknowledge a failed projection.

The 5,000-message existing spool test and 1,000-message UDP stress test passed. The five-repeat 50/100/200/400 MR loopback workload recorded zero application drops and completed all stops. Queue wait and maximum depth are now visible in the receiver health snapshot; final measured P95 values are in `SYSLOG_BENCHMARK_COMPARISON.md`.

This validates bounded local queues and local UDP loopback only. Sustained external traffic, kernel UDP drop counters, true network loss and long-duration backlog recovery remain unverified.
