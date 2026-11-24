from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status, Depends
from netconsole.backend.api.feature_access import require_feature

from netconsole.application.rail_transit.relationship_application_service import (
    RelationshipApplicationError,
)
from netconsole.models.api.rail_relationship import (
    EngineeringProjectRequest,
    RelationshipHistoryPage,
    RelationshipMutationRequest,
    RelationshipMutationResult,
    RelationshipPage,
)
from netconsole.services.site_manager import SiteManager

router = APIRouter(
    prefix="/rail-transit/relationships", tags=["rail-transit-relationships"]
)


def _service(request: Request):
    return request.app.state.rail_relationship_application_service


def _site_id(request: Request, value: str) -> str:
    supplied = (
        value
        or request.app.state.rail_transit_base_data_query_service.current_site_id()
    )
    return SiteManager(request.app.state.paths).validate_site_name(supplied)


@router.get("", response_model=RelationshipPage)
def list_relationships(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    relationship_type: str = Query(default="", max_length=40),
    entity_uid: str = Query(default="", max_length=160),
    at_time: str = Query(default="", max_length=64),
) -> RelationshipPage:
    try:
        return _service(request).list_current(
            _site_id(request, site_id),
            relationship_type=relationship_type,
            entity_uid=entity_uid,
            at_time=at_time,
        )
    except RelationshipApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/history", response_model=RelationshipHistoryPage)
def history(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    relationship_type: str = Query(default="", max_length=40),
    entity_uid: str = Query(default="", max_length=160),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> RelationshipHistoryPage:
    try:
        return _service(request).list_history(
            _site_id(request, site_id),
            relationship_type=relationship_type,
            entity_uid=entity_uid,
            page=page,
            page_size=page_size,
        )
    except RelationshipApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/engineering-context")
def engineering_context(
    request: Request,
    device_uuid: list[str] = Query(default=[], max_length=200),
    site_id: str = Query(default="", max_length=100),
    at_time: str = Query(default="", max_length=64),
    expected_revision: str = Query(default="", max_length=160),
):
    return _service(request).engineering_context(
        _site_id(request, site_id),
        device_uuid,
        at_time=at_time,
        expected_revision=expected_revision,
    )


@router.get("/catalog")
def catalog(request: Request, site_id: str = ""):
    return _call(lambda: _service(request).catalog(_site_id(request, site_id)))


@router.get("/delete-preflight")
def delete_preflight(request: Request, entity_uid: str, site_id: str = ""):
    return _call(
        lambda: _service(request).deletion_preflight(
            _site_id(request, site_id), entity_uid
        )
    )


@router.get("/ac-resources", dependencies=[Depends(require_feature("module.ac"))])
def ac_resources(request: Request, ac_device_uuid: str, site_id: str = ""):
    return _call(
        lambda: _service(request).fit_ap_overview(
            _site_id(request, site_id), ac_device_uuid
        )
    )


@router.post(
    "/projects",
    dependencies=[Depends(require_feature("capability.rail_base_data.write"))],
)
def save_project(
    request: Request, payload: EngineeringProjectRequest, preview: bool = False
):
    return _call(
        lambda: _service(request).save_project(
            _site_id(request, payload.site_id),
            payload.model_dump(mode="json"),
            preview=preview,
        )
    )


@router.post(
    "/preview",
    response_model=RelationshipMutationResult,
    dependencies=[Depends(require_feature("capability.rail_base_data.write"))],
)
def preview(request: Request, payload: RelationshipMutationRequest):
    return _call(
        lambda: _service(request).mutate(
            payload.model_copy(
                update={
                    "site_id": _site_id(request, payload.site_id),
                    "actor": "desktop-session",
                }
            ),
            preview=True,
        )
    )


@router.post(
    "",
    response_model=RelationshipMutationResult,
    dependencies=[Depends(require_feature("capability.rail_base_data.write"))],
)
def mutate(
    request: Request, payload: RelationshipMutationRequest
) -> RelationshipMutationResult:
    return _call(
        lambda: _service(request).mutate(
            payload.model_copy(
                update={
                    "site_id": _site_id(request, payload.site_id),
                    "actor": "desktop-session",
                }
            )
        )
    )


def _call(callback):
    try:
        return callback()
    except RelationshipApplicationError as exc:
        code = (
            status.HTTP_409_CONFLICT
            if exc.code
            in {
                "BASE_DATA_REVISION_CONFLICT",
                "RELATION_ALREADY_EXISTS",
                "RELATION_CONFLICT",
                "RELATION_NOT_FOUND",
                "RELATION_MIGRATION_REQUIRED",
            }
            else status.HTTP_403_FORBIDDEN
            if exc.code
            in {
                "BASE_DATA_WRITE_DISABLED",
                "BASE_DATA_COPY_WRITE_NOT_AUTHORIZED",
                "BASE_DATA_REAL_WRITE_NOT_AUTHORIZED",
                "ISOLATED_TEST_READONLY",
            }
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=code, detail={"code": exc.code, "message": str(exc)}
        ) from exc
