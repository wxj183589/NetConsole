from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.coordinator import DatabaseUpgradeCoordinator
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.history import LegacyDatabaseArchiveService
from netconsole.services.database_upgrade.journal import DatabaseUpgradeJournal, recover_incomplete_upgrades
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.database_upgrade.models import DatabaseDescriptor, DatabaseUpgradeStrategy
from netconsole.services.database_upgrade.sqlite_consistency import validate_sqlite
from netconsole.services.mesh_storage_service import MeshStorageService


@dataclass
class _Adapter:
    build_error: str = ""
    invalid_shadow: bool = False
    switch_error: str = ""

    def build_shadow(self, descriptor, shadow_path, *, progress, should_cancel):
        if self.build_error:
            raise RuntimeError(self.build_error)
        if self.invalid_shadow:
            shadow_path.write_bytes(b"not a sqlite database")
            return {"built": False}
        with closing(sqlite3.connect(shadow_path)) as conn:
            conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
            conn.execute("INSERT INTO marker(value) VALUES ('new')")
            conn.commit()
        return {"built": True}

    def validate(self, path: Path):
        return validate_sqlite(path)

    def switch(self, descriptor, shadow_path, rollback_path):
        if descriptor.database_path.exists():
            descriptor.database_path.replace(rollback_path)
        shadow_path.replace(descriptor.database_path)
        if self.switch_error:
            raise RuntimeError(self.switch_error)

    def rollback(self, descriptor, rollback_path, failed_shadow_path, failure_dir):
        failure_dir.mkdir(parents=True, exist_ok=True)
        failed = failure_dir / "failed_new_database.sqlite"
        if descriptor.database_path.exists():
            descriptor.database_path.replace(failed)
        if failed_shadow_path.exists():
            failed_shadow_path.replace(failed)
        if rollback_path.exists():
            rollback_path.replace(descriptor.database_path)

    def discard_shadow(self, shadow_path, failure_dir):
        failure_dir.mkdir(parents=True, exist_ok=True)
        if shadow_path.exists():
            shadow_path.replace(failure_dir / "failed_new_database.sqlite")

    def finalize_success(self, descriptor, rollback_path, backup_dir):
        if rollback_path.exists():
            rollback_path.replace(backup_dir / "rollback.sqlite")
        return {"retained": True}


def _create_database(path: Path, *, value: str = "old", wal: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        if wal:
            assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() == "wal"
        conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        conn.commit()


def _descriptor(paths: PathResolver, path: Path, adapter: _Adapter, *, smoke=None) -> DatabaseDescriptor:
    return DatabaseDescriptor(
        database_kind="test_database",
        scope_type="global",
        scope_id="test",
        database_path=path,
        current_version="v1",
        target_version="v2",
        strategy=DatabaseUpgradeStrategy.SCHEMA_MIGRATION,
        adapter=adapter,
        maintenance_lock="test-database",
        smoke_test=smoke,
    )


def _marker(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return str(conn.execute("SELECT value FROM marker LIMIT 1").fetchone()[0])


def test_batch_upgrade_preflights_profiles_and_auto_backups_each_incompatible_database(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    incompatible = storage.create_mr_profile("列车07-MR-CT")
    compatible = storage.create_mr_profile("列车07-MR-CW")
    incompatible_index = paths.mesh_mr_db_path("demo", incompatible.safe_folder_name)
    with closing(sqlite3.connect(incompatible_index)) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()

    result = DatabaseUpgradeManagementService(paths).batch_upgrade(
        "demo",
        [incompatible.mr_id, compatible.mr_id],
        task_id="batch-upgrade-test",
    )

    statuses = {item["profile_id"]: item["status"] for item in result["results"]}
    assert result["total"] == 2
    assert statuses == {incompatible.mr_id: "success", compatible.mr_id: "skipped"}
    assert result["failed"] == 0
    assert result["partial"] is False
    assert len(list(paths.database_upgrade_backups_dir.rglob("manifest.json"))) == 1


def test_wal_data_is_in_verified_backup_and_old_database_is_retained(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active, value="wal-value", wal=True)

    result = DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter()))

    backup_dir = Path(result.backup_path)
    assert _marker(backup_dir / "database.sqlite") == "wal-value"
    assert result.backup_validation["integrity_check"] == "ok"
    assert (backup_dir / "manifest.json").is_file()
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database_sha256"] == result.backup_validation["sha256"]
    assert _marker(active) == "new"
    assert _marker(backup_dir / "rollback.sqlite") == "wal-value"
    assert not active.with_name(active.name + "-wal").exists()
    assert not active.with_name(active.name + "-shm").exists()


def test_checkpoint_failure_does_not_create_or_replace_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active, wal=True)
    before = active.read_bytes()
    monkeypatch.setattr(
        "netconsole.services.database_upgrade.coordinator.checkpoint_wal",
        lambda _path: (_ for _ in ()).throw(RuntimeError("checkpoint busy")),
    )
    with pytest.raises(RuntimeError, match="checkpoint busy"):
        DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter()))
    assert active.read_bytes() == before
    assert not list(paths.database_upgrade_backups_dir.rglob("manifest.json"))


