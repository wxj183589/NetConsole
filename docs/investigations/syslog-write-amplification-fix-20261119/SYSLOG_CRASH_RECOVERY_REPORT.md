# Failure and recovery boundaries

Isolated tests verify: registration delay does not enter projection SQL; registration failure retains the checkpoint; a later CLOSED registration can recover the file; a real missing file triggers one rollback and can retry after registration; checkpoint commit failure retains pending work; clean stop/restart does not replay consumed spool; Raw recovery clamps an interrupted streaming checkpoint; bounded replay is idempotent. A file-table lock now prevents checkpoint flush racing writer rotation or close.

Failed registration is kept as a metadata error. A stop that cannot flush metadata reports failure and retains the writer/compression owner for retry, as existing lifecycle tests assert. A process restart invokes existing `recover_raw_files` and pending replay. Checkpoint cannot advance beyond committed Raw metadata through the new live path.

If the bounded metadata error map overflows, the writer does not silently forget old failures. Once pending work and known failures clear, it verifies all files created by this writer generation against the Site/Run registry before lifting the overflow fence. A closed file still indexed as OPEN keeps the fence active until its CLOSED registration succeeds. Added tests cover both recovery and continued blocking while the index is incomplete.

No actual process kill, power-loss simulation, WAL corruption, external device or production database was used in this task. Those scenarios remain `NOT_VERIFIED`; local tests do not establish disaster recovery or field long-run behavior.
