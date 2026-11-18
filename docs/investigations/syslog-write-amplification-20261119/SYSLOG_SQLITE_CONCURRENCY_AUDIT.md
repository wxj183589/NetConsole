# SQLite Concurrency Audit

Connections are per operation and closed by context managers. Write paths enable WAL, `synchronous=NORMAL`, foreign keys, temp memory and a 10 second busy timeout. Projection, metadata and verified boot/identity paths can write concurrently to the same SQLite file.

One detailed 400 MR repeat recorded `connections=3,030`, `BEGIN=1,358`, `COMMIT=1,211`, and `ROLLBACK=146`. No final uncaught lock error was reported because projection failures are caught and retried by the runtime.

The captured failures were `ValueError: ground unattended raw file not found`, not an uncaught SQLite lock error. Multiple writers and retry-preserved batches still increase contention risk, but the primary reproduced cause is metadata ordering: deferred raw-file registration can lag the projection checkpoint update.

Status: `ISSUE_FOUND`; no production or real development database was opened.
