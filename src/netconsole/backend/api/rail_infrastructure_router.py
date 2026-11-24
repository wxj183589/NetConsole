from fastapi import APIRouter, Depends, HTTPException, Query, Request

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDTO,
    InfrastructureSwitchApsDTO,
)

router = APIRouter(
    prefix="/rail-transit/infrastructure", tags=["rail-transit-infrastructure"]
)


def _call(callback):
    try:
        return callback()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="基础设施查询参数无效") from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="基础设施查询暂时不可用") from exc


@router.get("", response_model=InfrastructureDTO)
def infrastructure(request: Request, site_id: str = Query(default="", max_length=100)):
    return _call(
        lambda: (
            request.app.state.rail_infrastructure_application_service.infrastructure(
                site_id
            )
        )
    )


@router.get(
    "/switch-aps",
    response_model=InfrastructureSwitchApsDTO,
    dependencies=[Depends(require_feature("module.trackside_ap"))],
)
def switch_aps(
    request: Request,
    device_uuid: str = Query(min_length=1, max_length=64),
    site_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
):
    return _call(
        lambda: request.app.state.rail_infrastructure_application_service.switch_aps(
            site_id, device_uuid, page
        )
    )
