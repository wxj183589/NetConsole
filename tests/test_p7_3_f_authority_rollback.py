from __future__ import annotations

import json
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.authority import (
    DATABASE_BACKUP_DELETE_AUTHORIZED,
    DATABASE_BACKUP_RESTORE_AUTHORIZED,
    DATABASE_UPGRADE_AUTHORIZED,
    DatabaseMaintenanceAuthorityError,
    LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    build_database_task_authority,
    materialize_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.job_center.handlers import database_jobs
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.repositories.mesh_mr_repository import MeshMrRepository


def _profile(paths: PathResolver, name: str = "列车07-MR-CT") -> tuple[MeshMrProfile, Path]:
    profile = MeshStorageService("demo", paths).create_mr_profile(name)
    database = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    MeshMrRepository(database)
    return profile, database


def _backup(paths: PathResolver, profile: MeshMrProfile, database: Path, task_id: str) -> dict[str, object]:
    return DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id=f"demo:{profile.safe_folder_name}",
        task_id=task_id,
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )


def _job_params(paths: PathResolver, *, site: str = "demo") -> dict[str, object]:
    return {
        "app_root": str(paths.app_root),
        "data_root": str(paths.data_root),
        "site_id": site,
        "site_name": site,
        "database_kind": "mesh_derived",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_restore_worker_uses_actual_backup_and_site_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    backup = _backup(paths, profile, database, "restore-target-binding")
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        defer_identity=True,
    )
    database_before = _sha256(database)
    backup_file = Path(str(backup["path"])) / "database.sqlite"
    backup_before = _sha256(backup_file)
    called = False

    def forbidden_restore(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"restored": True}

    monkeypatch.setattr(database_jobs.DatabaseUpgradeManagementService, "restore_backup", forbidden_restore)
    params = {
        **_job_params(paths),
        "backup_id": "not-the-authorized-backup",
        "confirmed": True,
        "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
        "database_authority": authority,
    }
    result = run_job(
        BackgroundJob(
            job_id="restore-backup-id-tamper",
            task_type="database_backup_restore",
            params=params,
        )
    )
    assert result.ok is False
    assert "DATABASE_BACKUP_TARGET_STALE" in result.error
    assert called is False
    assert _sha256(database) == database_before
    assert _sha256(backup_file) == backup_before

    params["backup_id"] = str(backup["backup_id"])
    params["site_id"] = "other-site"
    params["site_name"] = "other-site"
    result = run_job(
        BackgroundJob(
            job_id="restore-site-tamper",
            task_type="database_backup_restore",
            params=params,
        )
    )
    assert result.ok is False
    assert any(
        code in result.error
        for code in ("DATABASE_SITE_SCOPE_STALE", "DATABASE_SITE_NOT_CANONICAL", "BACKUP_SITE_MISMATCH")
    )
    assert called is False
    assert _sha256(database) == database_before
    assert _sha256(backup_file) == backup_before


