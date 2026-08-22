from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.storage.analyze_sites_root import (
    analyze_sites_root,
    directory_contribution,
    main,
)
from scripts.storage.generate_storage_report import generate_storage_report


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sites_summary_sorts_chinese_sites_and_keeps_empty_site(tmp_path: Path) -> None:
    inventory = {
        "root_path": str(tmp_path / "sites"),
        "total_size_bytes": 300,
        "total_files": 3,
        "directories": [
            {"path": "空 Site", "size_bytes": 0, "file_count": 0},
            {"path": "宁波地铁12号线", "size_bytes": 200, "file_count": 2},
            {"path": "杭州", "size_bytes": 100, "file_count": 1},
            {"path": "宁波地铁12号线/files", "size_bytes": 200, "file_count": 2},
        ],
        "errors": [],
    }

    report = analyze_sites_root(inventory)

    assert [item["site_name"] for item in report["sites"]] == [
        "宁波地铁12号线",
        "杭州",
        "空 Site",
    ]
    assert report["sites"][0]["percentage"] == 66.67


def test_directory_contribution_aggregates_each_site_and_zero_fills(tmp_path: Path) -> None:
    inventory = {
        "root_path": str(tmp_path / "sites"),
        "total_size_bytes": 300,
        "directories": [
            {"path": "A/files/backups", "size_bytes": 150, "file_count": 1},
            {"path": "B/files/backups", "size_bytes": 50, "file_count": 1},
            {"path": "A/db", "size_bytes": 100, "file_count": 1},
        ],
        "errors": [],
    }

    report = directory_contribution(inventory, paths=("files/backups", "HistoryStore", "db"))
    by_path = {item["path"]: item for item in report["top_directories"]}

    assert by_path["files/backups"]["size_bytes"] == 200
    assert by_path["db"]["size_bytes"] == 100
    assert by_path["HistoryStore"]["size_bytes"] == 0


def test_sites_root_generator_writes_global_reports_and_findings(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    site_a = sites / "宁波地铁12号线"
    site_b = sites / "空 Site"
    (site_a / "files" / "backups" / "production-maintenance").mkdir(parents=True)
    (site_a / "db").mkdir()
    site_b.mkdir(parents=True)
    (site_a / "files" / "backups" / "production-maintenance" / "snapshot.bak").write_bytes(
        b"backup" * 10
    )
    (site_a / "files" / "backups" / "production-maintenance" / "migration.rollback").write_bytes(
        b"rollback"
    )
    tasks = site_a / "db" / "tasks.db"
    with sqlite3.connect(tasks) as connection:
        connection.execute("CREATE TABLE task_results (value TEXT)")
        connection.executemany("INSERT INTO task_results VALUES (?)", [("x" * 100,), ("y" * 100,)])
        connection.commit()
    (site_a / "db" / "devices.db").write_bytes(b"invalid sqlite")
    output = tmp_path / "storage-audit-report" / "all-sites"

    generate_storage_report(sites, output)

    expected = {
        "SITE_STORAGE_INVENTORY.json",
        "SITE_STORAGE_ANALYSIS.json",
        "LARGE_FILES_REPORT.json",
        "SQLITE_SPACE_REPORT.json",
        "SUMMARY.md",
        "SITES_SUMMARY.json",
        "BACKUP_INVENTORY.json",
        "ALL_SQLITE_DATABASES.json",
        "TOP_TABLE_USAGE.json",
        "ROOT_STORAGE_FINDINGS.md",
        "RAIL_TRANSIT_ANALYSIS.json",
        "RAIL_TRANSIT_TIMELINE.json",
        "BACKUP_ANALYSIS.json",
        "BACKUP_DUPLICATE_ANALYSIS.json",
        "HISTORY_DB_ANALYSIS.json",
        "STORAGE_DEEP_ANALYSIS.md",
    }
    assert {path.name for path in output.iterdir()} == expected

    sites_summary = _read_json(output / "SITES_SUMMARY.json")
    assert sites_summary["sites"][0]["site_name"] == "宁波地铁12号线"
    analysis = _read_json(output / "SITE_STORAGE_ANALYSIS.json")
    analysis_by_path = {item["path"]: item for item in analysis["top_directories"]}
    assert analysis_by_path["files/backups"]["size_bytes"] == 68
    backups = _read_json(output / "BACKUP_INVENTORY.json")
    assert len(backups["files"]) == 2
    assert backups["files"][0]["parent_site"] == "宁波地铁12号线"
    assert backups["files"][0]["classification"] in {"BACKUP", "ROLLBACK"}
    databases = _read_json(output / "ALL_SQLITE_DATABASES.json")
    assert {item["database"] for item in databases["databases"]} == {
        "宁波地铁12号线/db/tasks.db",
        "宁波地铁12号线/db/devices.db",
    }
    table_usage = _read_json(output / "TOP_TABLE_USAGE.json")
    assert any(item["table_name"] == "task_results" for item in table_usage["tables"])
    findings = (output / "ROOT_STORAGE_FINDINGS.md").read_text(encoding="utf-8")
    assert "## Site contribution" in findings
    assert "宁波地铁12号线" in findings
    assert "## Directory contribution" in findings
    assert "## Observations" in findings


def test_sites_root_cli_writes_summary(tmp_path: Path) -> None:
    source = tmp_path / "SITE_STORAGE_INVENTORY.json"
    source.write_text(
        json.dumps(
            {
                "root_path": "D:/sites",
                "total_size_bytes": 0,
                "total_files": 0,
                "directories": [{"path": "空 Site", "size_bytes": 0, "file_count": 0}],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "SITES_SUMMARY.json"

    assert main(["--input", str(source), "--output", str(output)]) == 0
    assert _read_json(output)["sites"][0]["site_name"] == "空 Site"
