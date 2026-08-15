from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from netconsole.core.runtime_environment import persistent_storage
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.site_storage import (
    DataRootPathRequest,
    SiteActivateRequest,
    SiteAuditSummaryResponse,
    SiteCleanupApplyRequest,
    SiteCleanupPlanResponse,
    SiteCleanupRestoreRequest,
    SiteCreateRequest,
    SiteDemoRebuildRequest,
    SiteExportRequest,
    SiteImportInspectRequest,
    SiteImportRequest,
    SiteRetentionExecuteRequest,
    SiteRetentionReportResponse,
    SiteTaskResponse,
    SiteTrashRequest,
    SiteTrashResponse,
    SiteUpdateRequest,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.database_upgrade.coordinator import (
    site_database_maintenance_key,
)
from netconsole.services.site_lifecycle import (
    SiteAuditService,
    SiteCleanupApplicationService,
)
from netconsole.services.site_retention import SiteRetentionService
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteStorageError,
)


router = APIRouter(prefix="/v1", tags=["site-and-storage"])


def _desktop(request: Request) -> None:
    if (
        request.app.state.runtime_mode is not RuntimeMode.DESKTOP
        or request.url.hostname != "127.0.0.1"
    ):
        raise HTTPException(status_code=403, detail="局点与数据管理仅允许本机桌面会话")
    if not bool(getattr(request.state, "desktop_session_authenticated", False)):
        raise HTTPException(status_code=401, detail="当前请求缺少桌面短期会话")


def _persistent_storage() -> None:
    if not persistent_storage():
        raise HTTPException(
            status_code=403,
            detail="隔离测试模式不允许修改、迁移或导入导出正式局点",
        )


def _sites(request: Request) -> SiteApplicationService:
    return request.app.state.site_application_service


def _storage(request: Request) -> DataRootApplicationService:
    return request.app.state.data_root_application_service


def _packages(request: Request) -> SitePackageService:
    return request.app.state.site_package_service


def _audit(request: Request) -> SiteAuditService:
    return request.app.state.site_audit_service


def _cleanup(request: Request) -> SiteCleanupApplicationService:
    return request.app.state.site_cleanup_application_service


def _retention(request: Request) -> SiteRetentionService:
    return request.app.state.site_retention_service


@router.get(
    "/sites",
    summary="列出全部局点",
    description="返回局点 Registry 摘要；路径字段仅用于通过桌面会话鉴权的内部设置页。",
    dependencies=[Depends(_desktop)],
)
def list_sites(request: Request) -> list[dict[str, object]]:
    return _call(_sites(request).list_sites)


@router.post(
    "/sites",
    status_code=status.HTTP_201_CREATED,
    summary="新建局点",
    description="在 staging 初始化数据库并校验后原子发布；失败不改变当前局点。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def create_site(request: Request, payload: SiteCreateRequest) -> dict[str, object]:
    return _call(
        lambda: _sites(request).create_site(
            payload.site_id,
            payload.display_name,
            remark=payload.remark,
            activate=payload.activate,
        )
    )


@router.get("/sites/active", summary="读取当前局点", dependencies=[Depends(_desktop)])
def active_site(request: Request) -> dict[str, object]:
    return _call(_sites(request).get_active_site)


@router.get(
    "/sites/{site_id}", summary="读取局点详情", dependencies=[Depends(_desktop)]
)
def get_site(request: Request, site_id: str) -> dict[str, object]:
    return _call(lambda: _sites(request).get_site(site_id))


@router.get(
    "/sites/{site_id}/task-result-storage",
    summary="读取任务结果存储 rollout 状态",
    description="只返回 schema、状态、revision、结果行数和启用标志。",
    dependencies=[Depends(_desktop)],
)
def task_result_storage_status(
    request: Request, site_id: str
) -> dict[str, object]:
    return _call(lambda: _sites(request).task_result_storage_status(site_id))


@router.patch(
    "/sites/{site_id}",
    summary="修改局点信息",
    description="只更新显示名称和基础信息，不修改稳定 ID、物理目录或历史关联。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def update_site(
    request: Request, site_id: str, payload: SiteUpdateRequest
) -> dict[str, object]:
    return _call(
        lambda: _sites(request).update_site_info(
            site_id,
            display_name=payload.display_name,
            line_name=payload.line_name,
            project_type=payload.project_type,
        )
    )


@router.post(
    "/sites/{site_id}/trash",
    response_model=SiteTrashResponse,
    summary="安全删除普通局点",
    description="将非当前普通局点原子移动到数据根 .trash 后再注销 Registry。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def trash_site(
    request: Request, site_id: str, payload: SiteTrashRequest
) -> SiteTrashResponse:
    result = _call(
        lambda: _cleanup(request).trash_site(
            site_id, confirm_display_name=payload.confirm_display_name
        )
    )
    return SiteTrashResponse.model_validate(result)


@router.post(
    "/sites/{site_id}/audit",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="审计局点",
    description="在 Task Center 中生成只读局点清单、SQLite 完整性和 Legacy/Demo 分类。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def audit_site(request: Request, site_id: str) -> SiteTaskResponse:
    if not _audit(request).site_exists(site_id):
        raise HTTPException(
            status_code=404, detail={"code": "SITE_NOT_FOUND", "message": "局点不存在"}
        )
    return _submit(request, "site_audit", {"site_id": site_id})


@router.get(
    "/sites/{site_id}/audit/latest",
    response_model=SiteAuditSummaryResponse,
    summary="读取最近局点审计",
    dependencies=[Depends(_desktop)],
)
def latest_site_audit(request: Request, site_id: str) -> SiteAuditSummaryResponse:
    result = _call(lambda: _audit(request).latest(site_id))
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"code": "SITE_AUDIT_NOT_FOUND", "message": "尚未生成局点审计"},
        )
    public = dict(result)
    public.pop("physical_path", None)
    public.pop("file_manifest", None)
    return SiteAuditSummaryResponse.model_validate(
        {
            name: public[name]
            for name in SiteAuditSummaryResponse.model_fields
            if name in public
        }
    )


