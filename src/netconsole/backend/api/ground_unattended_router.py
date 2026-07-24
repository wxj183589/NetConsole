from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.ground_unattended import (
    GroundActionResponseDTO,
    GroundArchiveDTO,
    GroundArchiveDeleteRequestDTO,
    GroundArchivePageDTO,
    GroundDeepCollectionPageDTO,
    GroundPingSummaryPageDTO,
    GroundPriorityUpdateDTO,
    GroundTimelinePageDTO,
    GroundUnattendedProfileDTO,
    GroundUnattendedProfileUpdateDTO,
    GroundUnattendedStatusDTO,
    GroundUnattendedTrainDTO,
    GroundUnattendedTrainPageDTO,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
)
from netconsole.models.api.system_maintenance import DesktopActionDTO


router = APIRouter(
    prefix="/rail-transit/ground-unattended",
    tags=["ground-unattended"],
    dependencies=[Depends(require_feature("web.ground_unattended"))],
)


def _service(request: Request) -> GroundUnattendedApplicationService:
    service = getattr(request.app.state, "ground_unattended_application_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GROUND_UNATTENDED_UNAVAILABLE",
                "message": "地面无人值守后台服务未接线",
            },
        )
    return service


def _site_id(request: Request) -> str:
    try:
        return SiteManager(request.app.state.paths).validate_site_name(
            SiteManager(request.app.state.paths).get_current_site()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SITE_INVALID", "message": "当前局点标识无效"},
        ) from exc


@router.get("/status", response_model=GroundUnattendedStatusDTO)
def get_status(request: Request) -> GroundUnattendedStatusDTO:
    return _call(lambda: _service(request).status(_site_id(request)))


@router.get("/profile", response_model=GroundUnattendedProfileDTO)
def get_profile(request: Request) -> GroundUnattendedProfileDTO:
    return _call(lambda: _service(request).get_profile(_site_id(request)))


@router.put("/profile", response_model=GroundUnattendedProfileDTO)
def update_profile(
    request: Request,
    payload: GroundUnattendedProfileUpdateDTO,
) -> GroundUnattendedProfileDTO:
    return _call(lambda: _service(request).update_profile(_site_id(request), payload))


@router.post(
    "/start",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def start(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).start_now(_site_id(request)))


@router.post(
    "/pause",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def pause(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).pause(_site_id(request)))


@router.post(
    "/resume",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).resume(_site_id(request)))


@router.post(
    "/stop",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def stop(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).stop(_site_id(request), archive=False))


@router.post(
    "/stop-and-archive",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def stop_and_archive(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).stop(_site_id(request), archive=True))


@router.get("/trains", response_model=GroundUnattendedTrainPageDTO)
def trains(request: Request) -> GroundUnattendedTrainPageDTO:
    return _call(lambda: _service(request).list_trains(_site_id(request)))


@router.get("/trains/{train_id}", response_model=GroundUnattendedTrainDTO)
def train(request: Request, train_id: str) -> GroundUnattendedTrainDTO:
    return _call(lambda: _service(request).get_train(_site_id(request), train_id))


@router.put("/trains/{train_id}/priority", response_model=GroundUnattendedTrainDTO)
def update_priority(
    request: Request,
    train_id: str,
    payload: GroundPriorityUpdateDTO,
) -> GroundUnattendedTrainDTO:
    return _call(
        lambda: _service(request).set_priority(
            _site_id(request), train_id, payload.priority
        )
    )


@router.get("/ping-targets", response_model=GroundPingSummaryPageDTO)
def ping_targets(request: Request) -> GroundPingSummaryPageDTO:
    return _call(lambda: _service(request).ping_summary(_site_id(request)))


@router.get("/ping-summary", response_model=GroundPingSummaryPageDTO)
def ping_summary(request: Request) -> GroundPingSummaryPageDTO:
    return _call(lambda: _service(request).ping_summary(_site_id(request)))


@router.get("/timeline", response_model=GroundTimelinePageDTO)
def timeline(
    request: Request,
    train_id: str = Query(default="", max_length=100),
    event_type: str = Query(default="", max_length=100),
) -> GroundTimelinePageDTO:
    return _call(
        lambda: _service(request).timeline(
            _site_id(request), train_id=train_id, event_type=event_type
        )
    )


@router.get("/deep-collections", response_model=GroundDeepCollectionPageDTO)
def deep_collections(request: Request) -> GroundDeepCollectionPageDTO:
    return _call(lambda: _service(request).deep_collections(_site_id(request)))


@router.get("/coverage", response_model=GroundDeepCollectionPageDTO)
def coverage(request: Request) -> GroundDeepCollectionPageDTO:
    return _call(lambda: _service(request).deep_collections(_site_id(request)))


@router.get("/archives", response_model=GroundArchivePageDTO)
def archives(request: Request) -> GroundArchivePageDTO:
    return _call(lambda: _service(request).archives(_site_id(request)))


@router.get("/archives/{archive_id}", response_model=GroundArchiveDTO)
def archive(request: Request, archive_id: str) -> GroundArchiveDTO:
    return _call(lambda: _service(request).archive(_site_id(request), archive_id))


@router.get("/archives/{archive_id}/summary-download")
def download_archive_summary(request: Request, archive_id: str) -> Response:
    item = _call(lambda: _service(request).archive(_site_id(request), archive_id))
    content = (
        json.dumps(item.summary, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{item.run_date}_ground_unattended_summary.json"'
            )
        },
    )


@router.post("/archives/open-directory", response_model=DesktopActionDTO)
def open_archive_directory(request: Request) -> DesktopActionDTO:
    return _call(lambda: _service(request).open_archive_directory(_site_id(request)))


@router.delete(
    "/archives/{archive_id}",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_archive(
    request: Request,
    archive_id: str,
    payload: GroundArchiveDeleteRequestDTO,
) -> GroundActionResponseDTO:
    return _call(
        lambda: _service(request).request_delete_archive(
            _site_id(request),
            archive_id,
            confirmed=payload.explicit_confirmation,
        )
    )


def _call(callback):
    try:
        return callback()
    except GroundUnattendedError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


__all__ = ["router"]
