from __future__ import annotations

import json
from pathlib import Path

from scripts.storage.generate_storage_lifecycle_report import (
    generate_storage_lifecycle_report,
)


def _write_report(directory: Path, name: str, payload: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def _reports(directory: Path) -> None:
    _write_report(directory, "SITE_STORAGE_ANALYSIS.json", {"root_path": "D:/sites", "total_size_bytes": 1000})
    _write_report(
        directory,
        "RAIL_TRANSIT_ANALYSIS.json",
        {
            "root_path": "D:/sites",
            "total_size_bytes": 600,
            "total_files": 6,
            "extension_summary": [
                {"extension": ".sqlite", "size_bytes": 400, "file_count": 2},
                {"extension": ".log", "size_bytes": 100, "file_count": 2},
                {"extension": ".zip", "size_bytes": 100, "file_count": 2},
            ],
            "directories": [],
            "errors": [],
        },
    )
    _write_report(
        directory,
        "RAIL_TRANSIT_TIMELINE.json",
        {"timeline": [{"period": "last_30_days", "size_bytes": 500, "file_count": 5}], "errors": []},
    )
    _write_report(
        directory,
        "BACKUP_ANALYSIS.json",
        {
            "total_size_bytes": 300,
            "total_files": 3,
            "backups": [
                {"backup_type": "PRODUCTION_MAINTENANCE", "size_bytes": 200, "mtime": "2026-08-01"},
                {"backup_type": "DATABASE_MIGRATION", "size_bytes": 100, "mtime": "2026-07-01"},
            ],
            "errors": [],
        },
    )
    _write_report(directory, "BACKUP_DUPLICATE_ANALYSIS.json", {"duplicates": [], "errors": []})
    _write_report(
        directory,
        "HISTORY_DB_ANALYSIS.json",
        {
            "total_size_bytes": 100,
            "total_files": 1,
            "databases": [
                {
                    "path": "site/db/history/devices-2026.db",
                    "size_bytes": 100,
                    "tables": [{"table_name": "history_events_v2", "size_bytes": 80, "row_count": 10}],
                }
            ],
            "errors": [],
        },
    )
    _write_report(
        directory,
        "TOP_TABLE_USAGE.json",
        {
            "tables": [
                {"database": "site/db/tasks.db", "table_name": "task_results", "size_bytes": 70, "percentage": 70, "row_count": 4},
                {"database": "site/db/tasks.db", "table_name": "task_events", "size_bytes": 30, "percentage": 30, "row_count": 5},
            ],
            "errors": [],
        },
    )


def test_lifecycle_report_generates_markdown_and_matrix(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    output = tmp_path / "lifecycle"
    _reports(source)

    result = generate_storage_lifecycle_report(source, output)

    lifecycle = (output / "STORAGE_LIFECYCLE_REPORT.md").read_text(encoding="utf-8")
    matrix = (output / "STORAGE_GOVERNANCE_MATRIX.md").read_text(encoding="utf-8")
    assert result["missing_reports"] == []
    assert "## rail_transit Lifecycle" in lifecycle
    assert "## Backup Lifecycle" in lifecycle
    assert "## History Lifecycle" in lifecycle
    assert "## Task Storage Lifecycle" in lifecycle
    assert "建议评估" in lifecycle
    assert "| rail_transit sqlite |" in matrix
    assert "删除" not in lifecycle
    assert "删除" not in matrix


def test_empty_input_is_reported_without_failure(tmp_path: Path) -> None:
    output = tmp_path / "lifecycle"

    result = generate_storage_lifecycle_report(tmp_path / "empty", output) if (tmp_path / "empty").mkdir() is None else None

    assert result is not None
    assert len(result["missing_reports"]) == 7
    assert (output / "STORAGE_LIFECYCLE_REPORT.md").is_file()
    assert "Input Gaps" in (output / "STORAGE_LIFECYCLE_REPORT.md").read_text(encoding="utf-8")


def test_missing_fields_are_tolerated(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    source.mkdir()
    _write_report(source, "RAIL_TRANSIT_ANALYSIS.json", {})
    _write_report(source, "RAIL_TRANSIT_TIMELINE.json", {})
    output = tmp_path / "lifecycle"

    result = generate_storage_lifecycle_report(source, output)

    assert result["missing_reports"]
    text = (output / "STORAGE_LIFECYCLE_REPORT.md").read_text(encoding="utf-8")
    assert "unavailable" in text
    assert "STORAGE_GOVERNANCE_MATRIX" not in text
