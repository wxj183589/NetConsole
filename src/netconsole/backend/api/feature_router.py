from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from netconsole.backend.api.edition_access import (
    EditionAccessError,
    EditionUnlockNotAvailableError,
    EditionUnlockPasswordError,
    EditionUnlockThrottledError,
    edition_runtime_status,
    ensure_edition_gate,
    lock_customer_edition,
    unlock_customer_edition,
)
from netconsole.core.feature_registry import list_features
from netconsole.models.api.features import WebFeatureStateDTO, WebFeatureStateListDTO


router = APIRouter(prefix="/features", tags=["features"])


class EditionRuntimeStatusDTO(BaseModel):
    edition: str
    base_profile: str
    active_profile: str
    full_features_active: bool
    admin_unlock_available: bool
    relock_available: bool
    packaged_runtime: bool
    profile_source: str


class EditionUnlockRequestDTO(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@router.get("", response_model=WebFeatureStateListDTO)
def web_feature_states(request: Request) -> WebFeatureStateListDTO:
    gate = ensure_edition_gate(request.app)
    return WebFeatureStateListDTO(
        items=[
            WebFeatureStateDTO(
                feature_id=item.feature_id,
                visible=gate.is_visible(item.feature_id),
                enabled=gate.is_enabled(item.feature_id),
            )
            for item in list_features()
            if item.feature_id.startswith("web.") or item.feature_id == "network_tools.traffic"
        ]
    )


@router.get("/edition", response_model=EditionRuntimeStatusDTO)
def edition_status(request: Request) -> EditionRuntimeStatusDTO:
    _require_loopback(request)
    return EditionRuntimeStatusDTO(**edition_runtime_status(request.app))


@router.post("/edition/unlock", response_model=EditionRuntimeStatusDTO)
def unlock_edition(
    payload: EditionUnlockRequestDTO,
    request: Request,
) -> EditionRuntimeStatusDTO:
    _require_loopback(request)
    try:
        unlock_customer_edition(
            request.app,
            payload.password,
            operator="desktop-loopback",
        )
    except EditionUnlockPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except EditionUnlockThrottledError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc
    except EditionUnlockNotAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except EditionAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return EditionRuntimeStatusDTO(**edition_runtime_status(request.app))


@router.post("/edition/lock", response_model=EditionRuntimeStatusDTO)
def lock_edition(request: Request) -> EditionRuntimeStatusDTO:
    _require_loopback(request)
    try:
        lock_customer_edition(request.app)
    except EditionUnlockNotAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except EditionAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return EditionRuntimeStatusDTO(**edition_runtime_status(request.app))


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    try:
        allowed = ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="版本维护接口仅允许桌面本机访问",
        )


__all__ = ["router"]
