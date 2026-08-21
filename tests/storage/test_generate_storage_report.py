from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.storage.generate_storage_report import (
    DIRECTORY_PATHS,
    generate_storage_report,
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_empty_site_generates_all_reports_and_zero_directory_entries(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    output = tmp_path / "storage-audit-report"

    generate_storage_report(site, output)

    inventory = _read_json(output / "SITE_STORAGE_INVENTORY.json")
    analysis = _read_json(output / "SITE_STORAGE_ANALYSIS.json")
    assert inventory["total_size_bytes"] == 0
    assert inventory["total_files"] == 0
    assert [item["path"] for item in analysis["top_directories"]] == sorted(DIRECTORY_PATHS)
    assert all(item["size_bytes"] == 0 for item in analysis["top_directories"])
    assert (output / "LARGE_FILES_REPORT.json").is_file()
    assert (output / "SQLITE_SPACE_REPORT.json").is_file()
    assert (output / "SUMMARY.md").is_file()


def test_multiple_directories_are_reported_with_explicit_paths(tmp_path: Path) -> None:
    site = tmp_path / "site"
    (site / "files" / "backups" / "production-maintenance").mkdir(parents=True)
    (site / "HistoryStore").mkdir()
    (site / "files" / "backups" / "production-maintenance" / "backup.zip").write_bytes(b"12345")
    (site / "HistoryStore" / "history.log").write_bytes(b"123")
    output = tmp_path / "report"

    generate_storage_report(site, output)

    analysis = _read_json(output / "SITE_STORAGE_ANALYSIS.json")
    by_path = {item["path"]: item for item in analysis["top_directories"]}
    assert by_path["files/backups/production-maintenance"]["size_bytes"] == 5
    assert by_path["HistoryStore"]["size_bytes"] == 3
    assert by_path["db"]["size_bytes"] == 0


def test_sqlite_files_are_analyzed_and_tables_are_flattened(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    database = site / "db" / "tasks.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE task_results (task_id TEXT, result_json TEXT)")
        connection.executemany(
            "INSERT INTO task_results VALUES (?, ?)",
            [("task-1", "x" * 50), ("task-2", "y" * 50)],
        )
        connection.commit()
    output = tmp_path / "report"

    generate_storage_report(site, output)

    report = _read_json(output / "SQLITE_SPACE_REPORT.json")
    assert report["database"]["count"] == 1
    table = next(item for item in report["database"]["tables"] if item["table_name"] == "task_results")
    assert table["row_count"] == 2
    if report["databases"][0]["dbstat_supported"]:
        assert table["size_bytes"] > 0
        assert table["percentage"] > 0
    else:
        assert report["databases"][0]["dbstat_error"]
    assert report["databases"][0]["database_path"] == str(database.resolve())


def test_summary_contains_factual_sections_and_top_files(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "large.log").write_bytes(b"x" * 32)
    output = tmp_path / "report"

    generate_storage_report(site, output)

    summary = (output / "SUMMARY.md").read_text(encoding="utf-8")
    assert "# NetConsole Site Storage Audit Report" in summary
    assert "## Largest files TOP20" in summary
    assert "`large.log`" in summary
    assert "## SQLite TOP10 tables" in summary
    assert "## Exceptions" in summary
    assert "## Conclusion" in summary


def test_invalid_sqlite_does_not_block_complete_report(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "broken.db").write_bytes(b"not a sqlite database")
    (site / "notes.txt").write_text("still scanned", encoding="utf-8")
    output = tmp_path / "report"

    generate_storage_report(site, output)

    report = _read_json(output / "SQLITE_SPACE_REPORT.json")
    assert report["databases"][0]["error"]
    assert report["errors"]
    assert (output / "SITE_STORAGE_INVENTORY.json").is_file()
    assert (output / "LARGE_FILES_REPORT.json").is_file()
    assert (output / "SUMMARY.md").is_file()


def test_repeated_generation_excludes_existing_report_directory(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "data.bin").write_bytes(b"payload")
    output = site / "storage-audit-report"

    generate_storage_report(site, output)
    first = _read_json(output / "SITE_STORAGE_INVENTORY.json")
    generate_storage_report(site, output)
    second = _read_json(output / "SITE_STORAGE_INVENTORY.json")

    for report in (first, second):
        report.pop("generated_at")
    assert first == second
    assert second["total_files"] == 1
