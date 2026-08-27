from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request

from netconsole.backend.api.site_storage_router import _desktop

if TYPE_CHECKING:
    from netconsole.services.storage_audit import StorageAuditService


router = APIRouter(prefix="/v1/storage-audit", tags=["storage-audit"])


def _service(request: Request) -> StorageAuditService:
    service = getattr(request.app.state, "storage_audit_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="存储审计服务未接线")
    return service


@router.get("", summary="读取存储审计报告", dependencies=[Depends(_desktop)])
def get_storage_audit(request: Request) -> dict[str, object]:
    return _service(request).snapshot()


__all__ = ["router"]