def test_checkpoint_failure_reopens_closed_database_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active, wal=True)
    events: list[str] = []
    descriptor = _descriptor(paths, active, _Adapter())
    descriptor = DatabaseDescriptor(
        **{
            **descriptor.__dict__,
            "close_hook": lambda: events.append("close"),
            "reopen_hook": lambda: events.append("reopen"),
        }
    )
    monkeypatch.setattr(
        "netconsole.services.database_upgrade.coordinator.checkpoint_wal",
        lambda _path: (_ for _ in ()).throw(RuntimeError("checkpoint busy")),
    )

    with pytest.raises(RuntimeError, match="checkpoint busy"):
        DatabaseUpgradeCoordinator(paths).upgrade(descriptor)

    assert events == ["close", "reopen"]
    assert _marker(active) == "old"


def test_shadow_build_failure_keeps_active_and_retains_verified_backup(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)

    with pytest.raises(RuntimeError, match="parser failed"):
        DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter(build_error="parser failed")))

    assert _marker(active) == "old"
    backups = list(paths.database_upgrade_backups_dir.rglob("manifest.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["result_status"] == "VALID_BACKUP"


def test_shadow_validation_failure_does_not_switch_active(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)

    with pytest.raises(RuntimeError, match="完整性校验失败"):
        DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter(invalid_shadow=True)))

    assert _marker(active) == "old"
    diagnostics = list(paths.database_upgrade_backups_dir.rglob("failed_new_database.sqlite"))
    assert len(diagnostics) == 1
    assert diagnostics[0].read_bytes() == b"not a sqlite database"


def test_partial_switch_failure_restores_active_database(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)

    with pytest.raises(RuntimeError, match="switch failed"):
        DatabaseUpgradeCoordinator(paths).upgrade(
            _descriptor(paths, active, _Adapter(switch_error="switch failed"))
        )

    assert _marker(active) == "old"
    failed = list(paths.database_upgrade_backups_dir.rglob("failed_new_database.sqlite"))
    assert len(failed) == 1
    assert _marker(failed[0]) == "new"


def test_smoke_failure_restores_rollback_database(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)

    with pytest.raises(RuntimeError, match="smoke test"):
        DatabaseUpgradeCoordinator(paths).upgrade(
            _descriptor(paths, active, _Adapter(), smoke=lambda _path: {"valid": False, "error": "broken"})
        )

    assert _marker(active) == "old"
    failed = list(paths.database_upgrade_backups_dir.rglob("failed_new_database.sqlite"))
    assert len(failed) == 1
    assert _marker(failed[0]) == "new"


def test_smoke_failure_for_first_creation_restores_missing_database_state(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"

    with pytest.raises(RuntimeError, match="smoke test"):
        DatabaseUpgradeCoordinator(paths).upgrade(
            _descriptor(paths, active, _Adapter(), smoke=lambda _path: {"valid": False})
        )

    assert not active.exists()
    failed = list(paths.database_upgrade_backups_dir.rglob("failed_new_database.sqlite"))
    assert len(failed) == 1
    assert _marker(failed[0]) == "new"
    manifest = json.loads(next(paths.database_upgrade_backups_dir.rglob("manifest.json")).read_text(encoding="utf-8"))
    assert manifest["result_status"] == "NO_EXISTING_DATABASE"


def test_repeated_upgrades_reuse_the_same_verified_source_revision(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)

    results = [
        DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter()))
        for _ in range(3)
    ]

    manifests = list(paths.database_upgrade_backups_dir.rglob("manifest.json"))
    assert len(manifests) == 2
    backup_ids = {json.loads(path.read_text(encoding="utf-8"))["backup_id"] for path in manifests}
    assert len(backup_ids) == 2
    assert results[1].backup_id == results[2].backup_id
    assert all((path.parent / "database.sqlite").stat().st_size > 0 for path in manifests)