def test_restore_worker_allows_authorized_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    backup = _backup(paths, profile, database, "restore-authorized")
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        defer_identity=True,
    )
    calls: list[str] = []

    def allowed_restore(_self, backup_id: str, **kwargs):
        calls.append(str(backup_id))
        kwargs["before_mutation"]()
        return {"restored": True}

    monkeypatch.setattr(database_jobs.DatabaseUpgradeManagementService, "restore_backup", allowed_restore)
    result = run_job(
        BackgroundJob(
            job_id="restore-authorized-target",
            task_type="database_backup_restore",
            params={
                **_job_params(paths),
                "backup_id": str(backup["backup_id"]),
                "confirmed": True,
                "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is True
    assert result.result == {"restored": True}
    assert calls == [str(backup["backup_id"])]


def test_restore_worker_rejects_manifest_replacement_before_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    backup = _backup(paths, profile, database, "restore-manifest-binding")
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        defer_identity=True,
    )
    manifest_path = Path(str(backup["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database_sha256"] = "manifest-replaced"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = manifest_path.read_bytes()
    called = False

    def forbidden_restore(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"restored": True}

    monkeypatch.setattr(database_jobs.DatabaseUpgradeManagementService, "restore_backup", forbidden_restore)
    result = run_job(
        BackgroundJob(
            job_id="restore-manifest-tamper",
            task_type="database_backup_restore",
            params={
                **_job_params(paths),
                "backup_id": str(backup["backup_id"]),
                "confirmed": True,
                "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is False
    assert "DATABASE_BACKUP_STALE" in result.error
    assert called is False
    assert manifest_path.read_bytes() == before


def test_restore_worker_revalidates_target_before_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    backup = _backup(paths, profile, database, "restore-pre-mutation")
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_restore",
        site_ref="demo",
        backup_ids=[str(backup["backup_id"])],
        authorization_token=DATABASE_BACKUP_RESTORE_AUTHORIZED,
        defer_identity=True,
    )
    params = {
        **_job_params(paths),
        "backup_id": str(backup["backup_id"]),
        "confirmed": True,
        "authorization_token": DATABASE_BACKUP_RESTORE_AUTHORIZED,
        "database_authority": authority,
    }
    called = False

    context = JobContext(
        job_id="restore-pre-mutation-target-race",
        task_type="database_backup_restore",
        params=params,
        progress_callback=None,
        should_cancel=None,
        paths=paths,
    )

    def mutate_then_revalidate(_self, _backup_id, **kwargs):
        nonlocal called
        context.params["backup_id"] = "changed-after-submit"
        kwargs["before_mutation"]()
        called = True
        return {"restored": True}

    monkeypatch.setattr(database_jobs.DatabaseUpgradeManagementService, "restore_backup", mutate_then_revalidate)
    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_BACKUP_TARGET_STALE"):
        database_jobs.database_backup_restore(context)
    assert called is False


def test_batch_delete_rejects_unrequested_existing_backup_without_side_effects(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    first, first_db = _profile(paths)
    second, second_db = _profile(paths, "列车08-MR-CT")
    first_backup = _backup(paths, first, first_db, "batch-delete-authorized")
    second_backup = _backup(paths, second, second_db, "batch-delete-unrequested")
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_batch_delete",
        site_ref="demo",
        backup_ids=[str(first_backup["backup_id"])],
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        defer_identity=True,
    )
    first_path = Path(str(first_backup["path"]))
    second_path = Path(str(second_backup["path"]))
    before = (_sha256(first_path / "database.sqlite"), _sha256(second_path / "database.sqlite"))
    result = run_job(
        BackgroundJob(
            job_id="batch-delete-unrequested-existing",
            task_type="database_backup_batch_delete",
            params={
                **_job_params(paths),
                "backup_ids": [str(first_backup["backup_id"]), str(second_backup["backup_id"])],
                "confirmed": True,
                "authorization_token": DATABASE_BACKUP_DELETE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is False
    assert "DATABASE_BACKUP_TARGET_STALE" in result.error
    assert first_path.is_dir() and second_path.is_dir()
    assert (_sha256(first_path / "database.sqlite"), _sha256(second_path / "database.sqlite")) == before


def test_batch_delete_authorized_items_and_missing_retry_keep_partial_contract(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    first, first_db = _profile(paths)
    second, second_db = _profile(paths, "列车08-MR-CT")
    first_backup = _backup(paths, first, first_db, "batch-delete-first")
    second_backup = _backup(paths, second, second_db, "batch-delete-second")
    backup_ids = [str(first_backup["backup_id"]), str(second_backup["backup_id"])]
    authority = build_database_task_authority(
        paths,
        task_type="database_backup_batch_delete",
        site_ref="demo",
        backup_ids=backup_ids,
        authorization_token=DATABASE_BACKUP_DELETE_AUTHORIZED,
        defer_identity=True,
    )
    first_path = Path(str(first_backup["path"]))
    second_path = Path(str(second_backup["path"]))
    result = run_job(
        BackgroundJob(
            job_id="batch-delete-authorized",
            task_type="database_backup_batch_delete",
            params={
                **_job_params(paths),
                "backup_ids": backup_ids,
                "confirmed": True,
                "authorization_token": DATABASE_BACKUP_DELETE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is True
    assert result.result["deleted"] == 2
    assert not first_path.exists() and not second_path.exists()

    retry = run_job(
        BackgroundJob(
            job_id="batch-delete-authorized-retry",
            task_type="database_backup_batch_delete",
            params={
                **_job_params(paths),
                "backup_ids": backup_ids,
                "confirmed": True,
                "authorization_token": DATABASE_BACKUP_DELETE_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert retry.ok is True
    assert retry.result["deleted"] == 0
    assert retry.result["failed"] == 2


def test_legacy_archive_uses_authority_site_and_rejects_cross_site_job(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    source = database.parent / "mesh.sqlite.legacy_cross_site"
    shutil.copy2(database, source)
    before = _sha256(source)
    authority = build_database_task_authority(
        paths,
        task_type="legacy_database_archive_migration",
        site_ref="demo",
        authorization_token=LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
        defer_identity=True,
    )
    result = run_job(
        BackgroundJob(
            job_id="legacy-archive-cross-site",
            task_type="legacy_database_archive_migration",
            params={
                **_job_params(paths, site="other-site"),
                "authorization_token": LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
                "database_authority": authority,
            },
        )
    )
    assert result.ok is False
    assert "DATABASE_SITE_" in result.error
    assert source.is_file()
    assert _sha256(source) == before


def test_legacy_archive_callback_runs_before_file_mutation(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    profile, database = _profile(paths)
    source = database.parent / "mesh.sqlite.legacy_pre_mutation"
    shutil.copy2(database, source)
    before = _sha256(source)
    service = database_jobs.DatabaseUpgradeManagementService(paths)

    def reject() -> None:
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")

    with pytest.raises(DatabaseMaintenanceAuthorityError, match="DATABASE_SITE_SCOPE_STALE"):
        service.organize_legacy("demo", before_mutation=reject)
    assert source.is_file()
    assert _sha256(source) == before


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
