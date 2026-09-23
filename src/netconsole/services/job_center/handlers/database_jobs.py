from __future__ import annotations

from collections.abc import Mapping

from netconsole.services.database_upgrade.authority import (
    DatabaseMaintenanceAuthorityError,
    materialize_database_task_authority,
    revalidate_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupDeleteError
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService


DATABASE_UPGRADE_OWNER = "database-upgrade"
DATABASE_UPGRADE_TASK_TYPES = frozenset(
    {
        "database_upgrade",
        "database_batch_upgrade",
        "database_batch_backup",
        "database_backup_validation",
        "legacy_database_archive_migration",
        "database_backup_restore",
        "database_backup_delete",
        "database_backup_batch_delete",
    }
)
DATABASE_UPGRADE_NONCANCELLABLE_TASK_TYPES = frozenset({"database_backup_delete", "database_backup_batch_delete"})

def _authorize(
    context: JobContext,
    *,
    profile_ids=None,
    backup_ids=None,
    validate_profile_targets: bool = True,
) -> None:
    authority = context.params.get("database_authority")
    if isinstance(authority, Mapping) and bool(authority.get("identity_deferred")):
        context.params["database_authority"] = materialize_database_task_authority(
            context.paths,
            authority,
            authorization_token=str(context.params.get("authorization_token") or ""),
        )
    revalidate_database_task_authority(
        context.paths,
        context.task_type,
        context.params,
        profile_ids=profile_ids,
        backup_ids=backup_ids,
        validate_profile_targets=validate_profile_targets,
    )


def _authorize_batch_delete_item(context: JobContext, selected_backup_id: str) -> None:
    try:
        _authorize(context, backup_ids=[selected_backup_id])
    except DatabaseMaintenanceAuthorityError as exc:
        raise DatabaseBackupDeleteError(exc.code, str(exc)) from exc


def database_upgrade(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    database_kind = str(context.params.get("database_kind") or "")
    if database_kind != "mesh_derived":
        raise ValueError("当前阶段仅 MESH 派生数据库已接入统一升级框架")
    site_id = str(context.params.get("site_id") or "")
    profile_id = str(context.params.get("profile_id") or "")
    if not site_id or not profile_id:
        raise ValueError("数据库升级缺少局点或 Profile 标识")
    return MeshDerivedDataMaintenanceService(context.paths).repair(
        site_id,
        profile_ids=[profile_id],
        progress=context.progress,
        should_cancel=context.should_cancel,
        before_mutation=lambda selected_profile_id: _authorize(
            context,
            profile_ids=[selected_profile_id],
        ),
    )


def database_batch_upgrade(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    site_id = str(context.params.get("site_id") or "")
    profile_ids = [str(value) for value in context.params.get("profile_ids") or []]
    if not site_id or not profile_ids:
        raise ValueError("批量数据库升级缺少局点或 Profile 标识")
    result = DatabaseUpgradeManagementService(context.paths).batch_upgrade(
        site_id,
        profile_ids,
        task_id=context.job_id,
        progress=context.progress,
        should_cancel=context.should_cancel,
        before_mutation=lambda selected_profile_id: _authorize(
            context,
            profile_ids=[selected_profile_id],
        ),
    )
    context.progress("database_batch_upgrade", int(result["total"]), int(result["total"]), "批量数据库升级完成")
    return result


def database_batch_backup(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context, validate_profile_targets=False)
    site_id = str(context.params.get("site_id") or "")
    profile_ids = [str(value) for value in context.params.get("profile_ids") or []]
    if not site_id or not profile_ids:
        raise ValueError("批量数据库备份缺少局点或 Profile 标识")
    result = DatabaseUpgradeManagementService(context.paths).batch_backup(
        site_id,
        profile_ids,
        task_id=context.job_id,
        progress=context.progress,
        should_cancel=context.should_cancel,
        before_mutation=lambda selected_profile_id: _authorize(
            context,
            profile_ids=[selected_profile_id],
        ),
    )
    context.progress("database_batch_backup", int(result["total"]), int(result["total"]), "批量数据库备份完成")
    return result


def database_backup_validation(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    result = DatabaseUpgradeManagementService(context.paths).validate_backup(
        str(context.params.get("backup_id") or ""),
        site_id=str(context.params.get("site_name") or ""),
        before_mutation=lambda: _authorize(
            context,
            backup_ids=[str(context.params.get("backup_id") or "")],
        ),
    )
    context.progress("database_backup_validation", 1, 1, "数据库备份验证完成")
    return result


def legacy_database_archive_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    authority = context.params.get("database_authority")
    authorized_archives = (
        authority.get("legacy_archives")
        if isinstance(authority, dict)
        else None
    )
    site_ref = (
        str(authority.get("site_directory_name") or "")
        if isinstance(authority, dict)
        else ""
    ) or str(context.params.get("site_id") or "")
    result = DatabaseUpgradeManagementService(context.paths).organize_legacy(
        site_ref,
        authorized_archives=authorized_archives,
    )
    context.progress("legacy_database_archive_migration", 1, 1, "历史数据库归档整理完成")
    return result


def database_backup_restore(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    result = DatabaseUpgradeManagementService(context.paths).restore_backup(
        str(context.params.get("backup_id") or ""),
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_name") or ""),
        progress=context.progress,
        should_cancel=context.should_cancel,
        before_mutation=lambda: _authorize(context),
    )
    context.progress("database_backup_restore", 1, 1, "数据库备份恢复完成")
    return result


def database_backup_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    result = DatabaseUpgradeManagementService(context.paths).delete_backup(
        str(context.params.get("backup_id") or ""),
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_name") or ""),
        before_mutation=lambda selected_backup_id: _authorize(
            context,
            backup_ids=[selected_backup_id],
        ),
    )
    context.progress("database_backup_delete", 1, 1, "数据库备份已删除")
    return result


def database_backup_batch_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    backup_ids = [str(value) for value in context.params.get("backup_ids") or []]
    if not backup_ids:
        _authorize(context)
    result = DatabaseUpgradeManagementService(context.paths).delete_backups(
        backup_ids,
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_id") or context.params.get("site_name") or ""),
        task_id=context.job_id,
        progress=context.progress,
        before_mutation=lambda selected_backup_id: _authorize_batch_delete_item(context, selected_backup_id),
    )
    context.structured_progress(
        "database_backup_batch_delete",
        int(result.get("deleted") or 0),
        int(result.get("requested") or 0),
        "批量删除数据库备份完成",
        requested=int(result.get("requested") or 0),
        deleted=int(result.get("deleted") or 0),
        failed=int(result.get("failed") or 0),
        skipped=int(result.get("skipped") or 0),
        released_bytes=int(result.get("released_bytes") or 0),
        partial_success=bool(result.get("partial_success")),
    )
    return result


HANDLERS = {
    "database_upgrade": database_upgrade,
    "database_batch_upgrade": database_batch_upgrade,
    "database_batch_backup": database_batch_backup,
    "database_backup_validation": database_backup_validation,
    "legacy_database_archive_migration": legacy_database_archive_migration,
    "database_backup_restore": database_backup_restore,
    "database_backup_delete": database_backup_delete,
    "database_backup_batch_delete": database_backup_batch_delete,
}

__all__ = [
    "DATABASE_UPGRADE_NONCANCELLABLE_TASK_TYPES",
    "DATABASE_UPGRADE_OWNER",
    "DATABASE_UPGRADE_TASK_TYPES",
    "HANDLERS",
]
