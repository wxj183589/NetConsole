from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade import backup_store as backup_store_module
from netconsole.services.database_upgrade.backup_lifecycle import BackupLifecycleService
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT NOT NULL)")
        connection.execute("DELETE FROM marker")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        connection.commit()


def _create(store: DatabaseBackupStore, source: Path, task_id: str) -> dict[str, object]:
    return store.create(
        source_path=source,
        database_kind="devices",
        scope_type="site",
        scope_id="line-12",
        task_id=task_id,
        old_version="v1",
        target_version="v2",
        strategy="SCHEMA_MIGRATION",
        reason="pytest lifecycle",
    )


def test_same_source_revision_reuses_verified_full_backup_and_restart(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "devices.db"
    _database(source, "revision-1")
    store = DatabaseBackupStore(paths)

    first = _create(store, source, "operation-1")
    second = _create(store, source, "operation-2")

    assert second["reused"] is True
    assert second["backup_id"] == first["backup_id"]
    assert second["source_revision"] == first["source_revision"]
    assert len(list(paths.database_upgrade_backups_dir.rglob("database.sqlite"))) == 1
    restarted = DatabaseBackupStore(PathResolver(data_root=tmp_path))
    persisted = restarted.read(str(first["backup_id"]))
    assert persisted["authority_status"] == "VERIFIED"
    assert persisted["reuse_count"] == 1
    assert persisted["last_reuse_task_id"] == "operation-2"

    _database(source, "revision-2")
    third = _create(store, source, "operation-3")
    assert third["reused"] is False
    assert third["backup_id"] != first["backup_id"]
    assert len(list(paths.database_upgrade_backups_dir.rglob("database.sqlite"))) == 2


def test_interrupted_backup_is_never_published_as_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "devices.db"
    _database(source, "revision-1")

    def fail_after_partial(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("injected backup interruption")

    monkeypatch.setattr(backup_store_module, "sqlite_backup", fail_after_partial)
    with pytest.raises(OSError, match="interruption"):
        _create(DatabaseBackupStore(paths), source, "operation-interrupted")

    manifest_path = next(paths.database_upgrade_backups_dir.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["result_status"] == "CREATION_FAILED"
    assert manifest["authority_status"] == "PREPARING"
    assert manifest["result_status"] != "VALID_BACKUP"


def test_backup_lifecycle_protects_active_unknown_and_reports_exact_duplicate(
    tmp_path: Path,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "devices.db"
    _database(source, "revision-1")
    store = DatabaseBackupStore(paths)
    first = _create(store, source, "operation-1")
    first_dir = Path(str(first["path"]))
    duplicate_dir = first_dir.parent / "manual-duplicate"
    shutil.copytree(first_dir, duplicate_dir)
    manifest_path = duplicate_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        backup_id="manual-duplicate",
        backup_database_path=str(duplicate_dir / "database.sqlite"),
        created_at="2020-01-01T00:00:00+00:00",
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    unknown = paths.database_upgrade_backups_dir / "unknown-owner"
    unknown.mkdir(parents=True)
    (unknown / "database.sqlite").write_bytes(b"unknown")

    plan = BackupLifecycleService(paths).preview_retirement(
        keep_revisions=1,
        protected_backup_ids={"manual-duplicate"},
    )

    protected = {item["backup_id"]: item for item in plan["protected"]}
    assert protected["manual-duplicate"]["reason"] == "ACTIVE_REFERENCE"
    assert plan["unknown"] == [
        {
            "path": str(unknown),
            "classification": "UNKNOWN",
            "action": "PROTECT",
            "reason": "MISSING_MANIFEST",
        }
    ]
    unprotected = BackupLifecycleService(paths).preview_retirement(keep_revisions=1)
    assert unprotected["retire"][0]["reason"] == "SUPERSEDED_EXACT_DUPLICATE"


def test_backup_retirement_rehearsal_is_exact_and_rejects_stale_plan(
    tmp_path: Path,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "devices.db"
    store = DatabaseBackupStore(paths)
    for index in range(3):
        _database(source, f"revision-{index}")
        _create(store, source, f"operation-{index}")

    lifecycle = BackupLifecycleService(paths)
    stale = lifecycle.preview_retirement(keep_revisions=1)
    _database(source, "revision-new")
    _create(store, source, "operation-new")
    with pytest.raises(ValueError, match="inventory changed"):
        lifecycle.apply_retirement(
            stale,
            expected_plan_digest=str(stale["plan_digest"]),
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path,
        )

    plan = lifecycle.preview_retirement(keep_revisions=1)
    result = lifecycle.apply_retirement(
        plan,
        expected_plan_digest=str(plan["plan_digest"]),
        apply=True,
        allow_development_root_only=True,
        development_root=tmp_path,
    )
    assert result["deleted_count"] == 3
    assert len(DatabaseBackupStore(paths).list()) == 1


def test_backup_retirement_rejects_empty_scope_and_non_development_root(
    tmp_path: Path,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "devices.db"
    _database(source, "revision-1")
    _create(DatabaseBackupStore(paths), source, "operation-1")
    lifecycle = BackupLifecycleService(paths)
    empty = lifecycle.preview_retirement(keep_revisions=2)
    assert empty["empty_scope"] is True
    with pytest.raises(ValueError, match="scope must not be empty"):
        lifecycle.apply_retirement(
            empty,
            expected_plan_digest=str(empty["plan_digest"]),
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path,
        )

    _database(source, "revision-2")
    _create(DatabaseBackupStore(paths), source, "operation-2")
    plan = lifecycle.preview_retirement(keep_revisions=1)
    with pytest.raises(ValueError, match="must be under"):
        lifecycle.apply_retirement(
            plan,
            expected_plan_digest=str(plan["plan_digest"]),
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path / "unrelated-root",
        )
