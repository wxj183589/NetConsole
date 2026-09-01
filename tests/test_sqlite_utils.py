from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal


def _synchronous_value(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA synchronous").fetchone()[0])


def test_sqlite_synchronous_paths_are_observed_without_global_override(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synchronous-observation.db"

    with connect_sqlite(path) as connection:
        fresh_connection = _synchronous_value(connection)
        initialize_sqlite_wal(connection)
        wal_initialized_connection = _synchronous_value(connection)

    with connect_sqlite(path) as connection:
        reopened_connection = _synchronous_value(connection)

    # There is no repository-wide synchronous contract today.  Record the
    # current runtime contract instead of changing every connection to NORMAL:
    # a fresh/reopened connection is SQLite FULL (2), while the explicit WAL
    # initializer uses NORMAL (1).  A future reliability/performance decision
    # can change this diagnostic together with the contract it documents.
    observed = {
        "fresh_connection": fresh_connection,
        "wal_initialized_connection": wal_initialized_connection,
        "reopened_connection": reopened_connection,
    }
    assert observed == {
        "fresh_connection": 2,
        "wal_initialized_connection": 1,
        "reopened_connection": 2,
    }
