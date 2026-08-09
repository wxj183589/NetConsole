from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.database_upgrade import (
    DatabaseBackupActionRequest,
    DatabaseTaskReferenceDTO,
    DatabaseUpgradeRequest,
)
from netconsole.models.api.system_maintenance import DesktopActionDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.job_center.handlers.database_jobs import DATABASE_UPGRADE_OWNER


router = APIRouter(prefix="/database-upgrades", tags=["database-upgrades"])


def _service(request: Request) -> DatabaseUpgradeManagementService:
    return request.app.state.database_upgrade_management_service


def _site_id(request: Request) -> str:
    return str(request.app.state.site_application_service.active_site_directory_name())


@router.get("")
def list_database_upgrades(request: Request) -> dict[str, object]:
    return _run(lambda: _service(request).list_status(_site_id(request)))


@router.post(
    "/upgrade",
    response_model=DatabaseTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.database_upgrade_start"))],
)
def start_database_upgrade(request: Request, payload: DatabaseUpgradeRequest) -> DatabaseTaskReferenceDTO:
    site_id = _site_id(request)
    snapshot = _run(lambda: _service(request).list_status(site_id))
    if not any(str(item.get("mr_id") or "") == payload.profile_id for item in snapshot.get("databases", [])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前局点的 MESH Profile 不存在")
    return _submit(
        request,
        "database_upgrade",
        {
            "database_kind": payload.database_kind,
            "profile_id": payload.profile_id,
            "site_id": site_id,
        },
        resource_keys=[f"mesh-import:{site_id}", f"database-upgrade:{site_id}:{payload.profile_id}"],
    )


@router.post(
    "/legacy-archives/organize",
    response_model=DatabaseTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.database_legacy_archive_organize"))],
)
def organize_legacy_archives(request: Request) -> DatabaseTaskReferenceDTO:
    site_id = _site_id(request)
    return _submit(
        request,
        "legacy_database_archive_migration",
        {"site_id": site_id},
        resource_keys=[f"database-backup-center:{site_id}", f"mesh-import:{site_id}"],
    )


@router.post(
    "/backups/{backup_id}/validate",
    response_model=DatabaseTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.database_backup_validate"))],
)
def validate_backup(request: Request, backup_id: str) -> DatabaseTaskReferenceDTO:
    _run(lambda: _service(request).read_backup(backup_id, site_id=_site_id(request)))
    return _submit(
        request,
        "database_backup_validation",
        {"backup_id": backup_id},
        resource_keys=[f"database-backup:{backup_id}"],
    )


@router.post(
    "/backups/{backup_id}/restore",
    response_model=DatabaseTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.database_backup_restore"))],
)
def restore_backup(
    request: Request,
    backup_id: str,
    payload: DatabaseBackupActionRequest,
) -> DatabaseTaskReferenceDTO:
    if not payload.confirmed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="恢复数据库备份前必须明确确认")
    site_id = _site_id(request)
    _run(lambda: _service(request).read_backup(backup_id, site_id=site_id))
    return _submit(
        request,
        "database_backup_restore",
        {"backup_id": backup_id, "confirmed": True},
        resource_keys=[f"database-backup:{backup_id}", f"mesh-import:{site_id}"],
    )


@router.post(
    "/backups/{backup_id}/delete",
    response_model=DatabaseTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.database_backup_delete"))],
)
def delete_backup(
    request: Request,
    backup_id: str,
    payload: DatabaseBackupActionRequest,
) -> DatabaseTaskReferenceDTO:
    if not payload.confirmed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="删除数据库备份前必须明确确认")
    _run(lambda: _service(request).read_backup(backup_id, site_id=_site_id(request)))
    return _submit(
        request,
        "database_backup_delete",
        {"backup_id": backup_id, "confirmed": True},
        resource_keys=[f"database-backup:{backup_id}"],
    )


@router.post(
    "/backups/{backup_id}/open-directory",
    response_model=DesktopActionDTO,
    dependencies=[Depends(require_feature("web.database_backup_open_directory"))],
)
def open_backup_directory(request: Request, backup_id: str) -> DesktopActionDTO:
    path = _run(lambda: _service(request).open_backup_directory(backup_id, site_id=_site_id(request)))
    result = request.app.state.desktop_action_service.open_controlled_path(path, expect_directory=True)
    return DesktopActionDTO(success=result.success, code=result.code, message=result.message)


def _submit(
    request: Request,
    task_type: str,
    params: dict[str, object],
    *,
    resource_keys: list[str] | None = None,
) -> DatabaseTaskReferenceDTO:
    task_id = uuid4().hex
    site_id = _site_id(request)
    names = {
        "database_upgrade": "升级数据库",
        "database_backup_validation": "验证数据库备份",
        "legacy_database_archive_migration": "整理历史数据库归档",
        "database_backup_restore": "恢复数据库备份",
        "database_backup_delete": "删除数据库备份",
    }
    request.app.state.site_process_adapter.start_job(
        BackgroundJob(
            job_id=task_id,
            task_type=task_type,
            params={
                **params,
                "site_name": site_id,
                "task_name": names[task_type],
                "owner": DATABASE_UPGRADE_OWNER,
                "resource_keys": list(resource_keys or ()),
                "resource_conflict_message": "当前数据库或备份已有维护任务正在执行",
            },
        )
    )
    return DatabaseTaskReferenceDTO(task_id=task_id, task_type=task_type)


def _run(callback):
    try:
        return callback()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "数据库备份不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库备份中心暂时不可用") from exc


__all__ = ["router"]