@router.post(
    "/sites/{site_id}/retention/scan",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="扫描局点可清理数据",
    description="通过 Task Center 只读统计数据库、历史备份、原始数据和任务历史，不修改业务数据。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def scan_site_retention(request: Request, site_id: str) -> SiteTaskResponse:
    _call(lambda: _sites(request).get_site(site_id))
    return _submit(request, "site_retention_scan", {"site_id": site_id})


@router.get(
    "/sites/{site_id}/retention/latest",
    response_model=SiteRetentionReportResponse,
    summary="读取最近数据清理扫描",
    dependencies=[Depends(_desktop)],
)
def latest_site_retention(
    request: Request, site_id: str
) -> SiteRetentionReportResponse:
    report = _call(lambda: _retention(request).latest(site_id))
    if not report:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SITE_RETENTION_SCAN_NOT_FOUND",
                "message": "尚未生成数据清理扫描",
            },
        )
    return SiteRetentionReportResponse.model_validate(report)


@router.post(
    "/sites/{site_id}/retention/apply",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="执行局点数据清理",
    description="复验扫描令牌和候选证据后，通过 Task Center 执行所选归档或清理动作。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def apply_site_retention(
    request: Request, site_id: str, payload: SiteRetentionExecuteRequest
) -> SiteTaskResponse:
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SITE_RETENTION_CONFIRMATION_REQUIRED",
                "message": "执行数据清理前必须明确确认",
            },
        )
    _call(lambda: _sites(request).get_site(site_id))
    _call(lambda: _retention(request).validate_scan(site_id, payload.scan_token))
    _call(lambda: _sites(request).ensure_no_active_tasks(site_id))
    return _submit(
        request,
        "site_retention_apply",
        {
            "site_id": site_id,
            "scan_token": payload.scan_token,
            "candidate_ids": payload.candidate_ids,
        },
    )


@router.post(
    "/sites/{site_id}/cleanup/prepare",
    response_model=SiteCleanupPlanResponse,
    summary="准备局点安全清理",
    description="只生成二阶段清理 token 和 manifest，不移动或删除目录。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def prepare_site_cleanup(request: Request, site_id: str) -> SiteCleanupPlanResponse:
    plan = _call(lambda: _cleanup(request).prepare_cleanup(site_id))
    return SiteCleanupPlanResponse.model_validate(
        {
            name: plan[name]
            for name in SiteCleanupPlanResponse.model_fields
            if name in plan
        }
    )


@router.post(
    "/sites/{site_id}/cleanup/apply",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="执行局点安全清理",
    description="复核 manifest 后注销 Registry，并将目录移入可恢复回收区。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def apply_site_cleanup(
    request: Request, site_id: str, payload: SiteCleanupApplyRequest
) -> SiteTaskResponse:
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SITE_CLEANUP_CONFIRMATION_REQUIRED",
                "message": "清理前必须明确确认",
            },
        )
    plan = _call(lambda: _cleanup(request).load_plan(payload.cleanup_token))
    if plan.get("site_id") != site_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SITE_CLEANUP_TOKEN_INVALID",
                "message": "清理清单已变化，请重新准备",
            },
        )
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(
        request,
        "site_cleanup_apply",
        {"site_id": site_id, "cleanup_token": payload.cleanup_token},
    )


