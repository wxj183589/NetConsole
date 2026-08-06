from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_storage_service import MeshStorageService
from scripts.maintenance.rebuild_mesh_parsed_data import apply_plan, build_plan


LINE = "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def test_rebuild_plan_is_dry_run_and_apply_preserves_raw(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("01-MR-CT")
    source = tmp_path / "meshlog.log"
    source.write_text("[1] 2025/12/03 10:12:33.579 (2)\n" + LINE + "\n", encoding="utf-8")
    MeshImportService("demo", paths).import_files(profile, [source])
    raw_file = next(paths.mesh_mr_raw_dir("demo", profile.safe_folder_name).rglob("*.log"))
    raw_bytes = raw_file.read_bytes()
    index_path = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with closing(sqlite3.connect(index_path)) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()

    plan = build_plan(paths, "demo")

    assert plan[0].action == "rebuild"
    assert not list(index_path.parent.glob("*.schema_archive_*"))
    result = apply_plan(paths, "demo", plan)
    assert result[0].action == "rebuilt"
    assert raw_file.read_bytes() == raw_bytes
    with closing(sqlite3.connect(index_path)) as connection:
        assert connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == SCHEMA_VERSION
    backups = list(paths.database_upgrade_backups_dir.rglob("manifest.json"))
    assert len(backups) == 1
    backup_dir = backups[0].parent
    assert (backup_dir / "database.sqlite").stat().st_size > 0
    assert (backup_dir / "validation.json").is_file()
    assert json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))["result_status"] == "VALID_BACKUP"


def test_rebuild_refuses_changed_raw_after_plan(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("01-MR-CT")
    raw_root = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name)
    raw_file = raw_root / "meshlog.log"
    raw_file.write_text("[1] 2025/12/03 10:12:33.579 (2)\n" + LINE + "\n", encoding="utf-8")
    index_path = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with closing(sqlite3.connect(index_path)) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()
    plan = build_plan(paths, "demo")
    raw_file.write_text(raw_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="原始日志在计划后发生变化"):
        apply_plan(paths, "demo", plan)


def test_rebuild_blocks_profile_without_raw(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    index_path = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with closing(sqlite3.connect(index_path)) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()

    plan = build_plan(paths, "demo")

    assert plan[0].action == "blocked"
    with pytest.raises(RuntimeError, match="无法从 raw 重建"):
        apply_plan(paths, "demo", plan)


def test_rebuild_dry_run_does_not_create_missing_catalog(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)

    assert build_plan(paths, "missing") == []
    assert not paths.mesh_catalog_path("missing").exists()
