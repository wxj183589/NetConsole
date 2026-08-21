from __future__ import annotations

import json
from pathlib import Path

from scripts.storage.audit_site import audit_site, main


def test_empty_directory_has_zero_size_and_no_entries(tmp_path: Path) -> None:
    report = audit_site(tmp_path)

    assert report["root"] == str(tmp_path.resolve())
    assert report["total_bytes"] == 0
    assert report["file_count"] == 0
    assert report["directories"] == []
    assert report["largest_files"] == []


def test_multiple_files_and_nested_directory_are_reported(tmp_path: Path) -> None:
    (tmp_path / "small.txt").write_bytes(b"12")
    nested = tmp_path / "site-a"
    nested.mkdir()
    (nested / "large.bin").write_bytes(b"12345")

    report = audit_site(tmp_path)

    assert report["total_bytes"] == 7
    assert report["file_count"] == 2
    assert {item["path"] for item in report["directories"]} == {"site-a"}
    assert report["directories"][0]["size_bytes"] == 5
    assert report["directories"][0]["file_count"] == 1
    assert [item["path"] for item in report["largest_files"]] == [
        "site-a/large.bin",
        "small.txt",
    ]


def test_extension_statistics_are_aggregated_and_stably_sorted(tmp_path: Path) -> None:
    (tmp_path / "first.DB").write_bytes(b"1234")
    (tmp_path / "second.db").write_bytes(b"567")
    (tmp_path / "readme.txt").write_bytes(b"12")

    report = audit_site(tmp_path)

    assert report["extensions"] == [
        {"extension": ".db", "size_bytes": 7, "file_count": 2},
        {"extension": ".txt", "size_bytes": 2, "file_count": 1},
    ]


def test_json_output_is_stable_except_for_generation_timestamp(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"payload")
    output = tmp_path / "SITE_STORAGE_INVENTORY.json"

    assert main(["--path", str(tmp_path), "--output", str(output)]) == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    assert main(["--path", str(tmp_path), "--output", str(output)]) == 0
    second = json.loads(output.read_text(encoding="utf-8"))

    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_largest_file_limit_and_size_statistics(tmp_path: Path) -> None:
    for name, content in (("a.bin", b"a"), ("b.bin", b"bb"), ("c.bin", b"ccc")):
        (tmp_path / name).write_bytes(content)

    report = audit_site(tmp_path, largest_file_count=2)

    assert report["total_bytes"] == 6
    assert report["file_count"] == 3
    assert [item["size_bytes"] for item in report["largest_files"]] == [3, 2]
    assert all("modified_time" in item for item in report["largest_files"])


def test_main_writes_json_report(tmp_path: Path, capsys) -> None:
    (tmp_path / "data.txt").write_text("content", encoding="utf-8")
    output = tmp_path / "report.json"

    assert main(["--path", str(tmp_path), "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["total_bytes"] == len("content".encode("utf-8"))
    assert payload["file_count"] == 1
    assert payload["largest_files"][0]["path"] == "data.txt"
    assert json.loads(capsys.readouterr().out)["root"] == str(tmp_path.resolve())