@router.post(
    "/sites/recycle/{cleanup_token}/restore",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="恢复已回收局点",
    description="在 30 天恢复期内，通过 Task Center 将受控回收区中的局点恢复到原路径。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def restore_site_cleanup(
    request: Request, cleanup_token: str, payload: SiteCleanupRestoreRequest
) -> SiteTaskResponse:
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SITE_CLEANUP_CONFIRMATION_REQUIRED",
                "message": "恢复前必须明确确认",
            },
        )
    plan = _call(lambda: _cleanup(request).load_plan(cleanup_token))
    if str(plan.get("status") or "") != "applied":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SITE_CLEANUP_RESTORE_INVALID",
                "message": "该回收记录当前不可恢复",
            },
        )
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(
        request,
        "site_cleanup_restore",
        {"site_id": str(plan.get("site_id") or ""), "cleanup_token": cleanup_token},
    )


@router.post(
    "/sites/demo/rebuild",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重建演示局点",
    description="在 staging 生成当前 Schema 的受控 Demo，旧 Demo 先移入可恢复回收区。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def rebuild_demo(request: Request, payload: SiteDemoRebuildRequest) -> SiteTaskResponse:
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DEMO_REBUILD_CONFIRMATION_REQUIRED",
                "message": "重建前必须明确确认",
            },
        )
    if payload.allow_user_data:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEMO_USER_DATA_EXPORT_REQUIRED",
                "message": "Demo 存在用户数据时必须先导出或备份，不能绕过审计",
            },
        )
    audit = _call(lambda: _audit(request).latest("demo"))
    if not audit:
        raise HTTPException(
            status_code=409,
            detail={"code": "SITE_AUDIT_REQUIRED", "message": "请先完成 Demo 只读审计"},
        )
    if not bool(audit.get("safe_to_replace")):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEMO_USER_DATA",
                "message": "Demo 可能包含用户数据，请先导出或备份",
            },
        )
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(
        request, "site_demo_rebuild", {"site_id": "demo", "allow_user_data": False}
    )


@router.post(
    "/sites/{site_id}/activate/preflight",
    summary="预检局点切换",
    description="只读检查目标局点与全局阻塞任务，不修改当前局点或数据路径。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def preflight_site_activation(request: Request, site_id: str) -> dict[str, object]:
    return _call(lambda: _sites(request).preflight_site_switch(site_id))


@router.post(
    "/sites/{site_id}/activate",
    summary="切换当前局点",
    description="有活动任务时拒绝；成功后要求 Electron 受控重启 Backend，使所有 Service 使用同一 SiteContext。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def activate_site(
    request: Request, site_id: str, payload: SiteActivateRequest
) -> dict[str, object]:
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail={"code": "SITE_SWITCH_BLOCKED", "message": "切换局点前必须确认"},
        )
    return _call(lambda: _sites(request).switch_site(site_id))


@router.post(
    "/sites/{site_id}/migrate",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="迁移单个局点",
    description="复制到目标数据根的 staging 并校验；源局点保留，不在当前 Backend 内热切换。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def migrate_site(
    request: Request, site_id: str, payload: DataRootPathRequest
) -> SiteTaskResponse:
    _call(lambda: _sites(request).get_site(site_id))
    _call(lambda: _sites(request).ensure_no_active_tasks(site_id))
    return _submit(
        request,
        "site_migration",
        {"site_id": site_id, "destination_root": payload.path},
    )


@router.post(
    "/sites/{site_id}/export",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="导出局点包",
    description="完整迁移包原样包含设备凭据；脱敏包和现场包不含密码。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def export_site(
    request: Request, site_id: str, payload: SiteExportRequest
) -> SiteTaskResponse:
    _call(lambda: _sites(request).get_site(site_id))
    _call(lambda: _sites(request).ensure_no_active_tasks(site_id))
    return _submit(
        request,
        "site_export",
        {
            "site_id": site_id,
            "destination_path": payload.destination_path,
            "package_type": payload.package_type,
        },
    )


@router.post(
    "/sites/import/inspect",
    summary="检查局点包",
    description="验证 manifest、checksum、路径、符号链接和解压大小，不写入业务目录。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def inspect_site_package(
    request: Request, payload: SiteImportInspectRequest
) -> dict[str, object]:
    return _call(
        lambda: _packages(request).inspect_package(
            Path(payload.package_path),
            target_site_id=payload.target_site_id or None,
        )
    )


