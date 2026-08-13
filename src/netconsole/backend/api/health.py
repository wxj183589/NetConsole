from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.version import APP_VERSION
from netconsole.core.storage_manifest import CURRENT_STORAGE_SCHEMA_VERSION
from netconsole.models.api import HealthResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    sites = request.app.state.site_application_service
    return health_response(
        str(request.app.state.backend_build_id),
        data_root=str(request.app.state.paths.data_root),
        active_site_id=sites.active_site_id(),
        storage_schema_version=CURRENT_STORAGE_SCHEMA_VERSION,
        runtime_services_status=str(getattr(request.app.state, "runtime_services_status", "ready")),
        runtime_services_ready=bool(getattr(request.app.state, "runtime_services_ready", True)),
        runtime_services_error=str(getattr(request.app.state, "runtime_services_error", "")),
        performance_mode=str(getattr(request.app.state, "performance_mode", "standard")),
        unattended_status=str(getattr(request.app.state, "unattended_status", "disabled")),
        unattended_ready=bool(getattr(request.app.state, "unattended_ready", False)),
        unattended_error=str(getattr(request.app.state, "unattended_error", "")),
    )


def health_response(
    build_id: str,
    *,
    data_root: str = "",
    active_site_id: str = "",
    storage_schema_version: int = CURRENT_STORAGE_SCHEMA_VERSION,
    runtime_services_status: str = "ready",
    runtime_services_ready: bool = True,
    runtime_services_error: str = "",
    performance_mode: str = "standard",
    unattended_status: str = "disabled",
    unattended_ready: bool = False,
    unattended_error: str = "",
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=APP_VERSION.removeprefix("v"),
        build_id=build_id,
        data_root=data_root,
        active_site_id=active_site_id,
        storage_schema_version=storage_schema_version,
        runtime_services_status=runtime_services_status,
        runtime_services_ready=runtime_services_ready,
        runtime_services_error=runtime_services_error,
        performance_mode=performance_mode,
        unattended_status=unattended_status,
        unattended_ready=unattended_ready,
        unattended_error=unattended_error,
    )
