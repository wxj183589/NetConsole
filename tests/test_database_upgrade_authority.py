from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.authority import (
    DATABASE_BACKUP_DELETE_AUTHORIZED,
    DATABASE_BACKUP_RESTORE_AUTHORIZED,
    LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    DATABASE_UPGRADE_AUTHORIZED,
    DatabaseMaintenanceAuthorityError,
    build_database_task_authority,
    revalidate_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.repositories.mesh_mr_repository import MeshMrRepository


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT NOT NULL)")
        connection.execute("DELETE FROM marker")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        connection.commit()


def _mesh_profile(paths, name: str = "列车07-MR-CT"):
    profile = MeshStorageService("demo", paths).create_mr_profile(name)
    database = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    MeshMrRepository(database)
    return profile, database


def test_database_task_authority_uses_operation_specific_capabilities(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )

    upgrade = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )
    restore = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
    )

    assert upgrade["operation_authority"] == DATABASE_UPGRADE_AUTHORIZED
    assert upgrade["scopes"][0]["database_relative_path"].endswith("mesh.sqlite")
    assert Path(upgrade["scopes"][0]["database_path"]).resolve() == database.resolve()
    assert restore["operation_authority"] == DATABASE_BACKUP_RESTORE_AUTHORIZED
    assert restore["scope_kind"] == "backup"


