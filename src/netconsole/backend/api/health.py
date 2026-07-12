from __future__ import annotations

from fastapi import APIRouter

from netconsole.core.version import APP_VERSION
from netconsole.models.api import HealthResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION.removeprefix("v"))
