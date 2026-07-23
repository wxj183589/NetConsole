from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from netconsole.core import app_logger
from netconsole.models.api.device_compatibility import DeviceCompatibilitySummaryDTO
from netconsole.services.device_compatibility.service import (
    DeviceCompatibilityError,
    DeviceCompatibilityService,
)


router = APIRouter(prefix="/device-compatibility", tags=["device-compatibility"])


@router.get("/summary", response_model=DeviceCompatibilitySummaryDTO)
def compatibility_summary(request: Request) -> DeviceCompatibilitySummaryDTO:
    try:
        payload = DeviceCompatibilityService(request.app.state.paths).summary()
    except (DeviceCompatibilityError, OSError, UnicodeError) as exc:
        app_logger.log_error(
            "DEVICE_COMPATIBILITY_RESOURCE_FAILED",
            f"code=DEVICE_COMPATIBILITY_RESOURCE_UNAVAILABLE type={type(exc).__name__}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DEVICE_COMPATIBILITY_RESOURCE_UNAVAILABLE",
                "message": "设备兼容性基线暂时不可用",
            },
        ) from exc
    return DeviceCompatibilitySummaryDTO.model_validate(payload)


__all__ = ["router"]