def test_worker_rejects_database_authority_tampering_before_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )
    authority["scopes"][0]["database_relative_path"] = "outside/mesh.sqlite"
    called = {"value": False}

    class ForbiddenService:
        def __init__(self, _paths):
            called["value"] = True

        def batch_upgrade(self, *_args, **_kwargs):
            called["value"] = True
            return {"total": 1}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.database_jobs.DatabaseUpgradeManagementService",
        ForbiddenService,
    )
    result = run_job(
        BackgroundJob(
            job_id="database-authority-tamper",
            task_type="database_batch_upgrade",
            params={
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "site_name": "demo",
                "site_id": "demo",
                "profile_ids": [profile.mr_id],
                "database_kind": "mesh_derived",
                "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )

    assert result.ok is False
    assert result.error == "DATABASE_AUTHORITY_INVALID"
    assert called["value"] is False


def test_worker_rejects_target_database_changed_after_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    _database(database, "before-submit")
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )
    _database(database, "after-submit")
    called = {"value": False}

    class ForbiddenService:
        def __init__(self, _paths):
            called["value"] = True

        def repair(self, *_args, **_kwargs):
            called["value"] = True
            return {}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.database_jobs.MeshDerivedDataMaintenanceService",
        ForbiddenService,
    )
    result = run_job(
        BackgroundJob(
            job_id="database-stale-target",
            task_type="database_upgrade",
            params={
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "site_name": "demo",
                "site_id": "demo",
                "profile_id": profile.mr_id,
                "database_kind": "mesh_derived",
                "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )

    assert result.ok is False
    assert result.error == "DATABASE_TARGET_STALE"
    assert called["value"] is False


def test_backup_authority_rejects_cross_site_and_manifest_path_tamper(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    source = tmp_path / "source.sqlite"
    _database(source, "backup")
    profile, database = _mesh_profile(paths)
    _database(database, "target")
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )

    manifest_path = Path(str(backup["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scope_id"] = "other:profile"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="BACKUP_SITE_MISMATCH"):
        build_database_task_authority(
            paths,
            task_type="database_backup_restore",
            site_ref="demo",
            backup_ids=[str(backup["backup_id"])],
            database_kind="mesh_derived",
            authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        )

    manifest["scope_id"] = f"demo:{profile.safe_folder_name}"
    manifest["backup_database_path"] = str(tmp_path / "outside.sqlite")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="BACKUP_PATH_INVALID"):
        build_database_task_authority(
            paths,
            task_type="database_backup_delete",
            site_ref="demo",
            backup_ids=[str(backup["backup_id"])],
            database_kind="mesh_derived",
            authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        )


def test_database_identity_tracks_wal_logical_commit_and_checkpoint_stability(tmp_path: Path) -> None:
    from netconsole.services.database_upgrade.authority import _database_identity

    database = tmp_path / "mesh.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=1000000")
        connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        connection.commit()
        main_before = database.read_bytes()
        identity_before = _database_identity(database)
        assert database.read_bytes() == main_before

        connection.execute("INSERT INTO marker(value) VALUES ('wal-only')")
        connection.commit()
        main_after_commit = database.read_bytes()
        identity_after_commit = _database_identity(database)
        assert main_after_commit == main_before
        assert identity_after_commit != identity_before

        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        identity_after_checkpoint = _database_identity(database)
        assert identity_after_checkpoint == identity_after_commit
    finally:
        connection.close()


def test_worker_rejects_wal_only_target_change_after_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=1000000")
        connection.execute("CREATE TABLE IF NOT EXISTS authority_marker(value TEXT NOT NULL)")
        connection.commit()
        authority = build_database_task_authority(
            paths,
            task_type="database_upgrade",
            site_ref="demo",
            profile_ids=[profile.mr_id],
            database_kind="mesh_derived",
            authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        )
        main_before = database.read_bytes()
        connection.execute("INSERT INTO authority_marker(value) VALUES ('after-submit')")
        connection.commit()
        assert database.read_bytes() == main_before

        called = {"value": False}

        class ForbiddenService:
            def __init__(self, _paths):
                called["value"] = True

            def repair(self, *_args, **_kwargs):
                called["value"] = True
                return {}

        monkeypatch.setattr(
            "netconsole.services.job_center.handlers.database_jobs.MeshDerivedDataMaintenanceService",
            ForbiddenService,
        )
        result = run_job(
            BackgroundJob(
                job_id="database-wal-stale-target",
                task_type="database_upgrade",
                params={
                    "app_root": str(paths.app_root),
                    "data_root": str(paths.data_root),
                    "site_name": "demo",
                    "site_id": "demo",
                    "profile_id": profile.mr_id,
                    "database_kind": "mesh_derived",
                    "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                    "database_authority": authority,
                },
            )
        )
    finally:
        connection.close()

    assert result.ok is False
    assert result.error == "DATABASE_TARGET_STALE"
    assert called["value"] is False


def test_validation_binds_observed_mismatch_and_reports_corrupt_backup(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="validation-seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_database = Path(str(backup["path"])) / "database.sqlite"
    backup_database.write_bytes(backup_database.read_bytes()[:100])

    authority = build_database_task_authority(
        paths,
        task_type="database_backup_validation",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        database_kind="mesh_derived",
    )
    binding = authority["backups"][0]
    assert binding["declared_identity"] != binding["observed_identity"]

    result = DatabaseUpgradeManagementService(paths).validate_backup(
        str(backup["backup_id"]), site_id="demo"
    )
    validation = dict(result["validation"])
    assert result["result_status"] == "INVALID_DATABASE"
    assert validation["valid"] is False
    assert validation["sha256_matches"] is False
    assert validation["restorable"] is False


def test_validation_worker_rejects_second_backup_change_after_submit(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="validation-second-change",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_database = Path(str(backup["path"])) / "database.sqlite"
    backup_database.write_bytes(backup_database.read_bytes()[:100])
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_validation",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        database_kind="mesh_derived",
    )
    backup_database.write_bytes(backup_database.read_bytes() + b"changed-after-submit")

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_BACKUP_STALE"):
        revalidate_database_task_authority(
            paths,
            "database_backup_validation",
            {
                "database_kind": "mesh_derived",
                "backup_id": str(backup["backup_id"]),
                "backup_ids": [str(backup["backup_id"])],
                "site_id": "demo",
                "site_name": "demo",
                "database_authority": authority,
            },
        )


def test_validation_and_delete_ignore_active_target_change_but_restore_does_not(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="target-split",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_id = str(backup["backup_id"])
    validation_authority = build_database_task_authority(
        paths,
        task_type="database_backup_validation",
        site_ref="demo",
        backup_ids=[backup_id],
        database_kind="mesh_derived",
    )
    delete_authority = build_database_task_authority(
        paths,
        task_type="database_backup_delete",
        site_ref="demo",
        backup_ids=[backup_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
    )
    restore_authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[backup_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
    )
    assert "target_identity" not in validation_authority["backups"][0]
    assert "target_identity" not in delete_authority["backups"][0]
    assert "target_identity" in restore_authority["backups"][0]
    _database(database, "active-target-changed")

    common = {
        "database_kind": "mesh_derived",
        "backup_id": backup_id,
        "backup_ids": [backup_id],
        "site_id": "demo",
        "site_name": "demo",
    }
    assert revalidate_database_task_authority(
        paths,
        "database_backup_validation",
        {**common, "database_authority": validation_authority},
    )
    assert revalidate_database_task_authority(
        paths,
        "database_backup_delete",
        {
            **common,
            "authorization_token": DATABASE_BACKUP_DELETE_AUTHORIZED,
            "database_authority": delete_authority,
        },
    )
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_BACKUP_STALE"):
        revalidate_database_task_authority(
            paths,
            "database_backup_restore",
            {
                **common,
                "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
                "database_authority": restore_authority,
            },
        )


def test_old_database_authority_schema_fails_closed(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )
    authority["schema_version"] = 1
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_AUTHORITY_INVALID"):
        revalidate_database_task_authority(
            paths,
            "database_upgrade",
            {
                "database_kind": "mesh_derived",
                "profile_id": profile.mr_id,
                "profile_ids": [profile.mr_id],
                "site_id": "demo",
                "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                "database_authority": authority,
            },
        )


def test_legacy_archive_authority_binds_and_revalidates_candidates(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    archive = paths.site_mesh_root("demo") / profile.safe_folder_name / "mesh.sqlite.rollback_authority"
    _database(archive, "legacy")

    authority = build_database_task_authority(
        paths,
        task_type="legacy_database_archive_migration",
        site_ref="demo",
        database_kind="mesh_derived",
        authorization_token=LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    )

    assert authority["legacy_archives"][0]["source_relative_path"].endswith(
        "mesh.sqlite.rollback_authority"
    )
    _database(archive, "changed-after-submit")

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="LEGACY_ARCHIVE_STALE"):
        revalidate_database_task_authority(
            paths,
            "legacy_database_archive_migration",
            {
                "database_kind": "mesh_derived",
                "site_id": "demo",
                "authorization_token": LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
                "database_authority": authority,
            },
        )


def test_restore_authority_revalidation_allows_its_own_validation_write(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="restore-authority",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_id = str(backup["backup_id"])
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[backup_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
    )
    params = {
        "database_kind": "mesh_derived",
        "backup_id": backup_id,
        "backup_ids": [backup_id],
        "site_id": "demo",
        "site_name": "demo",
        "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
        "database_authority": authority,
    }
    result = DatabaseUpgradeManagementService(paths).restore_backup(
        backup_id,
        confirmed=True,
        site_id="demo",
        before_mutation=lambda: revalidate_database_task_authority(
            paths, "database_backup_restore", params
        ),
    )

    assert result["restored"] is True
    assert result["backup_id"] == backup_id
