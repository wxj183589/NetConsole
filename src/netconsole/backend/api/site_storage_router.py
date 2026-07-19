from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.site_storage import (
    DataRootPathRequest,
    SiteActivateRequest,
    SiteCreateRequest,
    SiteExportRequest,
    SiteImportInspectRequest,
    SiteImportRequest,
    SiteTaskResponse,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteStorageError,
)


router = APIRouter(prefix="/v1", tags=["site-and-storage"])


def _desktop(request: Request) -> None:
    if request.app.state.runtime_mode is not RuntimeMode.DESKTOP or request.url.hostname != "127.0.0.1":
        raise HTTPException(status_code=403, detail="局点与数据管理仅允许本机桌面会话")
    if not bool(getattr(request.state, "desktop_session_authenticated", False)):
        raise HTTPException(status_code=401, detail="当前请求缺少桌面短期会话")


def _sites(request: Request) -> SiteApplicationService:
    return request.app.state.site_application_service


def _storage(request: Request) -> DataRootApplicationService:
    return request.app.state.data_root_application_service


def _packages(request: Request) -> SitePackageService:
    return request.app.state.site_package_service


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
    dependencies=[Depends(_desktop)],
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


@router.get("/sites/{site_id}", summary="读取局点详情", dependencies=[Depends(_desktop)])
def get_site(request: Request, site_id: str) -> dict[str, object]:
    return _call(lambda: _sites(request).get_site(site_id))


@router.post(
    "/sites/{site_id}/activate",
    summary="切换当前局点",
    description="有活动任务时拒绝；成功后要求 Electron 受控重启 Backend，使所有 Service 使用同一 SiteContext。",
    dependencies=[Depends(_desktop)],
)
def activate_site(request: Request, site_id: str, payload: SiteActivateRequest) -> dict[str, object]:
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail={"code": "SITE_SWITCH_BLOCKED", "message": "切换局点前必须确认"})
    return _call(lambda: _sites(request).switch_site(site_id))


@router.post(
    "/sites/{site_id}/migrate",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="迁移单个局点",
    description="复制到目标数据根的 staging 并校验；源局点保留，不在当前 Backend 内热切换。",
    dependencies=[Depends(_desktop)],
)
def migrate_site(request: Request, site_id: str, payload: DataRootPathRequest) -> SiteTaskResponse:
    _call(lambda: _sites(request).get_site(site_id))
    _call(lambda: _sites(request).ensure_no_active_tasks(site_id))
    return _submit(request, "site_migration", {"site_id": site_id, "destination_root": payload.path})


@router.post(
    "/sites/{site_id}/export",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="导出局点包",
    description="创建 Task Center Worker；包内不包含 Token、密码、bootstrap、锁、缓存和临时文件。",
    dependencies=[Depends(_desktop)],
)
def export_site(request: Request, site_id: str, payload: SiteExportRequest) -> SiteTaskResponse:
    _call(lambda: _sites(request).get_site(site_id))
    _call(lambda: _sites(request).ensure_no_active_tasks(site_id))
    return _submit(request, "site_export", {"site_id": site_id, "destination_path": payload.destination_path})


@router.post(
    "/sites/import/inspect",
    summary="检查局点包",
    description="验证 manifest、checksum、路径、符号链接和解压大小，不写入业务目录。",
    dependencies=[Depends(_desktop)],
)
def inspect_site_package(request: Request, payload: SiteImportInspectRequest) -> dict[str, object]:
    return _call(lambda: _packages(request).inspect_package(Path(payload.package_path)))


@router.post(
    "/sites/import",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="导入局点包",
    description="创建 Task Center Worker；替换导入会先备份，失败恢复原局点。",
    dependencies=[Depends(_desktop)],
)
def import_site(request: Request, payload: SiteImportRequest) -> SiteTaskResponse:
    _call(lambda: _packages(request).inspect_package(Path(payload.package_path)))
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(request, "site_import", payload.model_dump())


@router.get("/storage/data-root", summary="读取当前数据根", dependencies=[Depends(_desktop)])
def get_data_root(request: Request) -> dict[str, object]:
    return _storage(request).snapshot().to_public()


@router.post(
    "/storage/data-root/validate",
    summary="校验候选数据根",
    description="校验可写性、仓库/安装目录、临时目录和嵌套迁移风险。",
    dependencies=[Depends(_desktop)],
)
def validate_data_root(request: Request, payload: DataRootPathRequest) -> dict[str, object]:
    return _call(lambda: _storage(request).validate(Path(payload.path)))


@router.post(
    "/storage/data-root/migration-plan",
    summary="生成数据根迁移计划",
    dependencies=[Depends(_desktop)],
)
def plan_data_root_migration(request: Request, payload: DataRootPathRequest) -> dict[str, object]:
    result = _call(lambda: _storage(request).validate(Path(payload.path)))
    return {**result, "source_site_count": len(_sites(request).list_sites()), "old_data_retained": True, "restart_required": True}


@router.post(
    "/storage/data-root/migrate",
    response_model=SiteTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="迁移全部数据",
    description="复制到 staging、校验 SQLite 后原子发布；旧数据不会自动删除。",
    dependencies=[Depends(_desktop)],
)
def migrate_data_root(request: Request, payload: DataRootPathRequest) -> SiteTaskResponse:
    _call(lambda: _storage(request).validate(Path(payload.path)))
    _call(_sites(request).ensure_no_active_tasks_anywhere)
    return _submit(request, "site_data_root_migration", {"destination_root": payload.path})


def _submit(request: Request, task_type: str, params: dict[str, object]) -> SiteTaskResponse:
    task_id = uuid.uuid4().hex
    request.app.state.site_process_adapter.start_job(
        BackgroundJob(
            job_id=task_id,
            task_type=task_type,
            params={
                **params,
                "site_name": _sites(request).active_site_id(),
                "task_name": {
                    "site_export": "导出局点",
                    "site_migration": "迁移单个局点",
                    "site_import": "导入局点",
                    "site_data_root_migration": "迁移全部数据",
                }[task_type],
                "owner": "site-storage",
            },
        )
    )
    return SiteTaskResponse(task_id=task_id, task_type=task_type)


def _call(callback):
    try:
        return callback()
    except SiteStorageError as exc:
        status_code = 404 if exc.code == "SITE_NOT_FOUND" else 409 if exc.code.endswith(("CONFLICT", "EXISTS", "BLOCKED", "ACTIVE_TASKS")) else 422
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"code": "SITE_STORAGE_UNAVAILABLE", "message": "局点存储暂时不可用"}) from exc


__all__ = ["router"]
