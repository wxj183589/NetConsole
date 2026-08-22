from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.storage.analyze_sqlite_size import analyze_sqlite_size


def test_sqlite_table_space_report_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE task_snapshots (task_id TEXT, result_json TEXT)")
        connection.executemany(
            "INSERT INTO task_snapshots VALUES (?, ?)",
            [("task-1", "x" * 100), ("task-2", "y" * 200)],
        )
        connection.commit()
    before = database.stat().st_mtime_ns

    report = analyze_sqlite_size(database)

    assert report["database_path"] == str(database.resolve())
    assert report["database_size_bytes"] == database.stat().st_size
    assert database.stat().st_mtime_ns == before
    if report["dbstat_supported"]:
        table = next(item for item in report["tables"] if item["table_name"] == "task_snapshots")
        assert table["page_count"] > 0
        assert table["size_bytes"] > 0
    else:
        assert report["dbstat_error"]
        assert report["errors"]
        table = next(item for item in report["tables"] if item["table_name"] == "task_snapshots")
        assert table["row_count"] == 2
        assert table["size_bytes"] > 0
        assert report["allocation_source"] == "raw_btree"
