from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar

from netconsole.core.fit_ap_serial_identity import (
    fit_ap_serial_identity_key,
)
from netconsole.core.performance_profiling import ProfilingConnection


DEFAULT_SQLITE_TIMEOUT_SECONDS = 30.0
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 10_000

T = TypeVar("T")


def connect_sqlite(
    path: str | Path,
    *,
    timeout: float = DEFAULT_SQLITE_TIMEOUT_SECONDS,
    busy_timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    row_factory: bool = True,
    foreign_keys: bool = False,
    temp_store_memory: bool = False,
) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=timeout, factory=ProfilingConnection)
    if row_factory:
        conn.row_factory = sqlite3.Row
    configure_sqlite_connection(
        conn,
        busy_timeout_ms=busy_timeout_ms,
        foreign_keys=foreign_keys,
        temp_store_memory=temp_store_memory,
    )
    return conn


def configure_sqlite_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    foreign_keys: bool = False,
    temp_store_memory: bool = False,
) -> None:
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    if temp_store_memory:
        conn.execute("PRAGMA temp_store = MEMORY")
    conn.create_function(
        "netconsole_fit_ap_serial_identity",
        1,
        lambda value: fit_ap_serial_identity_key(value) or None,
        deterministic=True,
    )


def initialize_sqlite_wal(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass


def run_sqlite_with_retry(fn: Callable[[], T], *, attempts: int = 5, delay: float = 0.15) -> T:
    last_exc: sqlite3.OperationalError | None = None
    for index in range(max(1, attempts)):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(delay * (index + 1))
    if last_exc is not None:
        raise last_exc
    return fn()


def is_sqlite_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc).lower()
