from __future__ import annotations

from fastapi import APIRouter, Query, Request

from netconsole.core.sites import SiteManager
from netconsole.models.api.common import ApiResponse
from netconsole.models.api.online_mr import (
    OnlineMrCollectorStatusDTO,
    OnlineMrRawFileDTO,
    OnlineMrRawTailDTO,
    OnlineMrRealtimePreviewDTO,
    OnlineMrSessionDetailDTO,
    OnlineMrSessionSummaryDTO,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService


router = APIRouter(prefix="/online-mr", tags=["online-mr"])


def _service(request: Request) -> OnlineMrQueryService:
    return request.app.state.online_mr_query_service


def _site_id(request: Request) -> str:
    return str(SiteManager(request.app.state.paths).get_current_site() or "demo")


@router.get("/sessions/current", response_model=ApiResponse[OnlineMrSessionDetailDTO | None])
def current_session(request: Request) -> ApiResponse[OnlineMrSessionDetailDTO | None]:
    return ApiResponse(data=_service(request).get_current_session(_site_id(request)))


@router.get("/sessions/recent", response_model=ApiResponse[list[OnlineMrSessionSummaryDTO]])
def recent_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[list[OnlineMrSessionSummaryDTO]]:
    return ApiResponse(data=_service(request).list_sessions(_site_id(request), limit=limit))


@router.get("/sessions/{session_id}", response_model=ApiResponse[OnlineMrSessionDetailDTO])
def session_detail(request: Request, session_id: str) -> ApiResponse[OnlineMrSessionDetailDTO]:
    return ApiResponse(data=_service(request).get_session(_site_id(request), session_id))


@router.get("/sessions/{session_id}/collectors", response_model=ApiResponse[list[OnlineMrCollectorStatusDTO]])
def collectors(request: Request, session_id: str) -> ApiResponse[list[OnlineMrCollectorStatusDTO]]:
    return ApiResponse(data=_service(request).list_collectors(_site_id(request), session_id))


@router.get("/sessions/{session_id}/preview", response_model=ApiResponse[OnlineMrRealtimePreviewDTO])
def preview(request: Request, session_id: str) -> ApiResponse[OnlineMrRealtimePreviewDTO]:
    return ApiResponse(data=_service(request).get_realtime_preview(_site_id(request), session_id))


@router.get("/sessions/{session_id}/raw-tail", response_model=ApiResponse[OnlineMrRawTailDTO])
def raw_tail(
    request: Request,
    session_id: str,
    name: str,
    tail: int = Query(default=200, ge=1, le=500),
) -> ApiResponse[OnlineMrRawTailDTO]:
    return ApiResponse(data=_service(request).read_raw_tail(_site_id(request), session_id, name, tail=tail))


@router.get("/sessions/{session_id}/raw-summary", response_model=ApiResponse[list[OnlineMrRawFileDTO]])
def raw_summary(request: Request, session_id: str) -> ApiResponse[list[OnlineMrRawFileDTO]]:
    return ApiResponse(data=_service(request).get_raw_summary(_site_id(request), session_id))


@router.get("/sessions/{session_id}/logs", response_model=ApiResponse[OnlineMrRawTailDTO])
def collector_logs(
    request: Request,
    session_id: str,
    tail: int = Query(default=200, ge=1, le=500),
) -> ApiResponse[OnlineMrRawTailDTO]:
    return ApiResponse(data=_service(request).read_raw_tail(_site_id(request), session_id, "collector_output", tail=tail))


__all__ = ["router"]
