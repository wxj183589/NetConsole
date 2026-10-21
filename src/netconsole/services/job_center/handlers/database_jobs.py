from __future__ import annotations

from collections.abc import Mapping

from netconsole.services.database_upgrade.authority import (
    DatabaseMaintenanceAuthorityCancelled,
    DatabaseMaintenanceAuthorityError,
    build_database_task_authority,
    materialize_database_task_authority,
    revalidate_database_task_authority,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupDeleteError
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
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
    profile_ids: list[str] | None = None,
    backup_ids: list[str] | None = None,
    validate_profile_targets: bool = True,
    validate_requested_profile_list: bool = True,
    validate_requested_backup_list: bool = True,
 ) -> Mapping[str, object] | None:
    authority = context.params.get("database_authority")
    if not isinstance(authority, Mapping):
        # Direct service-level callers historically constructed JobContext
        # without the HTTP submission envelope.  Keep that narrow test/tool
        # compatibility while every real queued job (which carries site_name)
        # still fails closed when its immutable authority is absent.
        if context.params.get("site_name"):
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_REQUIRED")
        authority = build_database_task_authority(
            context.paths,
            task_type=context.task_type,
            site_ref=str(context.params.get("site_id") or ""),
            profile_ids=[str(value) for value in context.params.get("profile_ids") or ()]
            or ([str(context.params.get("profile_id") or "")] if context.params.get("profile_id") else []),
            backup_ids=[str(value) for value in context.params.get("backup_ids") or ()]
            or ([str(context.params.get("backup_id") or "")] if context.params.get("backup_id") else []),
            database_kind=str(context.params.get("database_kind") or "mesh_derived"),
            authorization_token=str(context.params.get("authorization_token") or ""),
            defer_identity=False,
        )
        context.params["database_authority"] = authority

    def cancel_check() -> None:
        if context.should_cancel is not None and context.should_cancel():
            raise DatabaseMaintenanceAuthorityCancelled("后台任务已取消")

    try:
        if bool(authority.get("identity_deferred")):
            if context.task_type == "database_backup_batch_delete" and not authority.get("backups"):
                return
            authority = materialize_database_task_authority(
                context.paths,
                authority,
                authorization_token=str(context.params.get("authorization_token") or ""),
                cancel_check=cancel_check,
            )
            context.params["database_authority"] = authority
        actual_profile_ids = profile_ids
        if actual_profile_ids is None:
            if "profile_ids" in context.params:
                actual_profile_ids = [str(value) for value in context.params.get("profile_ids") or ()]
            elif context.params.get("profile_id"):
                actual_profile_ids = [str(context.params.get("profile_id"))]
        actual_backup_ids = backup_ids
        if actual_backup_ids is None:
            if "backup_ids" in context.params:
                actual_backup_ids = [str(value) for value in context.params.get("backup_ids") or ()]
            elif context.params.get("backup_id"):
                actual_backup_ids = [str(context.params.get("backup_id"))]
        current = revalidate_database_task_authority(
            context.paths,
            context.task_type,
            context.params,
            profile_ids=actual_profile_ids,
            backup_ids=actual_backup_ids,
            validate_profile_targets=validate_profile_targets,
            validate_requested_profile_list=validate_requested_profile_list,
            validate_requested_backup_list=validate_requested_backup_list,
            cancel_check=cancel_check,
        )
        return current
    except DatabaseMaintenanceAuthorityCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc


def _authorize_batch_delete_item(context: JobContext, backup_id: str) -> None:
    try:
        _authorize(
            context,
            backup_ids=[backup_id],
            validate_requested_backup_list=False,
        )
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
        before_mutation=lambda selected: _authorize(context, profile_ids=[selected]),
    )


def database_batch_upgrade(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context, validate_profile_targets=False)
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
        before_mutation=lambda selected: _authorize(
            context,
            profile_ids=[selected],
            validate_requested_profile_list=False,
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
        before_mutation=lambda selected: _authorize(
            context,
            profile_ids=[selected],
            validate_requested_profile_list=False,
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
        before_mutation=lambda: _authorize(context, backup_ids=[str(context.params.get("backup_id") or "")]),
    )
    context.progress("database_backup_validation", 1, 1, "数据库备份验证完成")
    return result


def legacy_database_archive_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    authority = _authorize(context)
    site_id = str(authority.get("site_directory_name") or "")
    result = DatabaseUpgradeManagementService(context.paths).organize_legacy(
        site_id,
        before_mutation=lambda: _authorize(context),
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
        before_mutation=lambda selected: _authorize(context, backup_ids=[selected]),
    )
    context.progress("database_backup_delete", 1, 1, "数据库备份已删除")
    return result


def database_backup_batch_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    _authorize(context)
    result = DatabaseUpgradeManagementService(context.paths).delete_backups(
        [str(value) for value in context.params.get("backup_ids") or []],
        confirmed=bool(context.params.get("confirmed")),
        site_id=str(context.params.get("site_id") or context.params.get("site_name") or ""),
        task_id=context.job_id,
        progress=context.progress,
        before_mutation=lambda selected: _authorize_batch_delete_item(context, selected),
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
