from __future__ import annotations

import json
from pathlib import Path

from scripts.storage.analyze_site_storage import analyze_site_storage, main


def _inventory() -> dict[str, object]:
    return {
        "generated_at": "2026-08-21T00:00:00+00:00",
        "root_path": "D:/test/site",
        "total_size_bytes": 400,
        "total_files": 4,
        "directories": [
            {"path": "sync", "size_bytes": 20, "file_count": 1},
            {"path": "files/imports", "size_bytes": 50, "file_count": 1},
            {"path": "files", "size_bytes": 200, "file_count": 2},
            {"path": "db", "size_bytes": 100, "file_count": 1},
            {"path": "files/backups", "size_bytes": 150, "file_count": 1},
        ],
        "errors": [],
    }


def test_directory_share_uses_non_overlapping_depth_one_entries() -> None:
    report = analyze_site_storage(_inventory())

    assert [item["path"] for item in report["top_directories"]] == ["files", "db", "sync"]
    assert [item["percentage"] for item in report["top_directories"]] == [50.0, 25.0, 5.0]


def test_directory_share_can_analyze_nested_paths(tmp_path: Path) -> None:
    source = tmp_path / "SITE_STORAGE_INVENTORY.json"
    source.write_text(json.dumps(_inventory()), encoding="utf-8")

    report = analyze_site_storage(source, depth=2)

    assert [item["path"] for item in report["top_directories"]] == [
        "files/backups",
        "files/imports",
    ]


def test_main_writes_analysis_json(tmp_path: Path) -> None:
    source = tmp_path / "SITE_STORAGE_INVENTORY.json"
    output = tmp_path / "SITE_STORAGE_ANALYSIS.json"
    source.write_text(json.dumps(_inventory()), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["top_directories"][0]["path"] == "files"
