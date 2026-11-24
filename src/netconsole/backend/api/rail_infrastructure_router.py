from fastapi import APIRouter, Depends, HTTPException, Query, Request

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDTO,
    InfrastructureSwitchApContextPageDTO,
    OrganizationBatchRequest,
    OrganizationBatchResultDTO,
    OrganizationCatalogDTO,
    OrganizationNodeRequest,
)
from netconsole.application.rail_transit.infrastructure_application_service import RelationshipApplicationError
from netconsole.services.site_storage import SiteStorageError

router = APIRouter(
    prefix="/rail-transit/infrastructure", tags=["rail-transit-infrastructure"]
)
_write = [Depends(require_feature("capability.rail_infrastructure.write"))]


def _call(callback):
    try:
        return callback()
    except RelationshipApplicationError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except SiteStorageError as exc:
        raise HTTPException(status_code=404, detail="局点不可用") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="组织结构查询参数无效") from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="组织结构查询暂时不可用") from exc


@router.get("", response_model=InfrastructureDTO)
def infrastructure(request: Request, site_id: str = Query(default="", max_length=100)):
    return _call(
        lambda: (
            request.app.state.rail_infrastructure_application_service.infrastructure(
                site_id
            )
        )
    )


@router.post(
    "/initialize",
    response_model=InfrastructureDTO,
    dependencies=_write,
)
def initialize(request: Request, site_id: str = Query(min_length=1, max_length=100)):
    return _call(lambda: request.app.state.rail_infrastructure_application_service.initialize(site_id))


@router.get("/organization-catalog", response_model=OrganizationCatalogDTO, dependencies=_write)
def organization_catalog(request: Request, site_id: str = Query(min_length=1, max_length=100)):
    return _call(lambda: request.app.state.rail_infrastructure_application_service.organization_catalog(site_id))


@router.post("/organization-assets/preview", response_model=OrganizationBatchResultDTO, dependencies=_write)
def preview_organization_assets(
    request: Request, payload: OrganizationBatchRequest, site_id: str = Query(min_length=1, max_length=100)
):
    return _call(lambda: request.app.state.rail_infrastructure_application_service.change_organization_assets(
        site_id, payload, preview=True
    ))


@router.post("/organization-assets/apply", response_model=OrganizationBatchResultDTO, dependencies=_write)
def apply_organization_assets(
    request: Request, payload: OrganizationBatchRequest, site_id: str = Query(min_length=1, max_length=100)
):
    return _call(lambda: request.app.state.rail_infrastructure_application_service.change_organization_assets(
        site_id, payload, preview=False
    ))


@router.post("/organization-nodes", dependencies=_write)
def save_organization_node(
    request: Request, payload: OrganizationNodeRequest, site_id: str = Query(min_length=1, max_length=100)
):
    return {"node_uid": _call(lambda: request.app.state.rail_infrastructure_application_service.save_organization_node(
        site_id, payload
    ))}


@router.get(
    "/switch-aps",
    response_model=InfrastructureSwitchApContextPageDTO,
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
