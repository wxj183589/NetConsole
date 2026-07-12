from __future__ import annotations

from fastapi import APIRouter

from netconsole.backend.api.health import router as health_router
from netconsole.backend.api.task_router import router as task_router
from netconsole.backend.api.task_router import ws_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(task_router)

__all__ = ["api_router", "ws_router"]
