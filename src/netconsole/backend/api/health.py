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
    )


def health_response(
    build_id: str,
    *,
    data_root: str = "",
    active_site_id: str = "",
    storage_schema_version: int = CURRENT_STORAGE_SCHEMA_VERSION,
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=APP_VERSION.removeprefix("v"),
        build_id=build_id,
        data_root=data_root,
        active_site_id=active_site_id,
        storage_schema_version=storage_schema_version,
    )
