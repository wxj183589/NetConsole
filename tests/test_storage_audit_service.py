import json
from pathlib import Path

from netconsole.services.storage_audit import StorageAuditService


def test_storage_audit_service_reads_existing_reports_without_scanning(tmp_path: Path) -> None:
    report = tmp_path / "all-sites"
    report.mkdir()
    payloads = {
        "SITE_STORAGE_INVENTORY.json": {"root_path": "D:/sites", "generated_at": "2026-08-24T00:00:00Z", "total_size_bytes": 1000, "total_files": 3, "largest_files": [{"path": "large.db", "size_bytes": 800, "modified_time": "now"}]},
        "SITE_STORAGE_ANALYSIS.json": {"top_directories": [{"path": "files", "size_bytes": 900, "file_count": 2, "percentage": 90}]},
        "SITES_SUMMARY.json": {"sites": [{"site_name": "宁波", "total_size_bytes": 1000, "total_files": 3}]},
        "ALL_SQLITE_DATABASES.json": {"databases": [{"database": "宁波/db/tasks.db", "site": "宁波", "size_bytes": 500}]},
    }
    for name, value in payloads.items():
        (report / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    snapshot = StorageAuditService(tmp_path, report).snapshot()
    assert snapshot["total_size_bytes"] == 1000
    assert snapshot["sites"][0]["site_name"] == "宁波"
    assert snapshot["directories"][0]["path"] == "files"
    assert snapshot["databases"][0]["database"].endswith("tasks.db")
    assert snapshot["read_only"] is True