def test_cancel_after_backup_keeps_verified_backup_and_active_database(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(RuntimeError, match="已取消"):
        DatabaseUpgradeCoordinator(paths).upgrade(
            _descriptor(paths, active, _Adapter()),
            should_cancel=cancelled,
        )

    assert _marker(active) == "old"
    backups = list(paths.database_upgrade_backups_dir.rglob("database.sqlite"))
    assert len(backups) == 1
    assert _marker(backups[0]) == "old"


def test_invalid_backup_validation_stops_before_shadow_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)
    store = DatabaseBackupStore(paths)
    invalid_dir = paths.database_upgrade_backups_dir / "invalid"
    invalid_dir.mkdir(parents=True)
    monkeypatch.setattr(
        store,
        "create",
        lambda **_kwargs: {
            "backup_id": "invalid",
            "path": str(invalid_dir),
            "validation": {"valid": False, "integrity_check": "failed"},
        },
    )

    with pytest.raises(RuntimeError, match="旧数据库备份完整性校验失败"):
        DatabaseUpgradeCoordinator(paths, backup_store=store).upgrade(_descriptor(paths, active, _Adapter()))

    assert _marker(active) == "old"
    assert not list(active.parent.glob("active.sqlite.new.*"))


def test_zero_byte_active_database_is_not_treated_as_missing(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    active.touch()

    with pytest.raises(RuntimeError, match="旧数据库备份完整性校验失败"):
        DatabaseUpgradeCoordinator(paths).upgrade(_descriptor(paths, active, _Adapter()))

    manifest = next(paths.database_upgrade_backups_dir.rglob("manifest.json"))
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value["result_status"] == "ZERO_BYTE_ARCHIVE"
    assert value["integrity_check_result"]["exists"] is True
    assert not active.with_name("active.sqlite.new").exists()


def test_restore_creates_safety_backup_for_current_database(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active, value="selected-backup")
    selected = DatabaseBackupStore(paths).create(
        source_path=active,
        database_kind="test_database",
        scope_type="global",
        scope_id="test",
        task_id="seed",
        old_version="v1",
        target_version="v2",
        strategy="SCHEMA_MIGRATION",
    )
    with closing(sqlite3.connect(active)) as connection:
        connection.execute("UPDATE marker SET value = 'current-before-restore'")
        connection.commit()

    result = DatabaseUpgradeManagementService(paths).restore_backup(
        str(selected["backup_id"]),
        confirmed=True,
    )

    assert _marker(active) == "selected-backup"
    assert Path(str(selected["path"]), "database.sqlite").is_file()
    safety = DatabaseBackupStore(paths).read(str(result["safety_backup_id"]))
    assert _marker(Path(str(safety["path"]), "database.sqlite")) == "current-before-restore"
    assert _marker(Path(str(safety["path"]), "rollback.sqlite")) == "current-before-restore"


def test_backup_validation_rejects_content_changed_after_manifest_creation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active)
    store = DatabaseBackupStore(paths)
    backup = store.create(
        source_path=active,
        database_kind="test_database",
        scope_type="global",
        scope_id="test",
        task_id="seed",
        old_version="v1",
        target_version="v2",
        strategy="SCHEMA_MIGRATION",
    )
    database = Path(str(backup["path"])) / "database.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO marker(value) VALUES ('tampered')")
        connection.commit()

    result = store.validate(str(backup["backup_id"]))

    assert result["validation"]["integrity_check"] == "ok"
    assert result["validation"]["sha256_matches"] is False
    assert result["validation"]["valid"] is False
    assert result["result_status"] == "INVALID_DATABASE"
    manifest = json.loads((Path(str(backup["path"])) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database_sha256"] == backup["database_sha256"]
    assert manifest["result_status"] == "INVALID_DATABASE"


def test_legacy_archive_organizer_retains_valid_and_zero_byte_files(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    profile_root = paths.site_mesh_root("demo") / "列车07-MR-CT"
    profile_root.mkdir(parents=True)
    valid = profile_root / "mesh.sqlite.schema_archive_20260807"
    zero = profile_root / "mesh.sqlite.legacy_zero"
    _create_database(valid, value="legacy")
    zero.touch()

    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["found_count"] == 2
    assert result["moved_count"] == 2
    assert result["valid_count"] == 1
    assert result["duplicate_count"] == 0
    assert result["invalid_count"] == 1
    assert not valid.exists() and not zero.exists()
    statuses = {item["result_status"] for item in result["items"]}
    assert statuses == {"VALID_BACKUP", "ZERO_BYTE_ARCHIVE"}
    assert len(list((paths.database_upgrade_backups_dir / "_invalid").rglob("database.sqlite"))) == 1
    assert LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")["found_count"] == 0


def test_legacy_archive_organizer_marks_duplicate_content_without_deleting_backup(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "active.sqlite"
    _create_database(active, value="duplicate")
    existing = DatabaseBackupStore(paths).create(
        source_path=active,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:列车07-MR-CT",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="REBUILD_FROM_SOURCE",
    )
    profile_root = paths.site_mesh_root("demo") / "列车07-MR-CT"
    profile_root.mkdir(parents=True)
    legacy = profile_root / "mesh.sqlite.rollback_duplicate"
    legacy.write_bytes((Path(str(existing["path"])) / "database.sqlite").read_bytes())

    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["duplicate_count"] == 1
    duplicate = result["items"][0]
    assert duplicate["result_status"] == "DUPLICATE_BACKUP"
    assert duplicate["duplicate_of_backup_id"] == existing["backup_id"]
    assert Path(str(existing["path"]), "database.sqlite").is_file()
    assert Path(str(duplicate["path"]), "database.sqlite").is_file()
    assert not legacy.exists()


def test_legacy_archive_organizer_marks_prepared_orphan_and_retries_source(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    profile_root = paths.site_mesh_root("demo") / "列车07-MR-CT"
    profile_root.mkdir(parents=True)
    source = profile_root / "mesh.sqlite.schema_archive_interrupted"
    _create_database(source, value="legacy")
    orphan = paths.database_upgrade_backups_dir / "site_profile" / "demo_列车07-MR-CT" / "mesh_derived" / "legacy_orphan"
    orphan.mkdir(parents=True)
    manifest = {
        "backup_id": "legacy_orphan",
        "task_id": "legacy_database_archive_migration",
        "database_kind": "mesh_derived",
        "scope_type": "site_profile",
        "scope_id": "demo:列车07-MR-CT",
        "original_database_path": str(source),
        "backup_database_path": str(orphan / "database.sqlite"),
        "database_size": source.stat().st_size,
        "database_sha256": "pending",
        "migration_state": "PREPARED",
        "result_status": "MIGRATION_IN_PROGRESS",
    }
    (orphan / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["recovered_count"] == 1
    assert result["moved_count"] == 1
    assert result["items"][0]["result_status"] == "VALID_BACKUP"
    abandoned = json.loads((orphan / "manifest.json").read_text(encoding="utf-8"))
    assert abandoned["migration_state"] == "ABANDONED"
    assert abandoned["result_status"] == "UNREADABLE_DATABASE"
    assert not source.exists()


def test_incomplete_switch_journal_restores_database_and_parsed_directory(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "profile" / "mesh.sqlite"
    rollback = active.with_name("mesh.sqlite.rollback.operation-1")
    shadow = active.with_name("mesh.sqlite.new.operation-1")
    _create_database(active, value="old")
    backup = DatabaseBackupStore(paths).create(
        source_path=active,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        task_id="operation-1",
        old_version="old",
        target_version="new",
        strategy="REBUILD_FROM_SOURCE",
    )
    active.replace(rollback)
    _create_database(shadow, value="new")
    shadow.replace(active)
    active_parsed = active.parent / "parsed"
    rollback_parsed = active.parent / "parsed.rollback.operation-1"
    active_parsed.mkdir()
    rollback_parsed.mkdir()
    (active_parsed / "value.txt").write_text("new", encoding="utf-8")
    (rollback_parsed / "value.txt").write_text("old", encoding="utf-8")
    DatabaseUpgradeJournal(paths, "operation-1").update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        backup_id=str(backup["backup_id"]),
        backup_path=str(backup["path"]),
        adapter_state={
            "active_parsed_path": str(active_parsed),
            "shadow_parsed_path": "",
            "rollback_parsed_path": str(rollback_parsed),
        },
    )

    recovered = recover_incomplete_upgrades(paths)

    assert recovered[0]["stage"] == "recovered_rollback"
    assert _marker(active) == "old"
    assert (active_parsed / "value.txt").read_text(encoding="utf-8") == "old"
    assert _marker(next(Path(str(backup["path"])).glob("failed_recovered_database.sqlite*"))) == "new"
    assert (next(Path(str(backup["path"])).glob("failed_recovered_parsed*")) / "value.txt").read_text(encoding="utf-8") == "new"


def test_smoke_validated_journal_keeps_new_database_and_retains_old_artifact(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active = tmp_path / "profile" / "mesh.sqlite"
    rollback = active.with_name("mesh.sqlite.rollback.operation-2")
    shadow = active.with_name("mesh.sqlite.new.operation-2")
    _create_database(active, value="old")
    backup = DatabaseBackupStore(paths).create(
        source_path=active,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        task_id="operation-2",
        old_version="old",
        target_version="new",
        strategy="REBUILD_FROM_SOURCE",
    )
    active.replace(rollback)
    _create_database(shadow, value="new")
    shadow.replace(active)
    DatabaseUpgradeJournal(paths, "operation-2").update(
        "smoke_validated",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        backup_id=str(backup["backup_id"]),
        backup_path=str(backup["path"]),
        switched=True,
    )

    recovered = recover_incomplete_upgrades(paths)

    assert recovered[0]["stage"] == "recovered_new_database"
    assert _marker(active) == "new"
    assert _marker(next(Path(str(backup["path"])).glob("rollback_recovered.sqlite"))) == "old"
