# Duplicate UPDATE Audit

1. `PositionEngine` has bounded deduplication and ordering checks, but `_upsert_syslog_position_states` persists each flushed device state without an explicit field-aware no-op gate.
2. `touch_boot_syslog` opens a transaction for every verified parsed event and updates timestamps even after the boot state is already active.
3. Raw checkpoint updates repeat while a failed projection batch remains pending.
4. WMESH raw-line and dedup-key SELECT checks repeat on transaction retries.

Evidence: `src/netconsole/services/ground_unattended/position_engine.py`; repository methods at `src/netconsole/repositories/ground_unattended_repository.py:4403` and `:5572`; runtime retry at `src/netconsole/services/ground_unattended/syslog_runtime.py:2456`.

`NO_OP_UPDATE_FOUND=ISSUE_FOUND`. A future guard must preserve event time, receive time, freshness and counters; a blind old/new comparison is unsafe.
