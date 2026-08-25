from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.performance_profiling import (
    begin_request_profile,
    current_request_profile,
    end_request_profile,
    profile_repository,
)
from netconsole.core.sqlite_utils import connect_sqlite


def test_request_profile_collects_sql_and_repository_duration(tmp_path: Path) -> None:
    profile, token = begin_request_profile("request-1", "GET", "/api/example")
    try:
        with profile_repository("example.list"):
            with connect_sqlite(tmp_path / "profile.sqlite") as connection:
                connection.execute("CREATE TABLE values_table (value INTEGER)")
                connection.executemany(
                    "INSERT INTO values_table(value) VALUES (?)",
                    [(1,), (2,)],
                )
                cursor = connection.cursor()
                assert cursor.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 2
        assert current_request_profile() is profile
        # Connection PRAGMAs are intentionally included in request SQL cost.
        assert profile.sql_count >= 3
        assert profile.sql_ms >= 0
        assert profile.repository_ms >= 0
        assert "example.list" in profile.repository_calls
    finally:
        end_request_profile(token)
    assert current_request_profile() is None


def test_sql_errors_are_still_counted_and_propagated(tmp_path: Path) -> None:
    profile, token = begin_request_profile("request-2", "GET", "/api/example")
    try:
        with connect_sqlite(tmp_path / "profile.sqlite") as connection:
            try:
                connection.execute("SELECT * FROM missing_table")
            except sqlite3.OperationalError as exc:
                assert "missing_table" in str(exc)
            else:
                raise AssertionError("missing table query must fail")
        assert profile.sql_count >= 1
    finally:
        end_request_profile(token)
