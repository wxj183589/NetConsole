from __future__ import annotations

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


def database_upgrade(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
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
    )


def database_batch_upgrade(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
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
    )
    context.progress("database_batch_upgrade", int(result["total"]), int(result["total"]), "批量数据库升级完成")
    return result


def database_batch_backup(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
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
    )
    context.progress("database_batch_backup", int(result["total"]), int(result["total"]), "批量数据库备份完成")
    return result


def database_backup_validation(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DatabaseUpgradeManagementService(context.paths).validate_backup(
        str(context.params.get("backup_id") or ""),
        site_id=str(context.params.get("site_name") or ""),
    )
    context.progress("database_backup_validation", 1, 1, "数据库备份验证完成")
    return result


def legacy_database_archive_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DatabaseUpgradeManagementService(context.paths).organize_legacy(str(context.params.get("site_id") or ""))
    context.progress("legacy_database_archive_migration", 1, 1, "历史数据库归档整理完成")
    return result


def database_backup_restore(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DatabaseUpgradeManagementService(context.paths).restore_backup(
        str(context.params.get("backup_id") or ""),
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_name") or ""),
        progress=context.progress,
        should_cancel=context.should_cancel,
    )
    context.progress("database_backup_restore", 1, 1, "数据库备份恢复完成")
    return result


def database_backup_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DatabaseUpgradeManagementService(context.paths).delete_backup(
        str(context.params.get("backup_id") or ""),
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_name") or ""),
    )
    context.progress("database_backup_delete", 1, 1, "数据库备份已删除")
    return result


def database_backup_batch_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DatabaseUpgradeManagementService(context.paths).delete_backups(
        [str(value) for value in context.params.get("backup_ids") or []],
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_id") or context.params.get("site_name") or ""),
        task_id=context.job_id,
        progress=context.progress,
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
