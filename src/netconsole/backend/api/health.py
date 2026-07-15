from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.version import APP_VERSION
from netconsole.models.api import HealthResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return health_response(str(request.app.state.backend_build_id))


def health_response(build_id: str) -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION.removeprefix("v"), build_id=build_id)