@router.post(
    "/sites/import",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="导入局点包",
    description="创建 Task Center Worker；替换导入会先备份，失败恢复原局点。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def import_site(request: Request, payload: SiteImportRequest) -> SiteTaskResponse:
    _call(
        lambda: _packages(request).inspect_package(
            Path(payload.package_path),
            target_site_id=payload.site_id or payload.replace_site_id or None,
        )
    )
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(request, "site_import", payload.model_dump())


@router.get(
    "/storage/data-root", summary="读取当前数据根", dependencies=[Depends(_desktop)]
)
def get_data_root(request: Request) -> dict[str, object]:
    return _storage(request).snapshot().to_public()


@router.post(
    "/storage/data-root/validate",
    summary="校验候选数据根",
    description="校验可写性、仓库/安装目录、临时目录和嵌套迁移风险。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def validate_data_root(
    request: Request, payload: DataRootPathRequest
) -> dict[str, object]:
    return _call(lambda: _storage(request).validate(Path(payload.path)))


@router.post(
    "/storage/data-root/migration-plan",
    summary="生成数据根迁移计划",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def plan_data_root_migration(
    request: Request, payload: DataRootPathRequest
) -> dict[str, object]:
    result = _call(lambda: _storage(request).validate(Path(payload.path)))
    return {
        **result,
        "source_site_count": len(_sites(request).list_sites()),
        "old_data_retained": True,
        "restart_required": True,
    }


@router.post(
    "/storage/data-root/migrate",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="迁移全部数据",
    description="复制到 staging、校验 SQLite 后原子发布；旧数据不会自动删除。",
    dependencies=[Depends(_desktop), Depends(_persistent_storage)],
)
def migrate_data_root(
    request: Request, payload: DataRootPathRequest
) -> SiteTaskResponse:
    _call(lambda: _storage(request).validate(Path(payload.path)))
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(
        request, "site_data_root_migration", {"destination_root": payload.path}
    )


def _submit(
    request: Request,
    task_type: str,
    params: dict[str, object],
) -> SiteTaskResponse:
    task_id = uuid.uuid4().hex
    request.app.state.site_process_adapter.start_job(
        BackgroundJob(
            job_id=task_id,
            task_type=task_type,
            params={
                **params,
                "site_name": _sites(request).active_site_directory_name(),
                "task_name": {
                    "site_export": "导出局点",
                    "site_migration": "迁移单个局点",
                    "site_import": "导入局点",
                    "site_data_root_migration": "迁移全部数据",
                    "site_audit": "审计局点",
                    "site_cleanup_apply": "安全清理局点",
                    "site_cleanup_restore": "恢复局点",
                    "site_demo_rebuild": "重建演示局点",
                    "site_retention_scan": "扫描可清理数据",
                    "site_retention_apply": "执行局点数据清理",
                }[task_type],
                "owner": "site-storage",
                "resource_keys": (
                    [site_database_maintenance_key(str(params.get("site_id") or ""))]
                    if task_type in {"site_retention_scan", "site_retention_apply"}
                    else []
                ),
                "resource_conflict_message": "该局点已有数据清理任务正在执行",
            },
        ),
    )
    return SiteTaskResponse(task_id=task_id, task_type=task_type)


def _call(callback):
    try:
        return callback()
    except SiteStorageError as exc:
        if exc.code == "SITE_NOT_FOUND":
            status_code = 404
        elif exc.code == "SITE_TRASH_LOCKED":
            status_code = 423
        elif exc.code in {
            "SITE_INFO_UPDATE_FAILED",
            "SITE_TRASH_FAILED",
            "SITE_TRASH_ROLLBACK_FAILED",
        }:
            status_code = 503
        elif exc.code.endswith(
            ("CONFLICT", "EXISTS", "BLOCKED", "ACTIVE_TASKS")
        ) or exc.code in {
            "SITE_TRASH_CURRENT",
            "SITE_TRASH_DEMO",
            "SITE_TRASH_EMPTY_SHELL",
            "SITE_TRASH_PATH_INVALID",
        }:
            status_code = 409
        else:
            status_code = 422
        detail: dict[str, object] = {"code": exc.code, "message": str(exc)}
        if exc.details:
            detail["details"] = exc.details
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SITE_STORAGE_UNAVAILABLE",
                "message": "局点存储暂时不可用",
            },
        ) from exc


__all__ = ["router"]
