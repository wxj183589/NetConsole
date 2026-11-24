from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.application.rail_transit.relationship_application_service import RelationshipApplicationError
from netconsole.models.api.rail_relationship import (
    RelationshipHistoryPage,
    RelationshipMutationRequest,
    RelationshipMutationResult,
    RelationshipPage,
)
from netconsole.services.site_manager import SiteManager

router = APIRouter(prefix="/rail-transit/relationships", tags=["rail-transit-relationships"])


def _service(request: Request):
    return request.app.state.rail_relationship_application_service


def _site_id(request: Request, value: str) -> str:
    supplied = value or request.app.state.rail_transit_base_data_query_service.current_site_id()
    return SiteManager(request.app.state.paths).validate_site_name(supplied)


@router.get("", response_model=RelationshipPage)
def list_relationships(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    relationship_type: str = Query(default="", max_length=40),
    entity_uid: str = Query(default="", max_length=160),
) -> RelationshipPage:
    try:
        return _service(request).list_current(_site_id(request, site_id), relationship_type=relationship_type, entity_uid=entity_uid)
    except RelationshipApplicationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/history", response_model=RelationshipHistoryPage)
def history(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    relationship_type: str = Query(default="", max_length=40),
    entity_uid: str = Query(default="", max_length=160),
) -> RelationshipHistoryPage:
    try:
        return _service(request).list_history(_site_id(request, site_id), relationship_type=relationship_type, entity_uid=entity_uid)
    except RelationshipApplicationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("", response_model=RelationshipMutationResult)
def mutate(request: Request, payload: RelationshipMutationRequest) -> RelationshipMutationResult:
    try:
        return _service(request).mutate(payload.model_copy(update={"site_id": _site_id(request, payload.site_id)}))
    except RelationshipApplicationError as exc:
        code = status.HTTP_409_CONFLICT if exc.code in {"BASE_DATA_REVISION_CONFLICT", "RELATION_ALREADY_EXISTS", "RELATION_CONFLICT", "RELATION_NOT_FOUND"} else status.HTTP_403_FORBIDDEN if exc.code.startswith("BASE_DATA_") else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)}) from exc

