# Syslog Raw File / Checkpoint ordering fix

Baseline: `github/main=f6b1498c85cc7ed42cae74f690720a83a01d5d6f`. Historical audit: `3c7cdd6d121704580bda8a96637b34394ef358e3`.

`RawStreamWriter._open` submitted OPEN metadata to a single asynchronous worker. The parser could flush a checkpoint before that worker committed the row. `commit_wmesh_projection_batch` inserted projections, then looked up the file in the same transaction and raised `ValueError: ground unattended raw file not found`. Rollback retained the in-memory batch, so each retry repeated the projection SQL. The earlier isolated phase-separated 400 MR run observed 161 such errors and 161 rollbacks.

The writer now tracks pending metadata operations per file. A projection flush first makes its raw lines visible, waits for all OPEN/CLOSED metadata operations for its checkpoint files to finish, then enters the projection transaction. The metadata worker signals completion only after Repository commit. A bounded wait timeout or registration failure leaves the checkpoint and batch pending without starting the projection transaction. A genuinely unknown file still raises the existing missing-file error inside the Repository transaction; this is distinct from a pending registration. The single metadata worker retains OPEN/CLOSED order, and close/restart recovery remains in place.

`RawStreamWriter` now serializes writes, rotation, checkpoint flush and close under one reentrant lock. This also fixes a separately reproduced 400 MR `RuntimeError` when projection iteration overlapped writer changes to the open-file dictionary. Raw records and the compound projection identity are unchanged. A repeated checkpoint with identical `parse_status` skips its UPDATE using the row already selected for status computation.

The delayed-registration and failed-registration tests assert that no rollback occurs and the checkpoint remains pending. The forced missing-file test asserts one real rollback and successful retry after registration. The concurrent rotation test asserts that a checkpoint flush cannot race file-table mutation. Full isolated load results are in `SYSLOG_BENCHMARK_COMPARISON.md`.

Review follow-up: after more than 256 distinct registration failures, the bounded error map can evict old entries. The overflow fence now lifts only after the queue and known errors clear and an exceptional read-only scan confirms every file from this writer generation is indexed to the same Site/Run/path; a physically closed file must no longer be marked OPEN. This avoids both repeated missing-file rollbacks and permanent blockage after all registrations recover. The normal per-batch path does not add one query per raw record.

No schema, index, API, raw format or site-binding change was made.
