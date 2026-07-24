from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from netconsole.core import app_logger
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsConflictError, SettingsFileInvalidError, SettingsStore
from netconsole.models.api.system_settings import (
    FeatureSettingsSnapshotDTO, FeatureSettingsUpdateDTO, SystemSettingsSaveDTO,
    SystemSettingsSnapshotDTO, RuntimeSelfCheckSnapshotDTO,
)
from netconsole.services.external_tool_service import launch_ipop
from netconsole.services.settings_application_service import SettingsApplicationService
from netconsole.services.runtime_self_check_service import RuntimeSelfCheckService


class ConfirmedAction(BaseModel):
    confirmed: bool


class NativeSettingsAction(BaseModel):
    action: Literal["open_settings_config", "open_current_site", "launch_ipop"]


def _system_settings(request: Request) -> None:
    gate = request.app.state.feature_gate
    if gate.is_enabled("web.system_settings") or gate.is_customer_preview_active():
        return
    raise HTTPException(status_code=404, detail="功能未启用")


router = APIRouter(
    prefix="/settings",
    tags=["system-settings"],
    dependencies=[Depends(_system_settings)],
)


def _desktop(request: Request) -> None:
    if request.app.state.runtime_mode is not RuntimeMode.DESKTOP or request.url.hostname != "127.0.0.1":
        raise HTTPException(status_code=403, detail="系统设置仅允许本机桌面会话")
    if not bool(getattr(request.state, "desktop_session_authenticated", False)):
        raise HTTPException(status_code=401, detail="当前请求缺少桌面短期会话")


def _feature_switch(request: Request) -> None:
    gate = request.app.state.feature_gate
    if not gate.is_feature_configuration_available():
        app_logger.log_warning("FEATURE_CONFIGURATION_DISABLED", "runtime=packaged endpoint=system_settings")
        raise HTTPException(status_code=403, detail="正式包使用固定生产功能集，功能配置不可用")
    if gate.is_enabled("web.feature_switch") or gate.is_customer_preview_active():
        return
    raise HTTPException(status_code=404, detail="功能未启用")


def _service(request: Request) -> SettingsApplicationService:
    return request.app.state.settings_application_service


@router.get("", response_model=SystemSettingsSnapshotDTO, dependencies=[Depends(_desktop)])
def get_settings(request: Request) -> SystemSettingsSnapshotDTO:
    return _call(_service(request).get)


@router.put("", response_model=SystemSettingsSnapshotDTO, dependencies=[Depends(_desktop)])
def save_settings(request: Request, payload: SystemSettingsSaveDTO) -> SystemSettingsSnapshotDTO:
    return _call(lambda: _service(request).save(payload))


@router.post("/reload", response_model=SystemSettingsSnapshotDTO, dependencies=[Depends(_desktop)])
def reload_settings(request: Request) -> SystemSettingsSnapshotDTO:
    return _call(_service(request).reload)


@router.get(
    "/self-check",
    response_model=RuntimeSelfCheckSnapshotDTO,
    dependencies=[Depends(_desktop)],
)
def runtime_self_check(request: Request) -> RuntimeSelfCheckSnapshotDTO:
    service = _service(request)
    return RuntimeSelfCheckService(
        service.paths,
        service.feature_gate,
        service.site_name,
    ).run(
        backend_build_id=str(getattr(request.app.state, "backend_build_id", "")),
        frontend_build_id=str(getattr(request.app.state, "frontend_build_id", "")),
    )


@router.get("/features", response_model=FeatureSettingsSnapshotDTO, dependencies=[Depends(_desktop), Depends(_feature_switch)])
def get_feature_settings(request: Request) -> FeatureSettingsSnapshotDTO:
    return _call(_service(request).feature_settings)


@router.put("/features", response_model=FeatureSettingsSnapshotDTO, dependencies=[Depends(_desktop), Depends(_feature_switch)])
def save_feature_settings(request: Request, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).save_features(payload))


@router.post("/features/preview", response_model=FeatureSettingsSnapshotDTO, dependencies=[Depends(_desktop), Depends(_feature_switch)])
def preview_feature_settings(request: Request, payload: FeatureSettingsUpdateDTO) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).preview_features(payload))


@router.post("/features/preview/exit", response_model=FeatureSettingsSnapshotDTO, dependencies=[Depends(_desktop), Depends(_feature_switch)])
def exit_feature_preview(request: Request) -> FeatureSettingsSnapshotDTO:
    return _call(_service(request).exit_feature_preview)


@router.post("/features/restore", response_model=FeatureSettingsSnapshotDTO, dependencies=[Depends(_desktop), Depends(_feature_switch)])
def restore_feature_settings(request: Request, payload: ConfirmedAction) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).restore_features(confirmed=payload.confirmed))


@router.post("/native-action", dependencies=[Depends(_desktop)])
def execute_native_settings_action(request: Request, payload: NativeSettingsAction) -> dict[str, bool]:
    service = _service(request)
    if payload.action == "launch_ipop":
        result = launch_ipop(service.paths, settings=SettingsStore(service.paths))
        if not result.success:
            raise HTTPException(status_code=422, detail=result.message)
        return {"success": True}
    target = (
        service.paths.settings_path.parent
        if payload.action == "open_settings_config"
        else service.paths.site_dir(service.site_name)
    )
    target.mkdir(parents=True, exist_ok=True)
    result = request.app.state.desktop_action_service.open_controlled_path(
        target, expect_directory=True
    )
    if not result.success:
        raise HTTPException(status_code=422, detail=result.message)
    return {"success": True}


def _call(callback):
    try:
        return callback()
    except SettingsConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SettingsFileInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="系统设置文件暂时不可用") from exc


__all__ = ["router"]
