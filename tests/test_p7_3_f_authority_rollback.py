from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.authority import (
    DATABASE_UPGRADE_AUTHORIZED,
    DatabaseMaintenanceAuthorityError,
    build_database_task_authority,
    materialize_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.repositories.mesh_mr_repository import MeshMrRepository


def _profile(paths: PathResolver) -> tuple[MeshMrProfile, Path]:
    profile = MeshStorageService("demo", paths).create_mr_profile("列车07-MR-CT")
    database = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    MeshMrRepository(database)
    return profile, database


def test_database_authority_rejects_target_change_between_submit_and_worker(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        defer_identity=True,
    )
    assert authority["identity_deferred"] is True
    assert authority["scopes"][0]["database_observation"]["identity_format"] == "sqlite-observation-v1"

    info = database.stat()
    os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_TARGET_STALE"):
        materialize_database_task_authority(
            paths,
            authority,
            authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        )


def test_database_worker_rejects_tampered_target_before_service(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    authority = build_database_task_authority(
        paths,
        task_type="database_upgrade",
        site_ref="demo",
        profile_ids=[profile.mr_id],
        authorization_token=DATABASE_UPGRADE_AUTHORIZED,
        defer_identity=True,
    )
    info = database.stat()
    os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    result = run_job(
        BackgroundJob(
            job_id="p7-3-f-target-race",
            task_type="database_upgrade",
            params={
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "site_id": "demo",
                "site_name": "demo",
                "profile_id": profile.mr_id,
                "database_kind": "mesh_derived",
                "authorization_token": DATABASE_UPGRADE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is False
    assert "DATABASE_TARGET_STALE" in result.error


def test_database_restore_authority_rejects_path_separator_scope_tamper(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id="p7-3-f",
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
            authorization_token="DATABASE_BACKUP_RESTORE_AUTHORIZED",
            defer_identity=True,
        )


def test_rollback_authority_requires_operation_specific_production_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from netconsole.core.runtime_environment import DataEnvironmentInfo, DataEnvironmentMode
    import netconsole.services.production_rollback_authority as authority

    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    paths.site_dir("demo").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        authority,
        "data_environment",
        lambda _root: DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    monkeypatch.setattr(authority, "production_write_allowed", lambda: True)
    monkeypatch.setattr(authority, "require_data_root_write_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        authority,
        "resolve_production_site_scope",
        lambda _paths, _site: ("canonical-demo", paths.site_dir("demo")),
    )

    with pytest.raises(authority.ProductionRollbackAuthorityError, match="ROLLBACK_OPERATION_AUTHORIZATION_REQUIRED"):
        authority.require_rollback_authority(
            paths,
            site_ref="demo",
            operation="AC_EXTENSION_ROLLBACK",
            authorization_token="BASE_DATA_ROLLBACK_AUTHORIZED",
        )
    scope = authority.require_rollback_authority(
        paths,
        site_ref="demo",
        operation="AC_EXTENSION_ROLLBACK",
        authorization_token="AC_EXTENSION_ROLLBACK_AUTHORIZED",
    )
    assert scope.canonical_site_id == "canonical-demo"
