from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from scripts.maintenance import collect_global_storage_inventory as collector
from scripts.maintenance.collect_global_storage_inventory import (
    GlobalStorageInventoryError,
    collect_data_root_global_inventory,
    collect_site_storage_inventory,
    main,
)
from scripts.maintenance.finalize_site_storage_audit import (
    _validate_global_inventory,
    _validate_raw_inventory,
)


def _create_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE events (
                id TEXT,
                source_id TEXT,
                created_at TEXT,
                payload_json TEXT,
                raw_blob BLOB
            );
            CREATE INDEX idx_events_source ON events(source_id);
            """
        )
        connection.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            [
                ("1", "source-a", "2026-01-01T00:00:00Z", "same", b"\x00\x01"),
                ("2", "source-a", "2026-01-02T00:00:00Z", "same", b"\x00\x01"),
                (
                    "3",
                    "source-b",
                    "2026-01-03T00:00:00Z",
                    "different",
                    b"\x02",
                ),
                (
                    "3",
                    "source-b",
                    "2026-01-03T00:00:00Z",
                    "different",
                    b"\x02",
                ),
            ],
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_global_inventory_excludes_sites_and_profiles_sqlite_readonly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data-root"
    database = root / "backups" / "database_upgrade" / "site" / "full" / "b1" / "backup.db"
    _create_database(database)
    ignored = root / "sites" / "line-12" / "db" / "devices.db"
    _create_database(ignored)
    (root / "temp" / "site-import-staging" / "operation").mkdir(parents=True)
    (root / "temp" / "site-import-staging" / "operation" / "payload.tmp").write_text(
        "staging", encoding="utf-8"
    )
    (root / "config").mkdir()
    (root / "config" / "settings.json").write_text("{}", encoding="utf-8")
    (root / "agent-data" / "tasks").mkdir(parents=True)
    (root / "agent-data" / "tasks" / "task.json").write_text(
        '{"state":"running"}', encoding="utf-8"
    )
    dangerous = root / "cache" / "dangerous"
    dangerous.mkdir(parents=True)
    (dangerous / "must-not-read.txt").write_text("protected", encoding="utf-8")

    original_reparse_check = collector._is_reparse_entry

    def treat_dangerous_as_reparse(
        entry: os.DirEntry[str], metadata: os.stat_result
    ) -> bool:
        return entry.name == "dangerous" or original_reparse_check(entry, metadata)

    monkeypatch.setattr(collector, "_is_reparse_entry", treat_dangerous_as_reparse)
    database_hash = _sha256(database)
    database_mtime = database.stat().st_mtime_ns
    ignored_hash = _sha256(ignored)

    inventory = collect_data_root_global_inventory(root)

    _validate_raw_inventory(inventory)
    _validate_global_inventory(inventory)
    paths = {str(item["path"]) for item in inventory["files"]}
    assert "backups/database_upgrade/site/full/b1/backup.db" in paths
    assert "temp/site-import-staging/operation/payload.tmp" in paths
    assert "config/settings.json" in paths
    assert "agent-data/tasks/task.json" in paths
    assert not any(path.casefold().startswith("sites/") for path in paths)
    assert "cache/dangerous/must-not-read.txt" not in paths
    assert {tuple(item.values()) for item in inventory["skipped_entries"]} >= {
        ("sites", "SITES_EXCLUDED"),
        ("cache/dangerous", "SYMLINK_OR_REPARSE_POINT"),
    }
    assert inventory["inventory_scope"] == "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    assert inventory["safety_contract"]["writes_to_data_root"] == 0
    assert inventory["production_metadata_verification"]["unchanged"] is True

    profile = inventory["sqlite_databases"][0]
    assert profile["path"] == "backups/database_upgrade/site/full/b1/backup.db"
    assert profile["profile_status"] == "PASS"
    assert profile["open_contract"] == "mode=ro&immutable=1"
    table = profile["tables"][0]
    assert table["name"] == "events"
    assert table["rows"] == 4
    assert table["logical_payload"] == {
        "text_bytes": 142,
        "blob_bytes": 6,
        "max_text_or_blob_bytes": 20,
        "large_value_threshold_bytes": 4096,
        "large_text_values": 0,
        "large_text_bytes": 0,
        "large_blob_values": 0,
        "large_blob_bytes": 0,
    }
    assert table["content_columns"]["payload_json"] == {
        "bytes": 26,
        "duplicate_values": 2,
        "distinct_hashes": 2,
    }
    assert table["content_columns"]["raw_blob"] == {
        "bytes": 6,
        "duplicate_values": 2,
        "distinct_hashes": 2,
    }
    assert table["identity_columns"]["source_id"] == {"distinct": 2}
    assert table["time_ranges"]["created_at"] == {
        "min": "2026-01-01T00:00:00Z",
        "max": "2026-01-03T00:00:00Z",
    }
    assert table["duplicate_content"]["duplicate_rows"] == 1
    assert table["duplicate_content"]["duplicate_rows_method"] == "EXACT_ROW_SHA256"
    assert table["classification"] == "UNKNOWN"
    assert table["indexes"][0]["name"] == "idx_events_source"
    assert table["indexes"][0]["columns"] == ["source_id"]
    assert profile["database_pragmas"]["page_size"] > 0

    assert _sha256(database) == database_hash
    assert database.stat().st_mtime_ns == database_mtime
    assert _sha256(ignored) == ignored_hash
    assert not database.with_name(f"{database.name}-wal").exists()
    assert not database.with_name(f"{database.name}-shm").exists()


def test_site_inventory_includes_complete_site_tree(tmp_path: Path) -> None:
    root = tmp_path / "site-root"
    database = root / "db" / "devices.db"
    _create_database(database)
    nested = root / "sites" / "evidence.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("site evidence", encoding="utf-8")

    inventory = collect_site_storage_inventory(root)

    _validate_raw_inventory(inventory)
    paths = {str(item["path"]) for item in inventory["files"]}
    assert inventory["inventory_scope"] == "SITE_ROOT"
    assert inventory["safety_contract"]["sites_excluded"] is False
    assert paths == {"db/devices.db", "sites/evidence.txt"}


def test_global_inventory_protects_nonempty_wal_instead_of_reporting_stale_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data-root"
    database = root / "backups" / "live.db"
    _create_database(database)
    database.with_name("live.db-wal").write_bytes(b"non-empty-wal")

    inventory = collect_data_root_global_inventory(root)

    profile = inventory["sqlite_databases"][0]
    assert profile["path"] == "backups/live.db"
    assert profile["profile_status"] == "ERROR_PROTECT"
    assert profile["wal_sidecar_bytes"] == len(b"non-empty-wal")
    assert "current database view is protected" in profile["profile_error"]
    assert profile["tables"] == []


def test_global_inventory_reports_file_duplicates_and_zip_without_extracting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data-root"
    first = root / "migrations" / "archive" / "first.bin"
    second = root / "backups" / "second.bin"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"duplicate")
    second.write_bytes(b"duplicate")
    archive = root / "temp" / "package.zip"
    archive.parent.mkdir(parents=True)
    import zipfile

    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("payload/data.txt", "evidence")

    inventory = collect_data_root_global_inventory(root)

    assert inventory["totals"]["exact_duplicate_groups"] == 1
    assert inventory["totals"]["exact_duplicate_bytes"] == len(b"duplicate")
    assert inventory["duplicate_groups"][0]["paths"] == [
        "backups/second.bin",
        "migrations/archive/first.bin",
    ]
    assert inventory["zip_archives"] == [
        {
            "path": "temp/package.zip",
            "bytes": archive.stat().st_size,
            "status": "PASS",
            "members": 1,
            "compressed_bytes": len(b"evidence"),
            "uncompressed_bytes": len(b"evidence"),
        }
    ]
    assert not (root / "payload").exists()


def test_global_inventory_cli_writes_outside_root_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data-root"
    root.mkdir()
    (root / "config.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "diagnostic" / "DATA_ROOT_GLOBAL_INVENTORY.json"

    assert main(["--data-root", str(root), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["inventory_scope"] == "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    with pytest.raises(FileExistsError):
        main(["--data-root", str(root), "--output", str(output)])
    with pytest.raises(GlobalStorageInventoryError, match="outside data root"):
        main(
            [
                "--data-root",
                str(root),
                "--output",
                str(root / "inventory.json"),
            ]
        )


def test_global_inventory_rejects_symlink_data_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(GlobalStorageInventoryError, match="symlink or reparse point"):
        collect_data_root_global_inventory(alias)
