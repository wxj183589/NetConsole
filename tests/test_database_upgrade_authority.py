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
    DATABASE_UPGRADE_AUTHORIZED,
    DatabaseMaintenanceAuthorityError,
    build_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
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
