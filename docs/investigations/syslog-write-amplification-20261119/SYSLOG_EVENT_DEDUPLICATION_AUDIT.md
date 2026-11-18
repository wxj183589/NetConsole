# Syslog Event Deduplication Audit

Raw records remain append-only. Position deduplication uses bounded per-device history; repository idempotency checks raw file/line and `dedup_key`; IFNET/CFGMAN use a separate control-event key; receive/source sequences support ordering diagnostics.

The synthetic loopback sends an exact duplicate pair per MR. Application counters completed with no drops, but the 400 MR trace still contained repeated projection attempts and rollbacks. Raw duplicate evidence is intentionally retained and must not be removed as an optimization.

The current profile does not provide a stable exact-pair `duplicate_event_count` proof because public event listing is capped and projection retries inflate SQL before final inspection.

Status: `PARTIAL`; exactly-once processing is not claimed.
