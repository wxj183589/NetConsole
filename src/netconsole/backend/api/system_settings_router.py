from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from netconsole.core import app_logger
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsConflictError, SettingsFileInvalidError, SettingsStore
from netconsole.models.api.system_settings import (
    FeatureConfigurationTarget,
    FeatureRuntimeStatusDTO,
    FeatureSettingsRestoreDTO,
    FeatureSettingsSnapshotDTO,
    FeatureSettingsUpdateDTO,
    SystemSettingsSaveDTO,
    NetworkComponentsSnapshotDTO,
    NetworkComponentUpdateDTO,
    SystemSettingsSnapshotDTO,
    RuntimeSelfCheckSnapshotDTO,
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


def _network_components(request: Request) -> None:
    if request.app.state.feature_gate.is_enabled("web.network_test_components"):
        return
    raise HTTPException(status_code=404, detail="功能未启用")


def _service(request: Request) -> SettingsApplicationService:
    return request.app.state.settings_application_service


def _self_check(request: Request) -> RuntimeSelfCheckService:
    return request.app.state.runtime_self_check_service


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
    "/network-components",
    response_model=NetworkComponentsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_network_components)],
)
def get_network_components(request: Request) -> NetworkComponentsSnapshotDTO:
    return _call(_service(request).network_components)


@router.put(
    "/network-components/{component_name}",
    response_model=NetworkComponentsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_network_components)],
)
def save_network_component(
    component_name: Literal["iperf3", "fping"],
    payload: NetworkComponentUpdateDTO,
    request: Request,
) -> NetworkComponentsSnapshotDTO:
    return _call(lambda: _service(request).save_network_component(component_name, payload))


@router.get(
    "/self-check",
    response_model=RuntimeSelfCheckSnapshotDTO,
    dependencies=[Depends(_desktop)],
)
def runtime_self_check(request: Request) -> RuntimeSelfCheckSnapshotDTO:
    return _self_check(request).run(
        backend_build_id=str(getattr(request.app.state, "backend_build_id", "")),
        frontend_build_id=str(getattr(request.app.state, "frontend_build_id", "")),
    )


@router.get(
    "/features",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def get_feature_settings(
    request: Request,
    target: FeatureConfigurationTarget = "customer",
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).feature_settings(target))


@router.put(
    "/features",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def save_feature_settings(
    request: Request,
    payload: FeatureSettingsUpdateDTO,
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).save_features(payload))


@router.post(
    "/features/check",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def check_feature_settings(
    request: Request,
    payload: FeatureSettingsUpdateDTO,
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).check_features(payload))


@router.post(
    "/features/auto-fix",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def auto_fix_feature_settings(
    request: Request,
    payload: FeatureSettingsUpdateDTO,
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).auto_fix_features(payload))


@router.post(
    "/features/preview",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def preview_feature_settings(
    request: Request,
    payload: FeatureSettingsUpdateDTO,
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).preview_features(payload))


@router.post(
    "/features/preview/exit",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def exit_feature_preview(
    request: Request,
    target: FeatureConfigurationTarget = "customer",
) -> FeatureSettingsSnapshotDTO:
    return _call(lambda: _service(request).exit_feature_preview(target))


@router.post(
    "/features/restore",
    response_model=FeatureSettingsSnapshotDTO,
    dependencies=[Depends(_desktop), Depends(_feature_switch)],
)
def restore_feature_settings(
    request: Request,
    payload: FeatureSettingsRestoreDTO,
) -> FeatureSettingsSnapshotDTO:
    return _call(
        lambda: _service(request).restore_features(
            confirmed=payload.confirmed,
            target=payload.target,
        )
    )


@router.get(
    "/features/runtime-status",
    response_model=FeatureRuntimeStatusDTO,
    dependencies=[Depends(_desktop)],
)
def feature_runtime_status(request: Request) -> FeatureRuntimeStatusDTO:
    return _call(_service(request).runtime_feature_status)


@router.post(
    "/features/runtime-overrides/clear",
    response_model=FeatureRuntimeStatusDTO,
    dependencies=[Depends(_desktop)],
)
def clear_feature_runtime_overrides(
    request: Request,
    payload: ConfirmedAction,
) -> FeatureRuntimeStatusDTO:
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail="清除历史运行时覆盖前必须确认")
    return _call(_service(request).clear_runtime_feature_overrides)


@router.post(
    "/features/reload",
    response_model=FeatureRuntimeStatusDTO,
    dependencies=[Depends(_desktop)],
)
def reload_feature_gate(request: Request) -> FeatureRuntimeStatusDTO:
    return _call(_service(request).reload_feature_gate)


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
