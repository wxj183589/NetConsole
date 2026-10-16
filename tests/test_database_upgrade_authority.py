from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.authority import (
    DATABASE_BACKUP_CREATE_AUTHORIZED,
    DATABASE_BACKUP_DELETE_AUTHORIZED,
    DATABASE_BACKUP_RESTORE_AUTHORIZED,
    DATABASE_UPGRADE_AUTHORIZED,
    LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    DatabaseMaintenanceAuthorityError,
    build_database_task_authority,
    materialize_database_task_authority,
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


def test_authority_ignores_unrelated_site_registry_changes(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database = _mesh_profile(paths)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    registry_path = paths.config_dir / "site_registry.json"
    registry = {
        "schema_version": 2,
        "updated_at": "initial",
        "sites": [
            {
                "site_id": "demo",
                "display_name": "Demo",
                "relative_path": "sites/demo",
            },
            {
                "site_id": "other",
                "display_name": "Other",
                "relative_path": "sites/other",
            },
        ],
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )

    registry["updated_at"] = "changed"
    registry["sites"][1]["display_name"] = "Other renamed"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    revalidate_database_task_authority(
        paths,
        "database_upgrade",
        {
            "database_kind": "mesh_derived",
            "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
            "profile_ids": [profile.mr_id],
            "database_authority": authority,
        },
    )


def test_backup_validation_uses_production_write_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver
    from netconsole.core.runtime_environment import (
        DataEnvironmentInfo,
        DataEnvironmentMode,
        ProductionWriteBlockedError,
    )
    import netconsole.services.database_upgrade.authority as authority_module

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="production-validation-guard",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    monkeypatch.setattr(
        authority_module,
        "data_environment",
        lambda _root: DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )

    def blocked(*_args, **_kwargs):
        raise ProductionWriteBlockedError("blocked")

    monkeypatch.setattr(authority_module, "require_data_root_write_allowed", blocked)
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_PRODUCTION_WRITE_NOT_ALLOWED"):
        build_database_task_authority(
            paths,
            task_type="database_backup_validation",
            site_ref="demo",
            backup_ids=[str(backup["backup_id"])],
            database_kind="mesh_derived",
        )


def test_restore_rejects_path_separator_in_backup_scope_id(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="restore-scope-guard",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    manifest_path = Path(str(backup["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scope_id"] = f"demo:{profile.safe_folder_name}/../other"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="BACKUP_SCOPE_INVALID"):
        build_database_task_authority(
            paths,
            task_type="database_backup_restore",
            site_ref="demo",
            backup_ids=[str(backup["backup_id"])],
            database_kind="mesh_derived",
            authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        )


def test_deferred_authority_materializes_database_identity_inside_worker_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver
    from netconsole.services.mesh_derived_data_maintenance_service import (
        MeshDerivedDataMaintenanceService,
    )

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    original_inspect = MeshDerivedDataMaintenanceService.inspect
    inspect_calls = {"value": 0}

    def counted_inspect(self, *args, **kwargs):
        inspect_calls["value"] += 1
        return original_inspect(self, *args, **kwargs)

    monkeypatch.setattr(MeshDerivedDataMaintenanceService, "inspect", counted_inspect)
    deferred = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        defer_identity=True,
    )

    assert deferred["identity_deferred"] is True
    assert deferred["scopes"][0]["database_identity"] == {"deferred": True}
    assert deferred["scopes"][0]["database_observation"]["identity_format"] == "sqlite-observation-v1"
    assert inspect_calls["value"] == 0

    materialized = materialize_database_task_authority(
        paths,
        deferred,
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )

    assert materialized["identity_deferred"] is False
    assert materialized["scopes"][0]["database_identity"]["identity_format"] == "sqlite-logical-v1"
    assert inspect_calls["value"] == 1

    _database(_database_path, "changed-after-submit")
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_TARGET_STALE"):
        materialize_database_task_authority(
            paths,
            deferred,
            authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        )


def test_deferred_authority_materialization_honors_worker_cancellation(tmp_path: Path) -> None:
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
        defer_identity=True,
    )
    calls = {"value": 0}

    def should_cancel() -> bool:
        calls["value"] += 1
        return calls["value"] >= 2

    result = run_job(
        BackgroundJob(
            job_id="database-authority-cancelled",
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
        ),
        should_cancel=should_cancel,
    )

    assert result.ok is False
    assert result.cancelled is True
    assert result.error == "后台任务已取消"


def test_authority_revalidation_honors_worker_cancellation(tmp_path: Path) -> None:
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
    calls = {"value": 0}

    def should_cancel() -> bool:
        calls["value"] += 1
        return calls["value"] >= 2

    result = run_job(
        BackgroundJob(
            job_id="database-authority-revalidation-cancelled",
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
        ),
        should_cancel=should_cancel,
    )

    assert result.ok is False
    assert result.cancelled is True
    assert result.error == "后台任务已取消"


def test_batch_upgrade_revalidation_ignores_its_own_catalog_pending_marker(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver
    from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    first, _first_database = _mesh_profile(paths, "列车07-MR-CT")
    second, _second_database = _mesh_profile(paths, "列车08-MR-CT")
    authority = build_database_task_authority(
        paths,
        task_type="database_batch_upgrade",
        site_ref="demo",
        profile_ids=[first.mr_id, second.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
    )
    MeshCatalogRepository(paths.mesh_catalog_path("demo")).mark_index_pending()

    assert revalidate_database_task_authority(
        paths,
        "database_batch_upgrade",
        {
            "database_kind": "mesh_derived",
            "site_id": "demo",
            "site_name": "demo",
            "profile_ids": [first.mr_id, second.mr_id],
            "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
            "database_authority": authority,
        },
        profile_ids=[second.mr_id],
    )


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


def test_batch_backup_keeps_processing_profiles_when_one_target_is_stale(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    first, first_database = _mesh_profile(paths, "列车07-MR-CT")
    second, _second_database = _mesh_profile(paths, "列车08-MR-CT")
    authority = build_database_task_authority(
        paths,
        task_type="database_batch_backup",
        site_ref="demo",
        profile_ids=[first.mr_id, second.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_CREATE_AUTHORIZED,
    )
    _database(first_database, "changed-after-submit")

    result = run_job(
        BackgroundJob(
            job_id="database-batch-backup-stale-item",
            task_type="database_batch_backup",
            params={
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "site_name": "demo",
                "site_id": "demo",
                "profile_ids": [first.mr_id, second.mr_id],
                "database_kind": "mesh_derived",
                "authorization_token": DATABASE_BACKUP_CREATE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )

    assert result.ok is True
    assert result.result["failed"] == 1
    assert result.result["success"] == 1
    statuses = {item["profile_id"]: item["status"] for item in result.result["results"]}
    assert statuses == {first.mr_id: "failed", second.mr_id: "success"}
    assert "DATABASE_TARGET_STALE" in next(
        item["message"] for item in result.result["results"] if item["profile_id"] == first.mr_id
    )


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


def test_restore_authority_rejects_mesh_target_mismatch_outside_production(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    wrong_target = paths.data_root / "sites" / "demo" / "files" / "wrong.sqlite"
    _database(wrong_target, "wrong-target")
    backup = DatabaseBackupStore(paths).create(
        source_path=wrong_target,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="wrong-target-restore",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="BACKUP_TARGET_MISMATCH"):
        build_database_task_authority(
            paths,
            task_type="database_backup_restore",
            site_ref="demo",
            backup_ids=[str(backup["backup_id"])],
            database_kind="mesh_derived",
            authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        )


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
        identity_before = _database_identity(database, temp_dir=tmp_path / "runtime" / "temp")
        assert database.read_bytes() == main_before

        connection.execute("INSERT INTO marker(value) VALUES ('wal-only')")
        connection.commit()
        main_after_commit = database.read_bytes()
        identity_after_commit = _database_identity(database, temp_dir=tmp_path / "runtime" / "temp")
        assert main_after_commit == main_before
        assert identity_after_commit != identity_before

        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        identity_after_checkpoint = _database_identity(database, temp_dir=tmp_path / "runtime" / "temp")
        assert identity_after_checkpoint == identity_after_commit
    finally:
        connection.close()


def test_database_identity_cleans_managed_snapshot_root(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver
    from netconsole.services.database_upgrade.authority import _database_identity

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    _profile, database = _mesh_profile(paths)

    identity = _database_identity(database, temp_dir=paths.temp_dir)

    assert identity["identity_format"] == "sqlite-logical-v1"
    assert paths.temp_dir.is_dir()
    assert list(paths.temp_dir.glob("netconsole-sqlite-identity-*")) == []


def test_database_identity_rejects_reparse_temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from netconsole.core.paths import PathResolver
    from netconsole.services.database_upgrade import sqlite_consistency

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    _profile, database = _mesh_profile(paths)
    monkeypatch.setattr(
        sqlite_consistency,
        "_is_reparse_point",
        lambda path: Path(path) == paths.temp_dir,
    )

    with pytest.raises(ValueError, match="reparse point"):
        sqlite_consistency.sqlite_logical_identity(database, temp_dir=paths.temp_dir)


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


def test_invalid_backup_can_be_authorized_for_explicit_delete(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="delete-invalid-backup",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_database = Path(str(backup["path"])) / "database.sqlite"
    backup_database.write_bytes(backup_database.read_bytes()[:100])
    validated = DatabaseUpgradeManagementService(paths).validate_backup(
        str(backup["backup_id"]), site_id="demo"
    )
    assert validated["result_status"] == "INVALID_DATABASE"

    authority = build_database_task_authority(
        paths,
        task_type="database_backup_delete",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        defer_identity=True,
    )
    materialized = materialize_database_task_authority(
        paths,
        authority,
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
    )

    assert materialized["backups"][0]["observed_identity"]["sha256"] != materialized["backups"][0]["declared_identity"]["sha256"]
    assert revalidate_database_task_authority(
        paths,
        "database_backup_delete",
        {
            "database_kind": "mesh_derived",
            "backup_id": str(backup["backup_id"]),
            "backup_ids": [str(backup["backup_id"])],
            "site_id": "demo",
            "site_name": "demo",
            "authorization_token": DATABASE_BACKUP_DELETE_AUTHORIZED,
            "database_authority": materialized,
        },
    )


def test_deferred_backup_authority_rejects_changed_submit_declaration(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="deferred-declaration",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_id = str(backup["backup_id"])
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_delete",
        site_ref="demo",
        backup_ids=[backup_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        defer_identity=True,
    )
    manifest_path = Path(str(backup["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database_size"] = int(manifest["database_size"]) + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_BACKUP_STALE"):
        materialize_database_task_authority(
            paths,
            authority,
            authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        )


def test_batch_delete_builds_one_backup_index_for_selected_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _mesh_profile(paths)
    store = DatabaseBackupStore(paths)
    backups = [
        store.create(
            source_path=database,
            database_kind="mesh_derived",
            scope_type="site_profile",
            scope_id=f"demo:{profile.safe_folder_name}",
            task_id=f"batch-index-{index}",
            old_version="old",
            target_version="new",
            strategy="SCHEMA_MIGRATION",
        )
        for index in range(2)
    ]
    original_list = DatabaseBackupStore.list
    calls = {"value": 0}

    def counted_list(self, *args, **kwargs):
        calls["value"] += 1
        return original_list(self, *args, **kwargs)

    monkeypatch.setattr(DatabaseBackupStore, "list", counted_list)
    build_database_task_authority(
        paths,
        task_type="database_backup_batch_delete",
        site_ref="demo",
        backup_ids=[str(item["backup_id"]) for item in backups],
        database_kind="mesh_derived",
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        defer_identity=True,
    )

    assert calls["value"] == 1


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


def test_deferred_legacy_archive_authority_hashes_only_in_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, _database_path = _mesh_profile(paths)
    archive = paths.site_mesh_root("demo") / profile.safe_folder_name / "mesh.sqlite.rollback_deferred"
    _database(archive, "legacy")

    calls: list[Path] = []

    def tracked_sha256(path: Path) -> str:
        calls.append(path)
        from netconsole.services.database_upgrade.sqlite_consistency import sha256_file

        return sha256_file(path)

    monkeypatch.setattr(
        "netconsole.services.database_upgrade.history.sha256_file",
        tracked_sha256,
    )
    authority = build_database_task_authority(
        paths,
        task_type="legacy_database_archive_migration",
        site_ref="demo",
        database_kind="mesh_derived",
        authorization_token=LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
        defer_identity=True,
    )

    assert calls == []
    assert authority["identity_deferred"] is True
    assert authority["legacy_archives"] == []
    assert authority["legacy_archive_discovery_deferred"] is True

    materialized = materialize_database_task_authority(
        paths,
        authority,
        authorization_token=LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    )
    assert len(calls) == 1
    assert materialized["identity_deferred"] is False
    assert materialized["legacy_archive_discovery_deferred"] is False
    assert len(materialized["legacy_archives"][0]["sha256"]) == 64

    _database(archive, "changed-after-worker-discovery")
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="LEGACY_ARCHIVE_STALE"):
        revalidate_database_task_authority(
            paths,
            "legacy_database_archive_migration",
            {
                "database_kind": "mesh_derived",
                "site_id": "demo",
                "authorization_token": LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
                "database_authority": materialized,
            },
        )


def test_batch_upgrade_initial_authority_leaves_stale_profiles_to_item_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    first, first_database = _mesh_profile(paths, "列车07-MR-CT")
    second, _second_database = _mesh_profile(paths, "列车08-MR-CT")
    authority = build_database_task_authority(
        paths,
        task_type="database_batch_upgrade",
        site_ref="demo",
        profile_ids=[first.mr_id, second.mr_id],
        database_kind="mesh_derived",
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        defer_identity=True,
    )
    _database(first_database, "changed-after-submit")
    called = {"value": False}
    callback_failures: list[tuple[str, str]] = []

    class RecordingService:
        def __init__(self, _paths):
            pass

        def batch_upgrade(self, _site_id, selected_profile_ids, **kwargs):
            called["value"] = True
            before_mutation = kwargs["before_mutation"]
            for selected_profile_id in selected_profile_ids:
                try:
                    before_mutation(selected_profile_id)
                except Exception as exc:
                    callback_failures.append((selected_profile_id, str(exc)))
            return {"total": len(selected_profile_ids), "failed": len(callback_failures)}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.database_jobs.DatabaseUpgradeManagementService",
        RecordingService,
    )
    result = run_job(
        BackgroundJob(
            job_id="database-batch-upgrade-stale-item",
            task_type="database_batch_upgrade",
            params={
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "site_name": "demo",
                "site_id": "demo",
                "profile_ids": [first.mr_id, second.mr_id],
                "database_kind": "mesh_derived",
                "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )

    assert result.ok is True
    assert called["value"] is True
    assert callback_failures == [(first.mr_id, "DATABASE_TARGET_STALE")]
    assert result.result["failed"] == 1


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
