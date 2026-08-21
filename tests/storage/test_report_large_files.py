from __future__ import annotations

from pathlib import Path

from scripts.storage.report_large_files import large_files_report


def test_large_file_report_matches_extensions_and_path_keywords(tmp_path: Path) -> None:
    (tmp_path / "db").mkdir()
    (tmp_path / "backup").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "staging").mkdir()
    (tmp_path / "db" / "tasks.db").write_bytes(b"123")
    (tmp_path / "backup" / "archive.bak").write_bytes(b"12345678")
    (tmp_path / "logs" / "service.log").write_bytes(b"1234")
    (tmp_path / "staging" / "part.tmp").write_bytes(b"12")
    (tmp_path / "archive.zip").write_bytes(b"12345")
    (tmp_path / "ignored.txt").write_bytes(b"123456789")

    report = large_files_report(tmp_path)

    assert [item["path"] for item in report["large_files"]] == [
        "backup/archive.bak",
        "archive.zip",
        "logs/service.log",
        "db/tasks.db",
        "staging/part.tmp",
    ]
    by_path = {item["path"]: item for item in report["large_files"]}
    assert by_path["db/tasks.db"]["classification"] == "DATABASE"
    assert by_path["backup/archive.bak"]["classification"] == "BACKUP_LIKE"
    assert by_path["backup/archive.bak"]["matched_keywords"] == ["backup"]
    assert by_path["logs/service.log"]["classification"] == "LOG"
    assert by_path["archive.zip"]["classification"] == "ARCHIVE"
    assert by_path["staging/part.tmp"]["classification"] == "BACKUP_LIKE"
