from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from scripts.storage.analyze_backups import analyze_backup_duplicates, analyze_backups
from scripts.storage.analyze_history_db import analyze_history_db
from scripts.storage.analyze_rail_transit import analyze_rail_transit
from scripts.storage.generate_storage_deep_analysis import generate_deep_analysis


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_site(root: Path, name: str = "宁波 Site") -> Path:
    site = root / name
    rail = site / "files" / "rail_transit"
    _write(rail / "mesh" / "sample.db", b"a" * 10)
    _write(rail / "online" / "sample.log", b"b" * 20)
    _write(rail / "online" / "nested" / "sample.json", b"c" * 30)
    now = time.time()
    os.utime(rail / "mesh" / "sample.db", (now - 10 * 86400, now - 10 * 86400))
    os.utime(rail / "online" / "sample.log", (now - 200 * 86400, now - 200 * 86400))
    os.utime(rail / "online" / "nested" / "sample.json", (now - 500 * 86400, now - 500 * 86400))

    _write(site / "files" / "backups" / "production-maintenance" / "database.sqlite", b"same backup")
    _write(site / "files" / "backups" / "database-migrations" / "copy.db", b"same backup")
    _write(site / "files" / "backups" / "rollback" / "rollback.sqlite", b"rollback")

    history = site / "db" / "history" / "devices-2026-07.db"
    history.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(history) as connection:
        connection.execute("CREATE TABLE history_events (value TEXT)")
        connection.executemany("INSERT INTO history_events VALUES (?)", [("x" * 100,), ("y" * 100,)])
        connection.commit()
    return site


def test_rail_transit_directories_extensions_and_timeline(tmp_path: Path) -> None:
    site = _make_site(tmp_path)

    report = analyze_rail_transit(site)

    assert report["total_size_bytes"] == 60
    assert report["total_files"] == 3
    by_extension = {item["extension"]: item for item in report["extension_summary"]}
    assert by_extension[".db"]["size_bytes"] == 10
    assert by_extension[".log"]["file_count"] == 1
    assert by_extension[".json"]["size_bytes"] == 30
    by_period = {item["period"]: item for item in report["timeline"]}
    assert by_period["last_30_days"]["size_bytes"] == 10
    assert by_period["last_365_days"]["size_bytes"] == 20
    assert by_period["over_365_days"]["size_bytes"] == 30
    assert report["directories"][0]["path"] == "online"


def test_backup_classification_and_duplicate_hashes(tmp_path: Path) -> None:
    site = _make_site(tmp_path)

    report = analyze_backups(site)
    by_path = {item["path"]: item for item in report["backups"]}
    assert by_path["files/backups/production-maintenance/database.sqlite"]["backup_type"] == "PRODUCTION_MAINTENANCE"
    assert by_path["files/backups/database-migrations/copy.db"]["backup_type"] == "DATABASE_MIGRATION"
    assert by_path["files/backups/rollback/rollback.sqlite"]["backup_type"] == "ROLLBACK"

    duplicates = analyze_backup_duplicates(site, report)
    assert len(duplicates["duplicates"]) == 1
    assert len(duplicates["duplicates"][0]["files"]) == 2


def test_history_analysis_reports_tables_read_only(tmp_path: Path) -> None:
    site = _make_site(tmp_path)
    database = site / "db" / "history" / "devices-2026-07.db"
    before = database.stat().st_mtime_ns

    report = analyze_history_db(site)

    assert report["total_files"] == 1
    assert report["databases"][0]["filename"] == "devices-2026-07.db"
    assert any(table["table_name"] == "history_events" for table in report["databases"][0]["tables"])
    assert database.stat().st_mtime_ns == before


def test_deep_generator_supports_sites_root_and_summary(tmp_path: Path) -> None:
    sites = tmp_path / "sites"
    _make_site(sites)
    _write(sites / "另一个 Site" / "files" / "rail_transit" / "extra.csv", b"z" * 5)
    output = tmp_path / "deep-report"

    result = generate_deep_analysis(sites, output)

    assert result["rail_transit"]["total_size_bytes"] == 65
    assert set(path.name for path in output.iterdir()) == {
        "RAIL_TRANSIT_ANALYSIS.json",
        "RAIL_TRANSIT_TIMELINE.json",
        "BACKUP_ANALYSIS.json",
        "BACKUP_DUPLICATE_ANALYSIS.json",
        "HISTORY_DB_ANALYSIS.json",
        "STORAGE_DEEP_ANALYSIS.md",
    }
    summary = (output / "STORAGE_DEEP_ANALYSIS.md").read_text(encoding="utf-8")
    assert "# Storage Deep Analysis" in summary
    assert "## rail_transit" in summary
    assert "## backups" in summary
    assert "## db/history" in summary
    assert "建议删除" not in summary
    assert json.loads((output / "BACKUP_ANALYSIS.json").read_text(encoding="utf-8"))["total_files"] == 3
